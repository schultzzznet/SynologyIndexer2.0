#!/usr/bin/env python3
"""
Motion Detection Processor - Orchestrates scanning, detection, and database updates
"""
import time
import logging
from pathlib import Path
from typing import Dict
from multiprocessing import Pool, cpu_count

from database import DatabaseManager
from scanner import VideoScanner, VideoFile
from detector import MotionDetector, format_time

# Global detector instance for worker processes (initialized once per worker)
_worker_detector = None


class MotionProcessor:
    """Orchestrates the motion detection pipeline."""
    
    def __init__(self, root_dir: Path, db_path: Path, config: Dict, progress_callback=None):
        self.root_dir = root_dir
        self.db = DatabaseManager(db_path)
        self.scanner = VideoScanner(root_dir)
        self.config = config
        self.progress_callback = progress_callback
        self.logger = logging.getLogger("processor")
    
    def run_scan(self):
        """Run complete scan: discover videos, detect motion, update database."""
        self.logger.info("="*70)
        self.logger.info("Starting Motion Detection Scan")
        self.logger.info(f"Root directory: {self.root_dir}")
        self.logger.info(f"Workers: {self.config.get('parallel_workers', 1)}")
        self.logger.info("="*70)
        
        # Scan for videos
        all_videos = self.scanner.scan_all_videos()
        
        # Report initial count
        if self.progress_callback:
            self.progress_callback({
                'total': len(all_videos),
                'processed': 0,
                'current_file': 'Scanning complete, starting processing...',
                'has_motion': False,
                'segments': 0
            })
        
        # Cleanup deleted videos from database
        existing_paths = {str(v.path) for v in all_videos}
        self.db.cleanup_deleted_videos(existing_paths)
        
        # Filter to unprocessed videos
        processed_hashes = {v.hash for v in all_videos if self.db.is_processed(v.hash)}
        videos_to_process = [v for v in all_videos if v.hash not in processed_hashes]
        
        if len(videos_to_process) < len(all_videos):
            skipped = len(all_videos) - len(videos_to_process)
            self.logger.info(f"Skipping {skipped} already-processed videos")
        
        if not videos_to_process:
            self.logger.info("No new videos to process")
            return
        
        self.logger.info(f"Processing {len(videos_to_process)} videos...")
        
        # Process videos
        workers = self.config.get("parallel_workers", min(cpu_count(), 4))
        
        if workers > 1:
            self._process_parallel(videos_to_process, workers)
        else:
            self._process_sequential(videos_to_process)
        
        # Print statistics
        stats = self.db.get_statistics()
        self.logger.info("="*70)
        self.logger.info("Scan Complete")
        self.logger.info(f"Total processed: {stats['total_processed']}")
        self.logger.info(f"Videos with motion: {stats['videos_with_motion']}")
        self.logger.info(f"Total segments: {stats['total_segments']}")
        self.logger.info(f"Total previews: {stats['total_previews']}")
        self.logger.info("="*70)
    
    def _process_parallel(self, videos: list, workers: int):
        """Process videos in parallel with real-time progress updates."""
        total_videos = len(videos)
        processed_count = 0
        
        # Process all videos with a persistent pool for real-time updates
        work_args = [(v, self.config) for v in videos]
        
        with Pool(processes=workers, initializer=init_worker, initargs=(self.config,)) as pool:
            # Use imap_unordered to get results as they complete (not in order)
            for video, segments, metadata, error in pool.imap_unordered(process_video_worker_wrapper, work_args, chunksize=1):
                processed_count += 1
                
                # Report progress via callback
                if self.progress_callback:
                    self.progress_callback({
                        'total': total_videos,
                        'processed': processed_count,
                        'current_file': video.path.name,
                        'has_motion': len(segments) > 0,
                        'segments': len(segments)
                    })
                
                self._save_results(video, segments, metadata, error)
                
                # Log progress every 50 videos
                if processed_count % 50 == 0:
                    self.logger.info(f"Progress: {processed_count}/{total_videos} videos")
    
    def _process_sequential(self, videos: list):
        """Process videos sequentially."""
        for video in videos:
            _, segments, metadata, error = process_video_worker(video, self.config)
            self._save_results(video, segments, metadata, error)
    
    def _save_results(self, video: VideoFile, segments: list, metadata: Dict, error: str):
        """Save processing results to database."""
        if error:
            self.logger.error(f"{video.path.name}: {error}")
            self.db.mark_processed(
                video.hash, str(video.path), video.size, video.modified,
                processing_duration=0, has_motion=False, error_message=error
            )
            return
        
        # Mark video as processed with brightness metrics
        processing_time = metadata.get("processing_duration", 0)
        has_motion = len(segments) > 0
        brightness = metadata.get("brightness", None)
        brightness_factor = metadata.get("brightness_factor", None)
        preprocessing = "CLAHE" if brightness_factor == "dark" else None
        
        self.db.mark_processed(
            video.hash, str(video.path), video.size, video.modified,
            processing_duration=processing_time, has_motion=has_motion,
            brightness_level=brightness, preprocessing_applied=preprocessing
        )
        
        # Add motion segments
        for idx, segment in enumerate(segments, 1):
            self.db.add_motion_segment(
                video.hash, idx,
                format_time(segment.start_time),
                format_time(segment.end_time),
                segment.end_time - segment.start_time,
                segment.max_motion_area,
                segment.detected_objects,
                len(segment.preview_frames)
            )
        
        # Log result
        if segments:
            self.logger.info(
                f"{video.path.name}: {len(segments)} segment(s) "
                f"[{metadata.get('brightness_factor', 'normal')}]"
            )
        else:
            self.logger.info(f"{video.path.name}: No motion detected")
    
    def run_validation_scan(self, validation_model: str = "yolov8x.pt", 
                           rare_objects: list = None):
        """
        Run validation scan on videos with rare/unusual objects.
        Re-processes them with a more accurate model for sanity checking.
        
        Args:
            validation_model: Higher accuracy model (yolov8x.pt, yolov8l.pt, etc.)
            rare_objects: List of object names to validate (bear, bed, horse, etc.)
        """
        if rare_objects is None:
            # Default rare objects that need validation
            rare_objects = [
                'bear', 'bed', 'horse', 'backpack', 'skateboard', 
                'train', 'elephant', 'giraffe', 'zebra', 'umbrella'
            ]
        
        self.logger.info("="*70)
        self.logger.info("Starting Validation Scan")
        self.logger.info(f"Validation model: {validation_model}")
        self.logger.info(f"Rare objects to validate: {', '.join(rare_objects)}")
        self.logger.info("="*70)
        
        # Get videos needing validation
        videos_to_validate = self.db.get_videos_for_validation(rare_objects)
        
        if not videos_to_validate:
            self.logger.info("No videos with rare objects found to validate")
            return
        
        self.logger.info(f"Found {len(videos_to_validate)} videos to validate")
        
        # Create validation config with better model
        validation_config = self.config.copy()
        validation_config['yolo_model'] = validation_model
        validation_config['parallel_workers'] = 1  # Slow model, sequential is better
        
        # Process each video with validation model
        validated_count = 0
        for video_info in videos_to_validate:
            video_path = Path(video_info['video_path'])
            
            if not video_path.exists():
                self.logger.warning(f"Video not found, skipping: {video_path}")
                continue
            
            try:
                # Create VideoFile object
                from scanner import VideoFile
                import hashlib
                video = VideoFile(
                    path=video_path,
                    size=video_info['file_size'],
                    modified=video_info['last_modified'],
                    hash=video_info['video_hash']
                )
                
                # Re-analyze with validation model
                detector = MotionDetector(validation_config)
                segments, metadata = detector.analyze_video(video_path)
                
                # Clear old segments for this video
                with self.db.transaction() as conn:
                    conn.execute(
                        "DELETE FROM motion_segments WHERE video_hash = ?",
                        (video.hash,)
                    )
                
                # Save new segments
                for idx, segment in enumerate(segments, 1):
                    self.db.add_motion_segment(
                        video.hash, idx,
                        format_time(segment.start_time),
                        format_time(segment.end_time),
                        segment.end_time - segment.start_time,
                        segment.max_motion_area,
                        segment.detected_objects,
                        len(segment.preview_frames)
                    )
                
                # Mark as validated
                self.db.mark_validated(video.hash, validation_model)
                validated_count += 1
                
                self.logger.info(
                    f"✓ Validated {video_path.name}: {len(segments)} segment(s) "
                    f"(was: {video_info.get('all_objects', 'unknown')})"
                )
                
                # Report progress
                if self.progress_callback:
                    self.progress_callback({
                        'total': len(videos_to_validate),
                        'processed': validated_count,
                        'current_file': f"Validating: {video_path.name}",
                        'has_motion': len(segments) > 0,
                        'segments': len(segments)
                    })
                
            except Exception as e:
                self.logger.error(f"Validation failed for {video_path.name}: {e}")
        
        self.logger.info("="*70)
        self.logger.info(f"Validation Complete: {validated_count}/{len(videos_to_validate)} videos")
        self.logger.info("="*70)


def init_worker(config: Dict):
    """Initialize worker process with a reusable detector instance."""
    global _worker_detector
    _worker_detector = MotionDetector(config)


def process_video_worker(video: VideoFile, config: Dict):
    """Worker function for parallel processing - reuses detector from init_worker."""
    global _worker_detector
    
    try:
        start_time = time.time()
        
        # Reuse the detector that was initialized once for this worker
        segments, metadata = _worker_detector.analyze_video(video.path)
        
        metadata["processing_duration"] = time.time() - start_time
        
        return video, segments, metadata, None
    
    except Exception as e:
        return video, [], {}, str(e)


def process_video_worker_wrapper(args):
    """Wrapper for imap_unordered - unpacks tuple arguments."""
    video, config = args
    return process_video_worker(video, config)

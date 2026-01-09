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


class MotionProcessor:
    """Orchestrates the motion detection pipeline."""
    
    def __init__(self, root_dir: Path, db_path: Path, config: Dict):
        self.root_dir = root_dir
        self.db = DatabaseManager(db_path)
        self.scanner = VideoScanner(root_dir)
        self.config = config
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
        """Process videos in parallel, saving in batches."""
        batch_size = 50  # Save every 50 videos
        
        for i in range(0, len(videos), batch_size):
            batch = videos[i:i + batch_size]
            work_args = [(v, self.config) for v in batch]
            
            with Pool(processes=workers) as pool:
                results = pool.starmap(process_video_worker, work_args)
            
            # Save batch results
            for video, segments, metadata, error in results:
                self._save_results(video, segments, metadata, error)
            
            self.logger.info(f"Progress: {min(i + batch_size, len(videos))}/{len(videos)} videos")
    
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
        
        # Mark video as processed
        processing_time = metadata.get("processing_duration", 0)
        has_motion = len(segments) > 0
        
        self.db.mark_processed(
            video.hash, str(video.path), video.size, video.modified,
            processing_duration=processing_time, has_motion=has_motion
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


def process_video_worker(video: VideoFile, config: Dict):
    """Worker function for parallel processing."""
    try:
        start_time = time.time()
        
        detector = MotionDetector(config)
        segments, metadata = detector.analyze_video(video.path)
        
        metadata["processing_duration"] = time.time() - start_time
        
        return video, segments, metadata, None
    
    except Exception as e:
        return video, [], {}, str(e)

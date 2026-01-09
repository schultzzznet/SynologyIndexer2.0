#!/usr/bin/env python3
"""
Motion Detector - Core video analysis logic using OpenCV and YOLO
"""
import cv2
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from datetime import timedelta

try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False


@dataclass
class MotionSegment:
    """Represents a detected motion segment."""
    start_time: float
    end_time: float
    max_motion_area: int
    detected_objects: str
    preview_frames: List[int]


class MotionDetector:
    """Detects motion in video files using OpenCV background subtraction and YOLO."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger("detector")
        self.yolo_model = None
        
        if HAS_YOLO and config.get("enable_yolo", True):
            try:
                self.yolo_model = YOLO("yolov8n.pt")
                self.logger.info("YOLO model loaded")
            except Exception as e:
                self.logger.warning(f"Failed to load YOLO: {e}")
    
    def analyze_video(self, video_path: Path) -> Tuple[List[MotionSegment], Dict]:
        """
        Analyze video for motion segments.
        Returns (segments, metadata) tuple.
        """
        self.logger.info(f"Analyzing: {video_path.name}")
        
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Initialize background subtractor
        bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=self.config.get("background_history", 500),
            varThreshold=self.config.get("background_var_threshold", 16),
            detectShadows=False
        )
        
        segments = []
        current_segment = None
        frame_idx = 0
        sample_every = self.config.get("sample_every_n_frames", 2)
        
        # Calculate brightness for adaptive thresholds
        brightness = self._calculate_brightness(cap)
        thresholds = self._get_adaptive_thresholds(brightness)
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frame_idx += 1
            if frame_idx % sample_every != 0:
                continue
            
            # Resize for faster processing
            resize_width = self.config.get("resize_width", 640)
            height, width = frame.shape[:2]
            scale = resize_width / width
            resized = cv2.resize(frame, (resize_width, int(height * scale)))
            
            # Apply background subtraction
            fg_mask = bg_subtractor.apply(resized)
            _, binary = cv2.threshold(fg_mask, thresholds["binary_threshold"], 255, cv2.THRESH_BINARY)
            
            # Find contours
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            max_area = max((cv2.contourArea(c) for c in contours), default=0)
            
            has_motion = max_area >= thresholds["min_motion_area"]
            current_time = frame_idx / fps
            
            if has_motion:
                if current_segment is None:
                    # Start new segment
                    current_segment = {
                        "start_frame": frame_idx,
                        "start_time": current_time,
                        "max_area": max_area,
                        "preview_frames": [frame_idx],
                        "grace_counter": 0
                    }
                else:
                    # Continue segment
                    current_segment["max_area"] = max(current_segment["max_area"], max_area)
                    current_segment["grace_counter"] = 0
                    # Save preview frame every N frames
                    if len(current_segment["preview_frames"]) < 5:
                        current_segment["preview_frames"].append(frame_idx)
            
            elif current_segment is not None:
                # Grace period for gaps
                current_segment["grace_counter"] += 1
                if current_segment["grace_counter"] >= self.config.get("end_grace_frames", 6):
                    # End segment
                    segment = self._finalize_segment(current_segment, current_time, video_path, cap)
                    if segment:
                        segments.append(segment)
                    current_segment = None
        
        # Finalize last segment if exists
        if current_segment is not None:
            segment = self._finalize_segment(current_segment, frame_idx / fps, video_path, cap)
            if segment:
                segments.append(segment)
        
        cap.release()
        
        metadata = {
            "brightness": brightness,
            "brightness_factor": "dark" if brightness < 60 else "normal",
            "thresholds": thresholds,
            "total_frames": total_frames,
            "fps": fps
        }
        
        return segments, metadata
    
    def _calculate_brightness(self, cap: cv2.VideoCapture) -> float:
        """Sample frames to calculate average brightness."""
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        brightness_values = []
        
        for _ in range(5):  # Sample 5 frames
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness_values.append(gray.mean())
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Reset to start
        return sum(brightness_values) / len(brightness_values) if brightness_values else 80
    
    def _get_adaptive_thresholds(self, brightness: float) -> Dict:
        """Adjust detection thresholds based on brightness."""
        if brightness < 60:  # Dark video
            return {
                "min_motion_area": int(self.config.get("min_motion_area", 800) * 1.5),
                "binary_threshold": 120,
                "background_var_threshold": int(self.config.get("background_var_threshold", 16) * 0.7)
            }
        else:  # Normal brightness
            return {
                "min_motion_area": self.config.get("min_motion_area", 800),
                "binary_threshold": 150,
                "background_var_threshold": self.config.get("background_var_threshold", 16)
            }
    
    def _finalize_segment(self, segment_data: Dict, end_time: float, 
                         video_path: Path, cap: cv2.VideoCapture) -> Optional[MotionSegment]:
        """Finalize a motion segment and generate previews."""
        duration = end_time - segment_data["start_time"]
        min_duration = self.config.get("min_segment_duration", 0.5)
        
        if duration < min_duration:
            return None
        
        # Save preview images
        preview_dir = video_path.parent
        stem = video_path.stem
        saved_previews = []
        
        for idx, frame_num in enumerate(segment_data["preview_frames"][:5]):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if ret:
                preview_path = preview_dir / f"{stem}_seg{len(saved_previews):03d}_f{frame_num}.jpg"
                cv2.imwrite(str(preview_path), frame)
                saved_previews.append(frame_num)
        
        # YOLO detection on first preview
        detected_objects = ""
        if self.yolo_model and saved_previews:
            cap.set(cv2.CAP_PROP_POS_FRAMES, saved_previews[0])
            ret, frame = cap.read()
            if ret:
                detected_objects = self._detect_objects(frame)
        
        return MotionSegment(
            start_time=segment_data["start_time"],
            end_time=end_time,
            max_motion_area=segment_data["max_area"],
            detected_objects=detected_objects,
            preview_frames=saved_previews
        )
    
    def _detect_objects(self, frame) -> str:
        """Detect objects using YOLO."""
        if not self.yolo_model:
            return ""
        
        try:
            results = self.yolo_model(frame, verbose=False)
            objects = []
            for r in results:
                for box in r.boxes:
                    cls = int(box.cls[0])
                    conf = float(box.conf[0])
                    if conf > 0.5:
                        objects.append(r.names[cls])
            return ", ".join(sorted(set(objects))) if objects else ""
        except Exception as e:
            self.logger.warning(f"YOLO detection failed: {e}")
            return ""


def format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    return str(timedelta(seconds=int(seconds)))

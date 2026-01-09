#!/usr/bin/env python3
"""
Video Scanner - Discovers and tracks video files in surveillance directories
"""
import hashlib
import logging
from pathlib import Path
from typing import List, Set, Dict
from dataclasses import dataclass


@dataclass
class VideoFile:
    """Represents a video file with metadata."""
    path: Path
    hash: str
    size: int
    modified: int  # Unix timestamp


class VideoScanner:
    """Scans directories for video files and generates stable hashes."""
    
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".ts"}
    SKIP_PATTERNS = ["@SSRECMETA", "@Snapshot", "Thumbnail", "Preview", "RecLog"]
    
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.logger = logging.getLogger("scanner")
    
    def scan_all_videos(self) -> List[VideoFile]:
        """Scan root directory recursively for video files."""
        self.logger.info(f"Scanning for videos in: {self.root_dir}")
        
        videos = []
        for video_path in self._find_video_files():
            try:
                stat = video_path.stat()
                video = VideoFile(
                    path=video_path,
                    hash=self._generate_hash(video_path),
                    size=stat.st_size,
                    modified=int(stat.st_mtime)
                )
                videos.append(video)
            except Exception as e:
                self.logger.warning(f"Failed to stat {video_path}: {e}")
        
        self.logger.info(f"Found {len(videos)} video files")
        return videos
    
    def _find_video_files(self) -> List[Path]:
        """Recursively find all video files, excluding skip patterns."""
        videos = []
        
        for path in self.root_dir.rglob("*"):
            if not path.is_file():
                continue
            
            # Check extension
            if path.suffix.lower() not in self.VIDEO_EXTENSIONS:
                continue
            
            # Check skip patterns
            if any(pattern in str(path) for pattern in self.SKIP_PATTERNS):
                continue
            
            videos.append(path)
        
        return videos
    
    def _generate_hash(self, video_path: Path) -> str:
        """Generate stable hash for video path (relative to root)."""
        relative_path = str(video_path.relative_to(self.root_dir))
        return hashlib.sha256(relative_path.encode()).hexdigest()[:16]

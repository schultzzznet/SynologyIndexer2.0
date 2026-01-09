#!/usr/bin/env python3
"""
SQLite Database Manager for Motion Detection Results
Handles all persistence with ACID guarantees and proper indexing.
"""
import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set
from contextlib import contextmanager
from datetime import datetime


class DatabaseManager:
    """Manages SQLite database for motion detection results and processing state."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.logger = logging.getLogger("database")
        self._init_database()
    
    def _init_database(self):
        """Initialize database schema with proper indexes."""
        with self.transaction() as conn:
            # Videos table - tracks all scanned videos and processing state
            conn.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    video_hash TEXT PRIMARY KEY,
                    video_path TEXT UNIQUE NOT NULL,
                    file_size INTEGER NOT NULL,
                    last_modified INTEGER NOT NULL,
                    processed_at TEXT,
                    processing_duration_sec REAL,
                    has_motion BOOLEAN NOT NULL DEFAULT 0,
                    error_message TEXT
                )
            """)
            
            # Motion segments table - stores detected motion events
            conn.execute("""
                CREATE TABLE IF NOT EXISTS motion_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_hash TEXT NOT NULL,
                    segment_index INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_sec REAL NOT NULL,
                    max_motion_area INTEGER NOT NULL,
                    detected_objects TEXT,
                    preview_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (video_hash) REFERENCES videos(video_hash) ON DELETE CASCADE,
                    UNIQUE(video_hash, segment_index)
                )
            """)
            
            # Indexes for fast queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_path ON videos(video_path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_processed ON videos(processed_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_has_motion ON videos(has_motion)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_video ON motion_segments(video_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_created ON motion_segments(created_at)")
            
        self.logger.info(f"Database initialized: {self.db_path}")
    
    @contextmanager
    def transaction(self):
        """Context manager for database transactions with automatic commit/rollback."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Access columns by name
        conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key constraints
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Transaction failed: {e}")
            raise
        finally:
            conn.close()
    
    def is_processed(self, video_hash: str) -> bool:
        """Check if a video has been processed."""
        with self.transaction() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM videos WHERE video_hash = ? AND processed_at IS NOT NULL",
                (video_hash,)
            )
            return cursor.fetchone() is not None
    
    def get_unprocessed_hashes(self) -> Set[str]:
        """Get all video hashes that have NOT been processed."""
        with self.transaction() as conn:
            cursor = conn.execute(
                "SELECT video_hash FROM videos WHERE processed_at IS NULL"
            )
            return {row[0] for row in cursor.fetchall()}
    
    def mark_processed(self, video_hash: str, video_path: str, file_size: int, 
                      last_modified: int, processing_duration: float, has_motion: bool,
                      error_message: Optional[str] = None):
        """Mark a video as processed with metadata."""
        with self.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO videos 
                (video_hash, video_path, file_size, last_modified, processed_at, 
                 processing_duration_sec, has_motion, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                video_hash, str(video_path), file_size, last_modified,
                datetime.utcnow().isoformat(), processing_duration, has_motion, error_message
            ))
    
    def add_motion_segment(self, video_hash: str, segment_index: int, 
                          start_time: str, end_time: str, duration_sec: float,
                          max_motion_area: int, detected_objects: str, preview_count: int):
        """Add a motion segment for a video."""
        with self.transaction() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO motion_segments
                (video_hash, segment_index, start_time, end_time, duration_sec,
                 max_motion_area, detected_objects, preview_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                video_hash, segment_index, start_time, end_time, duration_sec,
                max_motion_area, detected_objects, preview_count
            ))
    
    def cleanup_deleted_videos(self, existing_video_paths: Set[str]) -> int:
        """Remove database entries for videos that no longer exist on disk."""
        with self.transaction() as conn:
            cursor = conn.execute("SELECT video_path FROM videos")
            all_db_paths = {row[0] for row in cursor.fetchall()}
            
            deleted_paths = all_db_paths - existing_video_paths
            if not deleted_paths:
                return 0
            
            placeholders = ','.join('?' * len(deleted_paths))
            cursor = conn.execute(
                f"DELETE FROM videos WHERE video_path IN ({placeholders})",
                list(deleted_paths)
            )
            deleted_count = cursor.rowcount
            self.logger.info(f"Cleaned up {deleted_count} deleted videos from database")
            return deleted_count
    
    def get_all_motion_events(self) -> List[Dict]:
        """Get all motion events with video information, sorted by creation time."""
        with self.transaction() as conn:
            cursor = conn.execute("""
                SELECT 
                    v.video_path,
                    m.segment_index,
                    m.start_time,
                    m.end_time,
                    m.duration_sec,
                    m.max_motion_area,
                    m.detected_objects,
                    m.preview_count,
                    m.created_at
                FROM motion_segments m
                JOIN videos v ON m.video_hash = v.video_hash
                ORDER BY m.created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_statistics(self) -> Dict:
        """Get processing statistics."""
        with self.transaction() as conn:
            stats = {}
            
            # Total videos processed
            cursor = conn.execute("SELECT COUNT(*) FROM videos WHERE processed_at IS NOT NULL")
            stats['total_processed'] = cursor.fetchone()[0]
            
            # Videos with motion
            cursor = conn.execute("SELECT COUNT(*) FROM videos WHERE has_motion = 1")
            stats['videos_with_motion'] = cursor.fetchone()[0]
            
            # Total motion segments
            cursor = conn.execute("SELECT COUNT(*) FROM motion_segments")
            stats['total_segments'] = cursor.fetchone()[0]
            
            # Total previews
            cursor = conn.execute("SELECT SUM(preview_count) FROM motion_segments")
            result = cursor.fetchone()[0]
            stats['total_previews'] = result if result else 0
            
            # Average processing time
            cursor = conn.execute(
                "SELECT AVG(processing_duration_sec) FROM videos WHERE processing_duration_sec IS NOT NULL"
            )
            result = cursor.fetchone()[0]
            stats['avg_processing_time'] = round(result, 2) if result else 0
            
            return stats

#!/usr/bin/env python3
"""
Motion Detection Web Viewer - Flask UI for browsing motion events from SQLite database
"""
import os
import logging
import subprocess
import threading
import time
from pathlib import Path
from flask import Flask, jsonify, request, send_file

from database import DatabaseManager
from processor import MotionProcessor


# Configuration
SURVEILLANCE_ROOT = Path(os.environ.get('SURVEILLANCE_ROOT', '/surveillance'))
DATA_DIR = Path('/data')  # Local storage for database and logs
DB_PATH = DATA_DIR / 'motion_events.db'
LOG_DIR = DATA_DIR / 'logs'
AUTOSCAN_INTERVAL = int(os.environ.get('AUTOSCAN_INTERVAL', '60'))
WORKERS = int(os.environ.get('WORKERS', '2'))
YOLO_MODEL = os.environ.get('YOLO_MODEL', 'yolov8m.pt')

# Detection config
DETECTION_CONFIG = {
    "parallel_workers": WORKERS,
    "sample_every_n_frames": 2,
    "resize_width": 640,
    "min_motion_area": 800,
    "background_history": 500,
    "background_var_threshold": 16,
    "end_grace_frames": 6,
    "min_segment_duration": 0.5,
    "enable_yolo": True,
    "yolo_model": YOLO_MODEL,
    "preview_dir": str(DATA_DIR / "previews")
}

# Setup logging
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'motion_viewer.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize database
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
db = DatabaseManager(DB_PATH)

# Flask app
app = Flask(__name__)

# Global state
rebuild_status = {'running': False, 'message': '', 'progress': 0}


@app.route('/')
def index():
    """Serve the main HTML page."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Motion Detection Viewer 2.0</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            padding: 20px;
        }
        .header {
            background: linear-gradient(135deg, #1f6feb 0%, #0969da 100%);
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 8px 24px rgba(31, 111, 235, 0.2);
        }
        .header h1 {
            color: white;
            font-size: 32px;
            margin-bottom: 10px;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: #161b22;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #30363d;
        }
        .stat-value {
            font-size: 28px;
            font-weight: bold;
            color: #58a6ff;
        }
        .stat-label {
            color: #8b949e;
            margin-top: 5px;
        }
        .controls {
            background: #161b22;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #30363d;
        }
        .btn {
            background: #238636;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            margin-right: 10px;
        }
        .btn:hover { background: #2ea043; }
        .btn-danger { background: #da3633; }
        .btn-danger:hover { background: #f85149; }
        .filters {
            margin: 20px 0;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .filter-input {
            padding: 8px 12px;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            color: #c9d1d9;
        }
        .filter-btn {
            padding: 6px 12px;
            background: #21262d;
            border: 1px solid #30363d;
            border-radius: 6px;
            color: #c9d1d9;
            cursor: pointer;
            font-size: 13px;
            transition: all 0.2s;
        }
        .filter-btn:hover {
            background: #30363d;
            border-color: #58a6ff;
        }
        .filter-btn.active {
            background: #1f6feb;
            border-color: #1f6feb;
            color: white;
        }
        .events-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
            gap: 20px;
        }
        .event-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            overflow: hidden;
            transition: transform 0.2s;
            cursor: pointer;
            text-decoration: none;
            color: inherit;
            display: block;
        }
        .event-card:hover {
            transform: translateY(-4px);
            border-color: #58a6ff;
        }
        .preview-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
            gap: 4px;
            padding: 4px;
            background: #0d1117;
        }
        .event-preview {
            width: 100%;
            height: 120px;
            object-fit: cover;
            background: #0d1117;
            border-radius: 4px;
        }
        .event-info {
            padding: 15px;
        }
        .event-time {
            color: #58a6ff;
            font-weight: bold;
            margin-bottom: 8px;
        }
        .event-meta {
            color: #8b949e;
            font-size: 13px;
            margin: 4px 0;
        }
        .tags {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 10px;
        }
        .tag {
            background: #1f6feb;
            color: white;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
        }
        .scan-details {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #30363d;
        }
        .scan-badge {
            background: #30363d;
            color: #8b949e;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 500;
        }
        .scan-badge.low-light {
            background: #1f2937;
            color: #fbbf24;
        }
        .scan-badge.normal-light {
            background: #1f2937;
            color: #60a5fa;
        }
        .scan-badge.enhancement {
            background: #581c87;
            color: #e9d5ff;
        }
        .status {
            padding: 15px;
            border-radius: 6px;
            margin: 20px 0;
            background: #1f6feb;
            color: white;
        }
        .processing-status {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: #238636;
            color: white;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 1000;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        .progress-bar {
            width: 100%;
            height: 4px;
            background: rgba(255,255,255,0.2);
            border-radius: 2px;
            margin-top: 10px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: white;
            transition: width 0.3s;
        }
    </style>
</head>
<body>
    <div id="processing-status" class="processing-status" style="display:none;">
        <strong>⚙️ Processing:</strong> <span id="status-message">Scanning...</span>
    </div>
    
    <div class="header">
        <h1>🎥 Motion Detection Viewer 2.0</h1>
        <p>SQLite-powered surveillance event browser</p>
    </div>

    <div class="stats" id="stats"></div>

    <div class="controls">
        <button class="btn" onclick="rebuild()">🔄 Rebuild Index</button>
        <button class="btn" onclick="validateRareObjects()">✓ Validate Rare Objects</button>
        <button class="btn" onclick="clearRecent()">🗑️ Clear Last 24h</button>
        <button class="btn" onclick="refreshEvents()">↻ Refresh</button>
        <label style="margin-left: 15px; color: #c9d1d9;">
            <input type="checkbox" id="onlyWithObjects" onchange="filterEvents()" style="margin-right: 5px;">
            Only show detected objects
        </label>
        <span id="rebuild-status"></span>
    </div>

    <div class="filters">
        <input type="text" class="filter-input" placeholder="Search video name..." 
               id="searchInput" oninput="filterEvents()" style="flex: 1;">
        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
            <label style="color: #8b949e; font-size: 13px;">Sort by:</label>
            <select class="filter-input" id="sortField" onchange="filterEvents()" style="width: auto;">
                <option value="time">Time (newest first)</option>
                <option value="time-asc">Time (oldest first)</option>
                <option value="duration">Duration (longest)</option>
                <option value="duration-asc">Duration (shortest)</option>
                <option value="segments">Segment count (most)</option>
                <option value="segments-asc">Segment count (least)</option>
                <option value="name">Name (A→Z)</option>
                <option value="name-desc">Name (Z→A)</option>
            </select>
        </div>
    </div>
    
    <div class="filters" id="object-filters">
        <div style="display: flex; gap: 5px; flex-wrap: wrap; align-items: center;">
            <span style="color: #8b949e; font-size: 13px; margin-right: 5px;">Objects:</span>
            <span style="color: #8b949e; font-size: 12px; margin-left: 10px; font-style: italic;">(Click multiple to filter)</span>
        </div>
    </div>

    <div class="events-grid" id="events"></div>

    <script>
        let allEvents = [];
        let rebuilding = false;
        let selectedObjectFilters = new Set(); // Multi-select

        async function loadStats() {
            const res = await fetch('/api/statistics');
            const stats = await res.json();
            document.getElementById('stats').innerHTML = `
                <div class="stat-card">
                    <div class="stat-value">${stats.total_processed}</div>
                    <div class="stat-label">Videos Processed</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.videos_with_motion}</div>
                    <div class="stat-label">With Motion</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.total_segments}</div>
                    <div class="stat-label">Motion Segments</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.total_previews}</div>
                    <div class="stat-label">Preview Images</div>
                </div>
            `;
        }

        async function loadEvents() {
            try {
                const res = await fetch('/api/events');
                if (!res.ok) {
                    throw new Error(`HTTP error! status: ${res.status}`);
                }
                allEvents = await res.json();
                console.log(`Loaded ${allEvents.length} events`);
                generateObjectFilters();
                filterEvents();
            } catch (error) {
                console.error('Error loading events:', error);
                document.getElementById('events').innerHTML = 
                    '<p style="grid-column: 1/-1; text-align:center; color:#ff6b6b;">Error loading events: ' + error.message + '</p>';
            }
        }
        
        function generateObjectFilters() {
            // Collect all unique detected objects
            const objectCounts = {};
            allEvents.forEach(e => {
                if (e.detected_objects) {
                    e.detected_objects.split(',').map(o => o.trim()).filter(o => o).forEach(obj => {
                        const objLower = obj.toLowerCase();
                        objectCounts[objLower] = (objectCounts[objLower] || 0) + 1;
                    });
                }
            });
            
            // Sort by frequency (most common first)
            const sortedObjects = Object.entries(objectCounts)
                .sort((a, b) => b[1] - a[1])
                .map(([obj, count]) => obj);
            
            // Object emoji mapping
            const emojis = {
                'person': '👤',
                'car': '🚗',
                'cat': '🐱',
                'dog': '🐕',
                'bird': '🐦',
                'bicycle': '🚲',
                'motorcycle': '🏍️',
                'truck': '🚚',
                'skateboard': '🛹',
                'bus': '🚌',
                'train': '🚆',
                'horse': '🐴',
                'bear': '🐻',
                'backpack': '🎒'
            };
            
            // Generate buttons
            const container = document.getElementById('object-filters').querySelector('div');
            
            // Clear existing buttons (keep only label and hint spans)
            const buttons = container.querySelectorAll('button');
            buttons.forEach(btn => btn.remove());
            
            // Get the hint span (last one) so we can insert before it
            const spans = container.querySelectorAll('span');
            const hintSpan = spans[spans.length - 1];
            
            // Add "All" button
            const allBtn = document.createElement('button');
            allBtn.className = 'filter-btn active';
            allBtn.setAttribute('data-filter', '');
            allBtn.textContent = 'All';
            allBtn.onclick = () => setObjectFilter('');
            container.insertBefore(allBtn, hintSpan);
            
            // Add buttons for each detected object
            sortedObjects.forEach(obj => {
                const btn = document.createElement('button');
                btn.className = 'filter-btn';
                btn.setAttribute('data-filter', obj);
                const emoji = emojis[obj] || '🏷️';
                const displayName = obj.charAt(0).toUpperCase() + obj.slice(1);
                btn.innerHTML = `${emoji} ${displayName}`;
                btn.onclick = () => setObjectFilter(obj);
                container.insertBefore(btn, hintSpan);
            });
        }
        
        async function checkProcessingStatus() {
            const res = await fetch('/api/rebuild/status');
            const status = await res.json();
            
            const statusDiv = document.getElementById('processing-status');
            const statusMessage = document.getElementById('status-message');
            
            if (status.running) {
                statusDiv.style.display = 'block';
                if (status.total && status.processed) {
                    const percent = Math.round((status.processed / status.total) * 100);
                    statusMessage.innerHTML = `${status.processed}/${status.total} (${percent}%) - ${status.current_file || 'Processing...'}`;
                } else {
                    statusMessage.textContent = status.message || 'Processing videos...';
                }
            } else {
                statusDiv.style.display = 'none';
            }
        }

        function setObjectFilter(filter) {
            if (filter === '') {
                // Clear all filters
                selectedObjectFilters.clear();
            } else {
                // Toggle filter
                if (selectedObjectFilters.has(filter)) {
                    selectedObjectFilters.delete(filter);
                } else {
                    selectedObjectFilters.add(filter);
                }
            }
            
            // Update button states
            document.querySelectorAll('.filter-btn').forEach(btn => {
                const btnFilter = btn.getAttribute('data-filter');
                if (btnFilter === '') {
                    // "All" button active when no filters selected
                    btn.classList.toggle('active', selectedObjectFilters.size === 0);
                } else {
                    btn.classList.toggle('active', selectedObjectFilters.has(btnFilter));
                }
            });
            
            filterEvents();
        }

        function filterEvents() {
            const search = document.getElementById('searchInput').value.toLowerCase();
            const onlyWithObjects = document.getElementById('onlyWithObjects').checked;

            const filtered = allEvents.filter(e => {
                // Search filter
                const matchesSearch = !search || (e.video_path || '').toLowerCase().includes(search);
                
                // Object filter - check if segment has ANY of the selected objects
                const hasObjects = e.detected_objects && e.detected_objects.trim() !== '';
                let matchesObject = selectedObjectFilters.size === 0; // If no filters, show all
                if (selectedObjectFilters.size > 0 && e.detected_objects) {
                    const objectList = e.detected_objects.toLowerCase().split(',').map(o => o.trim());
                    // Match if segment has ANY of the selected filters
                    matchesObject = Array.from(selectedObjectFilters).some(filter => objectList.includes(filter));
                }
                
                // Only with objects checkbox
                const passesObjectCheck = !onlyWithObjects || hasObjects;
                
                return matchesSearch && matchesObject && passesObjectCheck;
            });

            renderEvents(filtered);
            
            // Update count
            const container = document.getElementById('events');
            if (filtered.length > 0) {
                const videoCount = new Set(filtered.map(e => e.video_path)).size;
                const countMsg = `<p style="grid-column: 1/-1; text-align:center; color:#8b949e; margin-bottom: 20px;">Showing ${videoCount} videos (${filtered.length} segments)</p>`;
                container.innerHTML = countMsg + container.innerHTML;
            }
        }

        function renderEvents(events) {
            console.log(`Rendering ${events.length} events`);
            const container = document.getElementById('events');
            if (events.length === 0) {
                container.innerHTML = '<p style="grid-column: 1/-1; text-align:center; color:#8b949e;">No motion events found</p>';
                return;
            }

            // Group events by video_path
            const groupedEvents = {};
            events.forEach(e => {
                if (!groupedEvents[e.video_path]) {
                    groupedEvents[e.video_path] = [];
                }
                groupedEvents[e.video_path].push(e);
            });

            // Convert to array for sorting
            const groupedArray = Object.entries(groupedEvents).map(([videoPath, segments]) => {
                const videoName = videoPath.split('/').pop();
                const totalDuration = segments.reduce((sum, s) => sum + s.duration_sec, 0);
                
                // Parse date/time from filename for sorting (e.g., Fi9900P N-20260107-185348-1767808428216-7.mp4)
                const filenameMatch = videoName.match(/-(\d{8})-(\d{6})-/);
                let videoTimestamp = 0;
                if (filenameMatch) {
                    const dateStr = filenameMatch[1]; // 20260107
                    const timeStr = filenameMatch[2]; // 185348
                    const year = dateStr.substring(0, 4);
                    const month = dateStr.substring(4, 6);
                    const day = dateStr.substring(6, 8);
                    const hour = timeStr.substring(0, 2);
                    const min = timeStr.substring(2, 4);
                    const sec = timeStr.substring(4, 6);
                    videoTimestamp = new Date(`${year}-${month}-${day}T${hour}:${min}:${sec}`).getTime();
                } else {
                    // Fallback to segment start_time
                    const times = segments.map(s => new Date(s.start_time).getTime()).sort();
                    videoTimestamp = times[0];
                }
                
                return {
                    videoPath,
                    videoName,
                    segments,
                    totalDuration,
                    videoTimestamp,
                    segmentCount: segments.length
                };
            });

            // Sort based on selected field
            const sortField = document.getElementById('sortField').value;
            groupedArray.sort((a, b) => {
                switch(sortField) {
                    case 'time':
                        return b.videoTimestamp - a.videoTimestamp;
                    case 'time-asc':
                        return a.videoTimestamp - b.videoTimestamp;
                    case 'duration':
                        return b.totalDuration - a.totalDuration;
                    case 'duration-asc':
                        return a.totalDuration - b.totalDuration;
                    case 'segments':
                        return b.segmentCount - a.segmentCount;
                    case 'segments-asc':
                        return a.segmentCount - b.segmentCount;
                    case 'name':
                        return a.videoName.localeCompare(b.videoName);
                    case 'name-desc':
                        return b.videoName.localeCompare(a.videoName);
                    default:
                        return b.videoTimestamp - a.videoTimestamp;
                }
            });

            // Render sorted tiles
            container.innerHTML = groupedArray.map(group => {
                // Collect all unique detected objects across segments
                const allObjects = new Set();
                group.segments.forEach(s => {
                    if (s.detected_objects) {
                        s.detected_objects.split(',').map(o => o.trim()).filter(o => o).forEach(obj => allObjects.add(obj));
                    }
                });
                const objectsList = Array.from(allObjects);
                
                // Get scanning metadata from first segment
                const firstSeg = group.segments[0];
                const brightnessLevel = firstSeg.brightness_level;
                const preprocessingApplied = firstSeg.preprocessing_applied;
                const processingDuration = firstSeg.processing_duration_sec;
                
                // Parse date/time from filename (e.g., Fi9900P N-20260107-185348-1767808428216-7.mp4)
                // Format: CameraType-YYYYMMDD-HHMMSS-timestamp-id.mp4
                const filenameMatch = group.videoName.match(/-(\d{8})-(\d{6})-/);
                let displayTime = '';
                if (filenameMatch) {
                    const dateStr = filenameMatch[1]; // 20260107
                    const timeStr = filenameMatch[2]; // 185348
                    const year = dateStr.substring(0, 4);
                    const month = dateStr.substring(4, 6);
                    const day = dateStr.substring(6, 8);
                    const hour = timeStr.substring(0, 2);
                    const min = timeStr.substring(2, 4);
                    const sec = timeStr.substring(4, 6);
                    displayTime = `${year}-${month}-${day} ${hour}:${min}:${sec}`;
                } else {
                    // Fallback to segment times
                    const times = group.segments.map(s => s.start_time).sort();
                    displayTime = times[0];
                }
                
                // Build scan details HTML
                let scanDetailsHtml = '';
                if (brightnessLevel !== null && brightnessLevel !== undefined) {
                    const isLowLight = brightnessLevel < 60;
                    const brightnessIcon = isLowLight ? '🌙' : '☀️';
                    const brightnessClass = isLowLight ? 'low-light' : 'normal-light';
                    scanDetailsHtml += `<div class="scan-details">`;
                    scanDetailsHtml += `<span class="scan-badge ${brightnessClass}">${brightnessIcon} Brightness: ${brightnessLevel.toFixed(0)}</span>`;
                    
                    if (preprocessingApplied) {
                        scanDetailsHtml += `<span class="scan-badge enhancement">✨ Enhanced: ${preprocessingApplied}</span>`;
                    }
                    
                    if (processingDuration) {
                        scanDetailsHtml += `<span class="scan-badge">⚙️ Scan: ${processingDuration.toFixed(1)}s</span>`;
                    }
                    
                    scanDetailsHtml += `</div>`;
                }
                
                return `
                    <div class="event-card">
                        <a href="/api/video?path=${encodeURIComponent(group.videoPath)}" target="_blank" style="display: block; text-decoration: none; color: inherit;">
                            <div class="preview-grid">
                                ${group.segments.map(seg => `
                                    <img class="event-preview" 
                                         src="/api/preview?path=${encodeURIComponent(seg.video_path)}&segment=${seg.segment_index}"
                                         alt="Preview" loading="lazy"
                                         onerror="this.style.display='none';">
                                `).join('')}
                            </div>
                            <div class="event-info">
                                <div class="event-time">📅 ${displayTime}</div>
                                <div class="event-meta">📁 ${group.videoName}</div>
                                <div class="event-meta">🎬 ${group.segmentCount} motion segment${group.segmentCount > 1 ? 's' : ''}</div>
                                <div class="event-meta">⏱️ Total: ${group.totalDuration.toFixed(1)}s</div>
                                ${scanDetailsHtml}
                                ${objectsList.length > 0 ? `
                                    <div class="tags">
                                        ${objectsList.map(obj => `<span class="tag">🏷️ ${obj}</span>`).join('')}
                                    </div>
                                ` : ''}
                            </div>
                        </a>
                        <div style="padding: 10px; border-top: 1px solid #30363d; display: flex; gap: 10px; font-size: 11px; color: #8b949e;">
                            <a href="/api/video?path=${encodeURIComponent(group.videoPath)}&download=true" 
                               style="color: #58a6ff; text-decoration: none;"
                               download="${group.videoName}">⬇️ Download</a>
                            <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" 
                                  title="${group.videoPath}">💾 ${group.videoPath}</span>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function rebuild() {
            if (rebuilding) return;
            rebuilding = true;
            
            document.getElementById('rebuild-status').innerHTML = 
                '<span class="status">Rebuilding index...</span>';
            
            await fetch('/api/rebuild', { method: 'POST' });
            
            // Poll for completion
            const interval = setInterval(async () => {
                const res = await fetch('/api/rebuild/status');
                const status = await res.json();
                
                if (!status.running) {
                    clearInterval(interval);
                    rebuilding = false;
                    document.getElementById('rebuild-status').innerHTML = '';
                    await loadStats();
                    await loadEvents();
                }
            }, 2000);
        }

        async function validateRareObjects() {
            if (rebuilding) return;
            
            const confirmed = confirm(
                'This will re-scan videos with rare objects (bear, bed, horse, etc.) using YOLOv8x for accuracy validation.\\n\\n' +
                'This process is slow but ensures quality detections.\\n\\nContinue?'
            );
            
            if (!confirmed) return;
            
            rebuilding = true;
            document.getElementById('rebuild-status').innerHTML = 
                '<span class="status">Validating rare objects...</span>';
            
            await fetch('/api/validate', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: 'yolov8x.pt',
                    objects: ['bear', 'bed', 'horse', 'backpack', 'skateboard', 'train', 'elephant', 'giraffe', 'zebra', 'umbrella']
                })
            });
            
            // Poll for completion
            const interval = setInterval(async () => {
                const res = await fetch('/api/rebuild/status');
                const status = await res.json();
                
                if (!status.running) {
                    clearInterval(interval);
                    rebuilding = false;
                    document.getElementById('rebuild-status').innerHTML = '';
                    await loadStats();
                    await loadEvents();
                }
            }, 2000);
        }

        async function clearRecent() {
            if (rebuilding) return;
            
            const hours = prompt('Clear results from the last N hours (1-168):', '24');
            if (!hours) return;
            
            const hoursNum = parseInt(hours);
            if (isNaN(hoursNum) || hoursNum <= 0 || hoursNum > 168) {
                alert('Please enter a valid number between 1 and 168');
                return;
            }
            
            const confirmed = confirm(
                `This will clear all processing results for videos from the last ${hoursNum} hours.\\n\\n` +
                'These videos will be re-scanned during the next auto-scan with the current detection settings.\\n\\nContinue?'
            );
            
            if (!confirmed) return;
            
            try {
                const res = await fetch('/api/clear-recent', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hours: hoursNum })
                });
                
                const data = await res.json();
                
                if (data.success) {
                    alert(`Cleared ${data.videos_cleared} videos and ${data.segments_deleted} segments.\\nThey will be re-scanned on next auto-scan.`);
                    await loadStats();
                    await loadEvents();
                } else {
                    alert('Error: ' + (data.error || 'Unknown error'));
                }
            } catch (e) {
                console.error('Failed to clear recent results:', e);
                alert('Failed to clear results: ' + e.message);
            }
        }

        async function refreshEvents() {
            await loadStats();
            await loadEvents();
            await checkProcessingStatus();
        }

        // Auto-refresh every 30 seconds
        setInterval(refreshEvents, 30000);
        
        // Check processing status more frequently (every 5 seconds)
        setInterval(checkProcessingStatus, 5000);

        // Initial load
        console.log('Starting initial load...');
        loadStats();
        loadEvents();
        checkProcessingStatus();
        console.log('Initial load triggered');
    </script>
</body>
</html>
"""


@app.route('/api/statistics')
def api_statistics():
    """Get processing statistics."""
    stats = db.get_statistics()
    response = jsonify(stats)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/events')
def api_events():
    """Get all motion events."""
    events = db.get_all_motion_events()
    response = jsonify(events)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/video')
def api_video():
    """Serve the original video file for download or playback."""
    video_path = request.args.get('path')
    download = request.args.get('download', 'false').lower() == 'true'
    
    if not video_path:
        return "Missing path", 400
    
    # Security: ensure path is within surveillance root
    full_path = Path(video_path)
    if not full_path.exists():
        return "Video not found", 404
    
    try:
        # Resolve to check it's within surveillance root
        resolved = full_path.resolve()
        surveillance_resolved = SURVEILLANCE_ROOT.resolve()
        if not str(resolved).startswith(str(surveillance_resolved)):
            return "Access denied", 403
    except Exception:
        return "Invalid path", 400
    
    return send_file(str(full_path), mimetype='video/mp4', as_attachment=download)


@app.route('/api/preview')
def api_preview():
    """Serve a preview image for a motion segment."""
    video_path = request.args.get('path')
    segment_index = int(request.args.get('segment', 0))
    
    if not video_path:
        return "Missing path", 400
    
    # Previews are stored in /data/previews/
    preview_dir = DATA_DIR / "previews"
    video_path_obj = Path(video_path)
    pattern = f"{video_path_obj.stem}_seg{segment_index:03d}_*.jpg"
    
    # Find first matching preview
    for preview in preview_dir.glob(pattern):
        return send_file(str(preview), mimetype='image/jpeg')
    
    return "Preview not found", 404


@app.route('/api/rebuild', methods=['POST'])
def api_rebuild():
    """Trigger a rebuild of the motion detection index."""
    global rebuild_status
    
    if rebuild_status['running']:
        return jsonify({'error': 'Rebuild already in progress'}), 400
    
    rebuild_status = {'running': True, 'message': 'Starting rebuild...', 'progress': 0}
    
    def run_rebuild():
        def update_progress(progress):
            rebuild_status['total'] = progress['total']
            rebuild_status['processed'] = progress['processed']
            rebuild_status['current_file'] = progress['current_file']
            rebuild_status['message'] = f"Processing {progress['processed']}/{progress['total']}: {progress['current_file']}"
        
        try:
            logger.info("Manual rebuild triggered")
            processor = MotionProcessor(SURVEILLANCE_ROOT, DB_PATH, DETECTION_CONFIG, progress_callback=update_progress)
            processor.run_scan()
            rebuild_status['running'] = False
            rebuild_status['message'] = 'Rebuild complete'
            rebuild_status['total'] = 0
            rebuild_status['processed'] = 0
            rebuild_status['current_file'] = ''
            logger.info("Manual rebuild completed")
        except Exception as e:
            logger.error(f"Rebuild failed: {e}")
            rebuild_status['running'] = False
            rebuild_status['message'] = f'Error: {e}'
    
    thread = threading.Thread(target=run_rebuild, daemon=True)
    thread.start()
    
    return jsonify({'status': 'started'})


@app.route('/api/rebuild/status')
def api_rebuild_status():
    """Get rebuild status."""
    return jsonify(rebuild_status)


@app.route('/api/validate', methods=['POST'])
def api_validate():
    """Trigger validation scan on videos with rare objects."""
    global rebuild_status
    
    if rebuild_status['running']:
        return jsonify({'error': 'Scan already in progress'}), 400
    
    # Get parameters from request
    data = request.json or {}
    validation_model = data.get('model', 'yolov8x.pt')
    rare_objects = data.get('objects', [
        'bear', 'bed', 'horse', 'backpack', 'skateboard',
        'train', 'elephant', 'giraffe', 'zebra', 'umbrella'
    ])
    
    rebuild_status = {'running': True, 'message': 'Starting validation scan...', 'progress': 0}
    
    def run_validation():
        def update_progress(progress):
            rebuild_status['total'] = progress['total']
            rebuild_status['processed'] = progress['processed']
            rebuild_status['current_file'] = progress['current_file']
            rebuild_status['message'] = f"Validating {progress['processed']}/{progress['total']}: {progress['current_file']}"
        
        try:
            logger.info(f"Validation scan triggered (model: {validation_model}, objects: {rare_objects})")
            processor = MotionProcessor(SURVEILLANCE_ROOT, DB_PATH, DETECTION_CONFIG, progress_callback=update_progress)
            processor.run_validation_scan(validation_model=validation_model, rare_objects=rare_objects)
            rebuild_status['running'] = False
            rebuild_status['message'] = 'Validation complete'
            rebuild_status['total'] = 0
            rebuild_status['processed'] = 0
            rebuild_status['current_file'] = ''
            logger.info("Validation scan completed")
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            rebuild_status['running'] = False
            rebuild_status['message'] = f'Validation failed: {str(e)}'
    
    thread = threading.Thread(target=run_validation)
    thread.daemon = True
    thread.start()
    
    return jsonify({'message': 'Validation scan started', 'model': validation_model})


@app.route('/api/clear-recent', methods=['POST'])
def api_clear_recent():
    """Clear processing results for videos from the last N hours."""
    try:
        data = request.json or {}
        hours = data.get('hours', 24)
        
        # Validate hours parameter
        if not isinstance(hours, (int, float)) or hours <= 0 or hours > 168:  # Max 1 week
            return jsonify({'error': 'Hours must be between 0 and 168'}), 400
        
        db = DatabaseManager(DB_PATH)
        result = db.clear_recent_results(hours=int(hours))
        
        logger.info(f"Cleared results for last {hours} hours: {result['videos_cleared']} videos, {result['segments_deleted']} segments")
        
        return jsonify({
            'success': True,
            'message': f"Cleared {result['videos_cleared']} videos from last {hours} hours",
            'videos_cleared': result['videos_cleared'],
            'segments_deleted': result['segments_deleted'],
            'cutoff_time': result['cutoff_time']
        })
    except Exception as e:
        logger.error(f"Failed to clear recent results: {e}")
        return jsonify({'error': str(e)}), 500


def auto_scan_loop():
    """Background thread that runs periodic scans."""
    logger.info(f"Auto-scan thread started (scans every {AUTOSCAN_INTERVAL} seconds)")
    
    while True:
        time.sleep(AUTOSCAN_INTERVAL)
        
        if rebuild_status['running']:
            logger.info("Auto-scan skipped (manual rebuild in progress)")
            continue
        
        def update_progress(progress):
            rebuild_status['total'] = progress['total']
            rebuild_status['processed'] = progress['processed']
            rebuild_status['current_file'] = progress['current_file']
            rebuild_status['message'] = f"Processing {progress['processed']}/{progress['total']}: {progress['current_file']}"
        
        try:
            logger.info("Auto-scan triggered")
            rebuild_status['running'] = True
            rebuild_status['message'] = 'Auto-scan in progress...'
            
            processor = MotionProcessor(SURVEILLANCE_ROOT, DB_PATH, DETECTION_CONFIG, progress_callback=update_progress)
            processor.run_scan()
            
            rebuild_status['running'] = False
            rebuild_status['message'] = ''
            rebuild_status['total'] = 0
            rebuild_status['processed'] = 0
            rebuild_status['current_file'] = ''
            logger.info("Auto-scan completed")
        except Exception as e:
            logger.error(f"Auto-scan failed: {e}")
            rebuild_status['running'] = False
            rebuild_status['message'] = f'Error: {e}'


if __name__ == '__main__':
    logger.info("="*70)
    logger.info("Motion Detection Viewer 2.0 Starting")
    logger.info(f"Surveillance root: {SURVEILLANCE_ROOT}")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Database: {DB_PATH}")
    logger.info(f"Workers: {WORKERS}")
    logger.info(f"Auto-scan interval: {AUTOSCAN_INTERVAL}s")
    logger.info("="*70)
    
    # Start auto-scan thread
    scan_thread = threading.Thread(target=auto_scan_loop, daemon=True)
    scan_thread.start()
    
    # Start Flask
    app.run(host='0.0.0.0', port=5050, threaded=True)

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
        .events-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }
        .event-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            overflow: hidden;
            transition: transform 0.2s;
        }
        .event-card:hover {
            transform: translateY(-4px);
            border-color: #58a6ff;
        }
        .event-preview {
            width: 100%;
            height: 200px;
            object-fit: cover;
            background: #0d1117;
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
        .status {
            padding: 15px;
            border-radius: 6px;
            margin: 20px 0;
            background: #1f6feb;
            color: white;
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
    <div class="header">
        <h1>🎥 Motion Detection Viewer 2.0</h1>
        <p>SQLite-powered surveillance event browser</p>
    </div>

    <div class="stats" id="stats"></div>

    <div class="controls">
        <button class="btn" onclick="rebuild()">🔄 Rebuild Index</button>
        <button class="btn" onclick="refreshEvents()">↻ Refresh</button>
        <span id="rebuild-status"></span>
    </div>

    <div class="filters">
        <input type="text" class="filter-input" placeholder="Search video name..." 
               id="searchInput" oninput="filterEvents()">
        <input type="text" class="filter-input" placeholder="Filter by object..." 
               id="objectFilter" oninput="filterEvents()">
    </div>

    <div class="events-grid" id="events"></div>

    <script>
        let allEvents = [];
        let rebuilding = false;

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
            const res = await fetch('/api/events');
            allEvents = await res.json();
            filterEvents();
        }

        function filterEvents() {
            const search = document.getElementById('searchInput').value.toLowerCase();
            const objectFilter = document.getElementById('objectFilter').value.toLowerCase();

            const filtered = allEvents.filter(e => {
                const matchesSearch = !search || (e.video_path || '').toLowerCase().includes(search);
                const matchesObject = !objectFilter || (e.detected_objects || '').toLowerCase().includes(objectFilter);
                return matchesSearch && matchesObject;
            });

            renderEvents(filtered);
        }

        function renderEvents(events) {
            const container = document.getElementById('events');
            if (events.length === 0) {
                container.innerHTML = '<p style="grid-column: 1/-1; text-align:center; color:#8b949e;">No motion events found</p>';
                return;
            }

            container.innerHTML = events.map(e => {
                const objects = e.detected_objects ? e.detected_objects.split(',').map(o => o.trim()).filter(o => o) : [];
                const videoName = e.video_path.split('/').pop();
                
                return `
                    <div class="event-card">
                        <img class="event-preview" 
                             src="/api/preview?path=${encodeURIComponent(e.video_path)}&segment=${e.segment_index}"
                             alt="Preview" loading="lazy"
                             onerror="this.style.display='none';">
                        <div class="event-info">
                            <div class="event-time">${e.start_time} - ${e.end_time}</div>
                            <div class="event-meta">📁 ${videoName}</div>
                            <div class="event-meta">⏱️ ${e.duration_sec.toFixed(1)}s</div>
                            <div class="event-meta">📐 Area: ${e.max_motion_area}</div>
                            ${objects.length > 0 ? `
                                <div class="tags">
                                    ${objects.map(obj => `<span class="tag">🏷️ ${obj}</span>`).join('')}
                                </div>
                            ` : ''}
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

        async function refreshEvents() {
            await loadStats();
            await loadEvents();
        }

        // Auto-refresh every 30 seconds
        setInterval(refreshEvents, 30000);

        // Initial load
        loadStats();
        loadEvents();
    </script>
</body>
</html>
"""


@app.route('/api/statistics')
def api_statistics():
    """Get processing statistics."""
    stats = db.get_statistics()
    return jsonify(stats)


@app.route('/api/events')
def api_events():
    """Get all motion events."""
    events = db.get_all_motion_events()
    return jsonify(events)


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
        try:
            logger.info("Manual rebuild triggered")
            processor = MotionProcessor(SURVEILLANCE_ROOT, DB_PATH, DETECTION_CONFIG)
            processor.run_scan()
            rebuild_status['running'] = False
            rebuild_status['message'] = 'Rebuild complete'
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


def auto_scan_loop():
    """Background thread that runs periodic scans."""
    logger.info(f"Auto-scan thread started (scans every {AUTOSCAN_INTERVAL} seconds)")
    
    while True:
        time.sleep(AUTOSCAN_INTERVAL)
        
        if rebuild_status['running']:
            logger.info("Auto-scan skipped (manual rebuild in progress)")
            continue
        
        try:
            logger.info("Auto-scan triggered")
            rebuild_status['running'] = True
            rebuild_status['message'] = 'Auto-scan in progress...'
            
            processor = MotionProcessor(SURVEILLANCE_ROOT, DB_PATH, DETECTION_CONFIG)
            processor.run_scan()
            
            rebuild_status['running'] = False
            rebuild_status['message'] = ''
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

# SynologyIndexer 2.0 🎥

**Next-generation motion detection system with SQLite backend, real-time processing, intelligent object detection, and low-light enhancement**

Clean rewrite of SynologyIndexer with proper architecture, ACID transactions, crash-safe operations, YOLOv8-powered object recognition, and adaptive CLAHE enhancement for nighttime footage.

## Architecture

**Clean class structure:**
- `DatabaseManager` - SQLite with WAL mode, ACID transactions, and local Docker volume storage
- `VideoScanner` - File discovery and content-based hashing
- `MotionDetector` - OpenCV MOG2 background subtraction + YOLOv8m object recognition
- `MotionProcessor` - Parallel processing orchestration with real-time progress tracking
- `viewer.py` - Flask web UI with live status updates

**Key improvements over 1.0:**
- ✅ SQLite with WAL mode (crash-safe, indexed, queryable, concurrent reads)
- ✅ YOLOv8m object detection (50.2 mAP - person, car, dog, cat, etc.)
- ✅ **CLAHE low-light enhancement** (adaptive histogram equalization for dark videos)
- ✅ **Adaptive confidence thresholds** (0.15 for low-light vs 0.25 for normal lighting)
- ✅ **Brightness tracking & metadata** (per-video brightness levels and preprocessing info)
- ✅ Real-time progress tracking (live status banner in UI)
- ✅ Optimized parallel processing (YOLO loaded once per worker)
- ✅ Tile-based UI with scan details (brightness, enhancement, processing time)
- ✅ Docker volumes for persistence (database survives container restarts)
- ✅ imap_unordered for streaming updates (no batch delays)
- ✅ Atomic transactions (no data loss on crash)
- ✅ Clean separation of concerns

## Features

### Motion Detection
- **OpenCV MOG2** background subtraction with adaptive thresholds
- **Brightness detection** - Samples 5 frames to calculate mean grayscale value
- **CLAHE enhancement** - Applied to dark videos (brightness < 60) using LAB color space
- **Adaptive confidence** - 0.15 threshold for low-light vs 0.25 for normal lighting
- Contour analysis for motion area calculation
- Segment merging (combines nearby motion events)

### Low-Light Enhancement
- **Automatic brightness detection**: Samples 5 frames from video, calculates mean brightness (0-255)
- **CLAHE preprocessing**: Applied when brightness < 60
  - Converts frame to LAB color space
  - Applies Contrast Limited Adaptive Histogram Equalization to L channel
  - Preserves color information while enhancing contrast
- **Adaptive confidence thresholds**:
  - Dark videos (< 60 brightness): 0.15 confidence threshold
  - Normal videos (≥ 60 brightness): 0.25 confidence threshold
- **Metadata tracking**: Brightness level and preprocessing method stored per video

### Object Recognition
- **YOLOv8m** (medium model) - 25MB, 50.2 mAP on COCO dataset
- Detects: person, car, dog, cat, bird, truck, bicycle, motorcycle, and 72 other classes
- Optimized loading: YOLO loaded once per worker (not per video)
- Per-segment object detection with adaptive confidence scores
- Context-aware detection (lower thresholds for challenging lighting)

### Real-Time Progress Tracking
- Live status banner in UI (updates every 5 seconds)
- Displays: total videos, processed count, percentage, current filename
- Streaming updates using imap_unordered (per-video, not batch)
- Green pulsing indicator when processing active

### Web UI
- **Tile-based layout**: Groups motion segments by video file
- **Scan details badges**: 
  - 🌙/☀️ Brightness level (dark vs normal lighting)
  - ✨ Enhancement indicator (CLAHE applied)
  - ⚙️ Processing time per video
- **Preview thumbnails**: Multiple preview images per event in grid layout
- **Multi-select object filtering**: Click multiple object types to filter
- **Auto-refresh**: Statistics update every 30 seconds
- **Filtering/Sorting**: By date, duration, segment count, camera name
- **Clear recent results**: Delete and re-scan last N hours (for testing)
- **Responsive design**: Works on desktop and mobile

### Preview Images
- Up to 5 representative frames per motion segment
- Correctly named (seg001, seg002, etc.) to match database indices
- Stored in local Docker volume (fast access)
- Served via `/api/preview` endpoint



### Prerequisites
- Raspberry Pi 5 with Ubuntu 24.04+ (or any ARM64/x86_64 Linux)
- Docker & Docker Compose
- NAS shares mounted via CIFS

### Deployment

**Remote deployment (to Raspberry Pi):**
```bash
# Deploy to theinfracore (RPi5)
ssh theinfracore 'cd ~/SynologyIndexer2.0 && git pull && bash deployments/deploy.sh 212'

# Deploy second NAS
ssh theinfracore 'cd ~/SynologyIndexer2.0 && git pull && bash deployments/deploy.sh 213'

# Check status
ssh theinfracore 'cd ~/SynologyIndexer2.0 && bash deployments/status.sh'
```

**Local deployment:**
```bash
# Clone repository
git clone https://github.com/schultzzznet/SynologyIndexer2.0.git
cd SynologyIndexer2.0

# Deploy NAS 212 (port 5050)
bash deployments/deploy.sh 212

# Deploy NAS 213 (port 5051)
bash deployments/deploy.sh 213

# Check status
bash deployments/status.sh
```

The deploy.sh script:
- Pulls latest code from GitHub
- Stops existing containers
- Rebuilds Docker images
- Starts containers with docker-compose

## Configuration

### Camera Configurations

**NAS 212** (schultzzznet212.local - 192.168.1.212)
- 2x Foscam Fi9900P cameras
- Mount: `/mnt/nas-212/surveillance`
- Credentials: `jkv16/Mimsedyr42`

**NAS 213** (schultzzznet213 - Tailscale 100.115.226.53)
- 1x Reolink RLC-422-5MP
- 1x Trendnet TV-IP572PI
- Mount: `/mnt/nas-213/surveillance`
- Credentials: `f25/Mimsedyr42`

### Environment Variables

Edit `deployments/*/docker-compose.yml`:

```yaml
environment:
  - SURVEILLANCE_ROOT=/data
  - WORKERS=2                    # Parallel workers
  - AUTOSCAN_INTERVAL=60         # Auto-scan every N seconds
```

### Resource Limits

Current settings (per deployment):
- Memory: 4GB max, 2GB reserved
- Workers: 2
- Total system load: 8GB, 4 workers

Adjust in docker-compose.yml based on your hardware.

## Database Schema

**videos table:**
- `video_hash` - Unique identifier
- `video_path` - Full path to video file
- `processed_at` - Timestamp of processing
- `has_motion` - Boolean flag
- `brightness_level` - Mean brightness (0-255 scale)
- `preprocessing_applied` - Enhancement method (e.g., "CLAHE")
- `processing_duration_sec` - Time taken to process video
- `error_message` - If processing failed

**motion_segments table:**
- `video_hash` - Foreign key to videos
- `segment_index` - Segment number within video
- `start_time`, `end_time`, `duration_sec`
- `max_motion_area` - Largest contour detected
- `detected_objects` - YOLO detections
- `preview_count` - Number of saved images

**Indexes:**
- Fast lookups by path, hash, processing state
- Efficient queries for UI filtering/sorting

## API Endpoints

- `GET /` - Web UI with real-time status tracking
- `GET /api/statistics` - Processing stats (total/processed/pending videos)
- `GET /api/events` - All motion events (grouped by video)
- `GET /api/preview?path=...&segment=N` - Preview image for segment
- `POST /api/rebuild` - Trigger manual scan
- `GET /api/rebuild/status` - Live rebuild status (progress tracking)
- `POST /api/validate` - Re-scan videos with rare objects using YOLOv8x
- `POST /api/clear-recent` - Clear results for last N hours (for re-testing)

## Technology Stack

**Core Technologies:**
- **Python 3.11** - Base runtime
- **OpenCV 4.12.0.88** - Video processing and motion detection
- **Ultralytics YOLOv8m (8.3.250)** - Object recognition (50.2 mAP)
- **Flask 3.1.2** - Web server and API
- **SQLite3** - Database with WAL mode
- **Docker & Docker Compose** - Containerization and orchestration

**Key Libraries:**
- `cv2.createBackgroundSubtractorMOG2()` - Motion detection
- `ultralytics.YOLO` - Object detection
- `multiprocessing.Pool` - Parallel processing with imap_unordered
- `sqlite3` with WAL mode - Concurrent database access

**Infrastructure:**
- Docker volumes for persistence (database + preview images)
- Read-only NAS mounts (surveillance footage)
- Port mapping: 5050 (212), 5051 (213)

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
cd src
python viewer.py

# Access UI
open http://localhost:5050
```

## Migration from 1.0

**No automatic migration provided** - 2.0 is a fresh start.

If you need historical data:
1. Keep 1.0 running alongside 2.0
2. Or write custom CSV → SQLite import script

## Performance

**Raspberry Pi 5 (16GB RAM, 4 cores @ 2GHz):**
- ~60 videos/hour per worker (with YOLOv8m)
- ~60s per video (depends on length, motion, and YOLO detections)
- Minimal CPU throttling at 51°C
- 2 workers per deployment (4 total across both NAS)

**Processing Optimization:**
- YOLO loaded once per worker (not per video) - saves ~11,260 loads for 5,630 videos
- Streaming results with imap_unordered (real-time progress updates)
- Background subtraction with adaptive thresholds (dark video handling)

**Resource usage (2 deployments):**
- Memory: ~6GB total (3GB per container)
- Load: ~2.7 with 4 total workers
- Storage: 
  - Database: ~10MB per 1000 videos
  - Previews: ~1-2MB per 100 segments (5 images @ 50KB each)
  - YOLOv8m model: 25MB per worker

**Estimated Processing Time:**
- 5,667 videos × 60s ÷ 2 workers ÷ 3600s = ~47 hours for full rebuild

## Troubleshooting

**Container won't start:**
```bash
ssh theinfracore
cd ~/SynologyIndexer2.0/deployments/212
docker compose logs
```

**Database locked:**
SQLite handles this automatically with WAL mode and local storage. Data is stored in Docker volume, not NAS.

**No motion detected:**
Check logs for brightness values. Dark videos use adaptive thresholds (as low as 20 for very dark footage).

**High memory usage:**
Reduce WORKERS in docker-compose.yml or lower memory limits. Each worker loads YOLOv8m (25MB model).

**Preview images showing 404:**
Previews are named `{video}_seg{NNN}_f{frame}.jpg` where NNN is the segment index. Fresh rebuild will regenerate all previews with correct naming.

**Processing seems stuck:**
Check the live status banner - it updates every 5 seconds. Processing 1 video takes ~60s with YOLOv8m. Use the real-time progress indicator.

**UI shows statistics but no events:**
Check that preview images are accessible and processing has completed:
```bash
ssh theinfracore 'sudo ls /var/lib/docker/volumes/212_motion-db-212/_data/previews/ | head'
```

**Want to start fresh:**
```bash
# Stop container
ssh theinfracore 'cd ~/SynologyIndexer2.0/deployments/212 && docker compose down'

# Delete database and previews
ssh theinfracore 'docker volume rm 212_motion-db-212'

# Restart fresh
ssh theinfracore 'cd ~/SynologyIndexer2.0 && bash deployments/deploy.sh 212'
```

## Monitoring

```bash
# Tail logs with real-time updates
ssh theinfracore 'docker logs -f motion-detection-viewer-212'

# Database stats
ssh theinfracore 'docker exec motion-detection-viewer-212 python3 -c "
import sqlite3
conn = sqlite3.connect(\"/data/motion_events.db\")
cursor = conn.execute(\"SELECT COUNT(*) FROM videos WHERE processed_at IS NOT NULL\")
print(\"Processed videos:\", cursor.fetchone()[0])
cursor = conn.execute(\"SELECT COUNT(*) FROM motion_segments\")
print(\"Motion segments:\", cursor.fetchone()[0])
cursor = conn.execute(\"SELECT COUNT(*) FROM motion_segments WHERE detected_objects != '\''[]'\''\")
print(\"Segments with objects detected:\", cursor.fetchone()[0])
"'

# Check Docker volume
ssh theinfracore 'sudo ls -lh /var/lib/docker/volumes/212_motion-db-212/_data/'

# Preview image count
ssh theinfracore 'sudo find /var/lib/docker/volumes/212_motion-db-212/_data/previews/ -name "*.jpg" | wc -l'

# API health check
ssh theinfracore 'curl -s http://localhost:5050/api/statistics | python3 -m json.tool'

# Live rebuild status
ssh theinfracore 'curl -s http://localhost:5050/api/rebuild/status | python3 -m json.tool'
```

## Recent Updates (Jan 2026)

**v2.2 - Low-Light Enhancement & Scan Metadata (Jan 11, 2026)**
- ✅ **CLAHE preprocessing** for dark videos (brightness < 60)
  - LAB color space enhancement preserves color while improving contrast
  - Applied in-memory before YOLO detection (no video file modification)
- ✅ **Adaptive confidence thresholds** (0.15 for dark vs 0.25 for normal)
- ✅ **Brightness tracking** - Samples 5 frames, stores mean brightness per video
- ✅ **Scan details UI** - Shows brightness level, enhancement status, processing time
- ✅ **Clear recent results** - Delete and re-scan last N hours via UI button
- ✅ **AB testing deployment** - NAS 212 with enhancements, 213 as baseline

**v2.1 - Real-Time Processing & YOLOv8m**
- ✅ Upgraded to YOLOv8m (50.2 mAP, up from 37.3 with nano)
- ✅ Real-time progress tracking in UI (5-second polling)
- ✅ Optimized YOLO loading (once per worker vs per video)
- ✅ Fixed preview image naming to match database indices
- ✅ Streaming results with imap_unordered (no batch delays)
- ✅ Tile-based UI grouping segments by video
- ✅ Green pulsing status banner with detailed progress

## How It Works

### Detection Pipeline

1. **Video Discovery**
   - Scans NAS mounts for video files
   - Calculates content-based hashes (MD5)
   - Skips already-processed videos

2. **Brightness Analysis**
   - Samples 5 frames evenly distributed through video
   - Converts to grayscale and calculates mean pixel value (0-255)
   - Determines if video is "dark" (< 60) or "normal" (≥ 60)

3. **Motion Detection**
   - OpenCV MOG2 background subtraction
   - Samples every Nth frame (configurable, default 2)
   - Identifies contours above minimum area threshold
   - Groups nearby motion into segments

4. **Low-Light Enhancement** (if brightness < 60)
   - Converts frame from BGR to LAB color space
   - Applies CLAHE to L (lightness) channel only
   - Converts back to BGR for YOLO input
   - Preserves color information while improving contrast

5. **Object Detection**
   - YOLOv8m inference on motion frames
   - Adaptive confidence: 0.15 for dark videos, 0.25 for normal
   - Detects 80 COCO classes (person, car, dog, etc.)
   - Stores detected objects per segment

6. **Preview Generation**
   - Saves up to 5 representative frames per segment
   - Stored as JPEG in Docker volume
   - Named: `{video}_seg{NNN}_f{frame}.jpg`

7. **Database Storage**
   - Atomic transaction with video metadata + segments
   - Stores brightness level and preprocessing method
   - Tracks processing duration for performance monitoring

### Why CLAHE on LAB Color Space?

- **CLAHE** (Contrast Limited Adaptive Histogram Equalization) prevents over-amplification
- **LAB color space** separates luminance (L) from color (A, B):
  - Enhancing only L channel improves visibility without color distortion
  - Preserves natural color appearance of objects
  - Better for YOLO detection than RGB-based enhancement

### Understanding YOLO

YOLO (You Only Look Once) is a single-pass neural network for object detection:
- **Not "AI that understands"** - it's pattern recognition trained on millions of labeled images
- **Grid-based prediction** - Divides image into grid, predicts bounding boxes + class probabilities
- **COCO dataset** - Pre-trained on 80 common object classes
- **Confidence scores** - Higher = more certain, but context-dependent (night footage needs lower thresholds)

Read more: [How YOLO Actually Works](https://chatgpt.com/share/69635dbf-1ef8-8007-81ec-064ea452993e)

## Future Enhancements

See [GitHub Issues](https://github.com/schultzzznet/SynologyIndexer2.0/issues) for detailed proposals:

### 🎯 High Priority

**[#3 - Object Tracking](https://github.com/schultzzznet/SynologyIndexer2.0/issues/3)**
- Track objects across multiple segments (ByteTrack/BoT-SORT)
- "Person was present for 5 minutes" analytics
- Reduce duplicate detection alerts
- Path/trajectory visualization

**[#4 - Zone-Based Detection](https://github.com/schultzzznet/SynologyIndexer2.0/issues/4)**
- Define areas of interest (driveway, door, property boundary)
- Ignore specific zones (street traffic, swaying trees)
- Per-zone confidence thresholds and object filters
- Drastically reduce false positives

### 🔬 Research / Long-Term

**[#2 - Night-Vision Specific Model](https://github.com/schultzzznet/SynologyIndexer2.0/issues/2)**
- Fine-tune YOLO on IR/thermal footage datasets
- Handle IR illuminator patterns and artifacts
- Better than CLAHE + base model for complete darkness
- Switch models based on brightness: `if brightness < 60: use night_model`

**[#1 - Custom Training](https://github.com/schultzzznet/SynologyIndexer2.0/issues/1)**
- Train on your specific camera footage
- Custom classes: "delivery_package", "my_dog", "open_door"
- Optimized for your camera angles and lighting
- Use existing motion segments as training data

### 💡 Other Ideas

- **Smart notifications**: Push alerts for specific objects in specific zones
- **Time-based patterns**: "Unusual activity" detection (movement at 3 AM)
- **Integration**: Home Assistant, Frigate NVR compatibility
- **Multi-model inference**: Fast model for initial scan, accurate model for validation
- **Hardware acceleration**: Coral TPU or GPU support for faster inference

## AB Testing Methodology

Current deployment strategy for testing enhancements:

- **NAS 212** - Production with enhancements (CLAHE, adaptive confidence, metadata)
- **NAS 213** - Baseline without enhancements (control group)

This allows direct comparison of detection quality, false positive rates, and processing performance before deploying to all systems.

## Recent Updates (Jan 2026)

**v2.1 - Real-Time Processing & YOLOv8m**
- ✅ Upgraded to YOLOv8m (50.2 mAP, up from 37.3 with nano)
- ✅ Real-time progress tracking in UI (5-second polling)
- ✅ Optimized YOLO loading (once per worker vs per video)
- ✅ Fixed preview image naming to match database indices
- ✅ Streaming results with imap_unordered (no batch delays)
- ✅ Tile-based UI grouping segments by video
- ✅ Green pulsing status banner with detailed progress

## License

MIT

## Credits

Built by @schultzzznet
Powered by OpenCV, YOLO (Ultralytics), Flask, SQLite

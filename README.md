# SynologyIndexer 2.0 🎥

**Next-generation motion detection system with SQLite backend**

Clean rewrite of SynologyIndexer with proper architecture, ACID transactions, and crash-safe operations.

## Architecture

**Clean class structure:**
- `DatabaseManager` - SQLite with ACID transactions
- `VideoScanner` - File discovery and hashing
- `MotionDetector` - OpenCV + YOLO analysis
- `MotionProcessor` - Orchestrates the pipeline
- `viewer.py` - Flask web UI

**Key improvements over 1.0:**
- ✅ SQLite replaces CSV (crash-safe, indexed, queryable)
- ✅ No checkpoint files needed (database handles state)
- ✅ Atomic transactions (no data loss on crash)
- ✅ Clean separation of concerns
- ✅ Same proven UI and deployment model

## Quick Start

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

- `GET /` - Web UI
- `GET /api/statistics` - Processing stats
- `GET /api/events` - All motion events
- `GET /api/preview?path=...&segment=N` - Preview image
- `POST /api/rebuild` - Trigger manual scan
- `GET /api/rebuild/status` - Check rebuild status

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
- ~200 videos/hour per worker
- ~3-4s per video (depends on length/motion)
- Minimal CPU throttling at 51°C

**Resource usage (2 deployments):**
- Memory: ~6GB total (3GB per container)
- Load: ~2.7 with 4 total workers
- Storage: ~10MB per 1000 videos (database)

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
Check logs for brightness values. Dark videos use adaptive thresholds.

**High memory usage:**
Reduce WORKERS in docker-compose.yml or lower memory limits.

**UI shows statistics but no events:**
Check that preview images are accessible:
```bash
ssh theinfracore 'sudo ls /var/lib/docker/volumes/212_motion-db-212/_data/previews/ | head'
```

## Monitoring

```bash
# Tail logs
ssh theinfracore 'docker logs -f motion-detection-viewer-212'

# Database stats
ssh theinfracore 'docker exec motion-detection-viewer-212 python3 -c "
import sqlite3
conn = sqlite3.connect(\"/data/motion_events.db\")
cursor = conn.execute(\"SELECT COUNT(*) FROM videos WHERE processed_at IS NOT NULL\")
print(\"Processed videos:\", cursor.fetchone()[0])
cursor = conn.execute(\"SELECT COUNT(*) FROM motion_segments\")
print(\"Motion segments:\", cursor.fetchone()[0])
"'

# Check Docker volume
ssh theinfracore 'sudo ls -lh /var/lib/docker/volumes/212_motion-db-212/_data/'

# API health check
ssh theinfracore 'curl -s http://localhost:5050/api/statistics | python3 -m json.tool'
```

## License

MIT

## Credits

Built by @schultzzznet
Powered by OpenCV, YOLO (Ultralytics), Flask, SQLite

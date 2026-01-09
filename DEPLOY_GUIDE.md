# SynologyIndexer 2.0 - RPi5 Deployment Guide

## Quick Deploy (Copy-paste on RPi5)

### 1. Clone and Setup
```bash
# SSH into RPi5
ssh cschultz@192.168.88.212  # or 213

# Clone the repo
cd ~/projects
rm -rf SynologyIndexer2.0  # Clean slate
git clone https://github.com/schultzzznet/SynologyIndexer2.0.git
cd SynologyIndexer2.0

# Verify structure
ls -la
```

### 2. Deploy Both Instances
```bash
# Deploy 212
cd ~/projects/SynologyIndexer2.0/deployments
./deploy.sh 212

# Wait for it to start, then check
./status.sh 212

# Deploy 213
./deploy.sh 213
./status.sh 213
```

### 3. Verify URLs
- **212**: http://192.168.88.212:5001
- **213**: http://192.168.88.213:5002

### 4. Watch Logs (Real-time)
```bash
# On 212
docker logs -f synology-indexer-212

# On 213
docker logs -f synology-indexer-213
```

### 5. Quick Health Check
```bash
# Should see:
# - Scanner running every 60s
# - Motion detector processing videos
# - Database files in /data/
# - Preview images being generated

# Check database
./deployments/status.sh 212
docker exec synology-indexer-212 ls -lh /data/
```

## Expected First-Run Output

```
[2026-01-09 12:00:00] Starting SynologyIndexer 2.0
[2026-01-09 12:00:00] Initializing database at /data/motions.db
[2026-01-09 12:00:01] Database ready: 0 videos, 0 motions
[2026-01-09 12:00:01] Starting scanner (60s interval)...
[2026-01-09 12:00:01] Starting motion detector (2 workers)...
[2026-01-09 12:00:01] Flask UI starting on 0.0.0.0:5001
[2026-01-09 12:00:02] Scanning: /surveillance
[2026-01-09 12:00:05] Found 1234 videos (456 new)
[2026-01-09 12:00:05] Processing: video_001.mp4
```

## Troubleshooting

### No videos found
```bash
# Check mount
docker exec synology-indexer-212 ls /surveillance/

# Should see:
# 2024/  2025/  2026/
```

### Port conflict
```bash
# Check what's using the port
sudo lsof -i :5001

# Stop old version
docker stop synology-indexer-212-old
```

### Slow processing
```bash
# Check CPU/memory
docker stats synology-indexer-212

# Should see ~400% CPU (4 cores, 2 workers)
```

## Migration from 1.0 (Optional)

If you want to preserve motion data from 1.0:

```bash
# This will scan all videos and re-detect motions
# Takes ~2 hours for 5000 videos on RPi5
# Database will be built from scratch
```

Or manual migration (advanced):

```bash
# Export 1.0 CSV to 2.0 SQLite
# (Not recommended - fresh start is cleaner)
```

## Stop/Restart

```bash
# Stop
docker stop synology-indexer-212

# Restart (preserves database)
docker start synology-indexer-212

# Full reset
./deployments/deploy.sh 212  # Rebuilds everything
```

#!/usr/bin/env bash
set -e

DEPLOYMENT_NAME=$1

if [ -z "$DEPLOYMENT_NAME" ]; then
    echo "Usage: ./deploy.sh <deployment-name>"
    echo "Example: ./deploy.sh 212"
    exit 1
fi

# Get absolute path to repo root (where this script's parent is)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DEPLOYMENT_DIR="$REPO_ROOT/deployments/$DEPLOYMENT_NAME"

if [ ! -d "$DEPLOYMENT_DIR" ]; then
    echo "❌ Deployment directory not found: $DEPLOYMENT_DIR"
    exit 1
fi

echo "=========================================="
echo "🚀 Deploying: $DEPLOYMENT_NAME"
echo "=========================================="

# Pull latest code from repo root
cd "$REPO_ROOT"
echo "📥 Pulling latest changes from git..."
git pull
echo "📝 Current commit: $(git rev-parse --short HEAD)"

# Stop existing containers
echo "🛑 Stopping existing containers..."
cd "$DEPLOYMENT_DIR"
docker compose down

# Build and start
echo "🔨 Building Docker image..."
export DOCKER_BUILDKIT=0  # Use legacy builder (RPi5 workaround)
docker compose build

echo "🚀 Starting containers..."
docker compose up -d

# Wait for service
echo ""
echo "⏳ Waiting for service to be ready..."
sleep 5

# Show status
echo ""
echo "✅ Deployment successful!"
PORT=$(docker compose port motion-detector 5050 2>/dev/null | cut -d: -f2)
if [ -n "$PORT" ]; then
    echo "🌐 Access at: http://localhost:$PORT"
fi

echo ""
echo "📊 Container status:"
docker compose ps

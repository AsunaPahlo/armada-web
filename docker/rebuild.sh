#!/bin/bash
# Armada Docker Rebuild Script for Linux/Mac
# Run this script from the docker/ directory or the project root

set -e

echo ""
echo "========================================"
echo "  Armada Docker Image Rebuild"
echo "========================================"
echo ""

# Determine script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# If running from project root, adjust
if [ -f "docker/Dockerfile" ]; then
    PROJECT_ROOT="$(pwd)"
fi

cd "$PROJECT_ROOT"

# Rebuild the image (no cache to ensure fresh build)
echo "Rebuilding Docker image..."
docker build --no-cache -t armada:latest -f docker/Dockerfile .

echo ""
echo "========================================"
echo "  Rebuild complete!"
echo "========================================"
echo ""

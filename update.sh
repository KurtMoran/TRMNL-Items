#!/bin/bash
# TRMNL Items auto-update script
# Pulls latest code from GitHub, rebuilds and restarts all containers.
# API keys are passed via environment variables — set them below.
#
# Usage: Run as an Unraid User Script or manually via:
#   bash /mnt/user/appdata/TRMNL-Items/update.sh

GEMINI_API_KEY="${GEMINI_API_KEY:?Set GEMINI_API_KEY}"
AIRPORT_WEBHOOK_UUID="${AIRPORT_WEBHOOK_UUID:?Set AIRPORT_WEBHOOK_UUID}"
WIKI_WEBHOOK_UUID="${WIKI_WEBHOOK_UUID:?Set WIKI_WEBHOOK_UUID}"

cd /mnt/user/appdata/TRMNL-Items

# Pull latest from GitHub
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "New changes found, pulling..."
    git pull
else
    echo "Code already up to date."
fi

# Always rebuild and restart all containers to get fresh data

# --- Airport Tracker ---
echo "Rebuilding airport tracker..."
docker stop trmnl-items 2>/dev/null
docker rm trmnl-items 2>/dev/null
docker build --no-cache -t trmnl-items ./airport-tracker/
docker run -d --name trmnl-items --restart unless-stopped \
    -e TZ=America/Los_Angeles \
    -e TRMNL_WEBHOOK_UUID="$AIRPORT_WEBHOOK_UUID" \
    -e POLL_INTERVAL_SEC=120 \
    -e DATA_FILE=/data/tracker_state.json \
    -v /mnt/user/appdata/TRMNL-Items/airport-tracker/data:/data \
    trmnl-items

# --- Wiki Trending ---
echo "Rebuilding wiki trending..."
docker stop wiki-trending 2>/dev/null
docker rm wiki-trending 2>/dev/null
docker build --no-cache -t wiki-trending ./wiki-trending/
docker run -d --name wiki-trending --restart unless-stopped \
    -e TZ=America/Los_Angeles \
    -e TRMNL_WEBHOOK_UUID="$WIKI_WEBHOOK_UUID" \
    -e GEMINI_API_KEY="$GEMINI_API_KEY" \
    -v /mnt/user/appdata/TRMNL-Items/wiki-trending/data:/data \
    wiki-trending

# Clean up old images
docker image prune -f

echo "Update complete!"

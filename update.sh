#!/bin/bash
# TRMNL Items auto-update script
# Pulls latest code from GitHub and rebuilds only containers whose
# source files have changed. API keys are passed via environment
# variables — set them below.
#
# Usage: Run as an Unraid User Script or manually via:
#   bash /mnt/user/appdata/TRMNL-Items/update.sh
#
# Force a full rebuild of every container:
#   FORCE_REBUILD=1 bash /mnt/user/appdata/TRMNL-Items/update.sh

GEMINI_API_KEY="${GEMINI_API_KEY:?Set GEMINI_API_KEY}"
AIRPORT_WEBHOOK_UUID="${AIRPORT_WEBHOOK_UUID:?Set AIRPORT_WEBHOOK_UUID}"
WIKI_WEBHOOK_UUID="${WIKI_WEBHOOK_UUID:?Set WIKI_WEBHOOK_UUID}"
WEATHER_WEBHOOK_UUID="${WEATHER_WEBHOOK_UUID:?Set WEATHER_WEBHOOK_UUID}"

cd /mnt/user/appdata/TRMNL-Items

# Pull latest from GitHub
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

CHANGED_FILES=""
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "New changes found, pulling..."
    CHANGED_FILES=$(git diff --name-only "$LOCAL" "$REMOTE")
    git pull
else
    echo "Code already up to date."
fi

# Rebuild a container if FORCE_REBUILD=1, the container is missing,
# or any file under its subdirectory changed in this pull.
needs_rebuild() {
    local container_name="$1"
    local subdir="$2"

    if [ "$FORCE_REBUILD" = "1" ]; then
        return 0
    fi

    if ! docker ps -a --format '{{.Names}}' | grep -q "^${container_name}$"; then
        echo "Container ${container_name} does not exist — will build."
        return 0
    fi

    if echo "$CHANGED_FILES" | grep -q "^${subdir}/"; then
        echo "Changes detected in ${subdir}/ — will rebuild ${container_name}."
        return 0
    fi

    echo "No changes for ${container_name} — skipping."
    return 1
}

# --- Airport Tracker ---
if needs_rebuild "airport-tracker" "airport-tracker"; then
    echo "Rebuilding airport tracker..."
    docker stop trmnl-items 2>/dev/null
    docker rm trmnl-items 2>/dev/null
    docker stop airport-tracker 2>/dev/null
    docker rm airport-tracker 2>/dev/null
    docker build --no-cache -t airport-tracker ./airport-tracker/
    docker run -d --name airport-tracker --restart unless-stopped \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
        -e TZ=America/Los_Angeles \
        -e TRMNL_WEBHOOK_UUID="$AIRPORT_WEBHOOK_UUID" \
        -e POLL_INTERVAL_SEC=120 \
        -e DATA_FILE=/data/tracker_state.json \
        -v /mnt/user/appdata/TRMNL-Items/airport-tracker/data:/data \
        airport-tracker
fi

# --- Wiki Trending ---
if needs_rebuild "wiki-trending" "wiki-trending"; then
    echo "Rebuilding wiki trending..."
    docker stop wiki-trending 2>/dev/null
    docker rm wiki-trending 2>/dev/null
    docker build --no-cache -t wiki-trending ./wiki-trending/
    docker run -d --name wiki-trending --restart unless-stopped \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
        -e TZ=America/Los_Angeles \
        -e TRMNL_WEBHOOK_UUID="$WIKI_WEBHOOK_UUID" \
        -e GEMINI_API_KEY="$GEMINI_API_KEY" \
        -v /mnt/user/appdata/TRMNL-Items/wiki-trending/data:/data \
        wiki-trending
fi

# --- Weather Board ---
if needs_rebuild "weather-board" "weather-board"; then
    echo "Rebuilding weather board..."
    docker stop weather-board 2>/dev/null
    docker rm weather-board 2>/dev/null
    docker build --no-cache -t weather-board ./weather-board/
    docker run -d --name weather-board --restart unless-stopped \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
        -e TZ=America/Los_Angeles \
        -e TRMNL_WEBHOOK_UUID="$WEATHER_WEBHOOK_UUID" \
        -v /mnt/user/appdata/TRMNL-Items/weather-board/data:/data \
        weather-board
fi

# Clean up old images
docker image prune -f

echo "Update complete!"

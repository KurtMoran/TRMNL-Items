# TRMNL-Items

Custom plugins for the [TRMNL](https://usetrmnl.com/) e-ink display, powered by Docker and free APIs.

## Projects

### [Airport Tracker](airport-tracker/)
Tracks daily flight activity at a local airport using ADS-B data. Shows arrivals, departures, aircraft types, hourly activity chart, and weather. Currently configured for Montgomery-Gibbs Executive Airport (KMYF) in San Diego — easily adaptable to any airport by changing the coordinates in `tracker.py`.

---

## How It Works

### Overview

Each project is a Python script that runs in a Docker container. It polls free APIs on a schedule, processes the data, and pushes a JSON payload to a TRMNL e-ink display via webhook. No paid APIs or authentication required.

### Data Flow

```
  Free APIs (airplanes.live, Open-Meteo, etc.)
       |
       | poll every ~2 min
       v
  Docker container (any always-on server)
  - Fetches data from APIs
  - Processes & tracks state (JSON file on disk)
  - Builds payload (must stay under 2KB)
       |
       | push every ~10 min
       v
  TRMNL webhook API
  - Receives JSON via POST
  - Merges variables into the Liquid template
       |
       | display refreshes periodically
       v
  TRMNL e-ink display
  - Renders the template with the latest data
```

### Architecture

| Component | What it does |
|-----------|-------------|
| `tracker.py` | Main script — polls APIs, detects events, pushes to TRMNL |
| `trmnl_template.html` | Liquid/HTML template — pasted into the TRMNL markup editor |
| `preview.html` | Local browser preview with sample data for design iteration |
| `Dockerfile` | Builds a lightweight Python container (python:3.12-slim) |
| `data/` directory | Persistent state (JSON), mounted as a Docker volume |

---

## Setup Guide

### Prerequisites

- A [TRMNL](https://usetrmnl.com/) e-ink display
- An always-on server that can run Docker (Unraid, Raspberry Pi, NAS, VPS, etc.)
- Git installed on the server

### 1. TRMNL Plugin Setup

1. Log into the [TRMNL dashboard](https://trmnl.com/)
2. Create a new **Private Plugin**
3. Set the strategy to **Webhook**
4. Copy the **Webhook UUID** — you'll need this for the Docker container
5. Open the project's `trmnl_template.html` file, copy its contents, and paste into the **Markup Editor**
6. Under plugin settings:
   - Set **Remove bleed margin** = Yes
   - Uncheck **Show TRMNL logo** (optional)
7. Save

### 2. Server Setup

Clone the repo:

```bash
git clone https://github.com/KurtMoran/TRMNL-Items.git
cd TRMNL-Items
```

Build and run a project (example: airport-tracker):

```bash
cd airport-tracker
docker build --no-cache -t trmnl-items .
docker run -d --name trmnl-items --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=<your-uuid-from-step-4> \
  -e POLL_INTERVAL_SEC=120 \
  -e DATA_FILE=/data/tracker_state.json \
  -v $(pwd)/data:/data \
  trmnl-items
```

Replace `<your-uuid-from-step-4>` with the UUID from the TRMNL dashboard, and adjust the timezone (`TZ`) to your location.

Verify it's running:

```bash
docker logs trmnl-items
```

### 3. Customization

**Different airport?** Edit `tracker.py` and change these three lines:

```python
AIRPORT_LAT = 32.8157      # your airport's latitude
AIRPORT_LON = -117.1397    # your airport's longitude
AIRPORT_ELEV_FT = 427      # your airport's field elevation in feet
```

**Different timezone?** Change the `-e TZ=` value in the docker run command. Examples: `America/New_York`, `Europe/London`, `Asia/Tokyo`.

**Different polling interval?** Change `-e POLL_INTERVAL_SEC=120` to your preferred interval in seconds.

---

## Updating

### Manual update

```bash
cd TRMNL-Items && git pull
docker stop trmnl-items && docker rm trmnl-items
cd airport-tracker && docker build --no-cache -t trmnl-items .
docker run -d --name trmnl-items --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=<your-uuid> \
  -e POLL_INTERVAL_SEC=120 \
  -e DATA_FILE=/data/tracker_state.json \
  -v $(pwd)/data:/data \
  trmnl-items
```

### Auto-update (optional, Unraid)

If you're on Unraid, install the **User Scripts** plugin and create a script that runs on a schedule (daily recommended):

```bash
#!/bin/bash
cd /path/to/TRMNL-Items

git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "New changes found, updating..."
    git pull
    cd airport-tracker
    docker stop trmnl-items
    docker rm trmnl-items
    docker build --no-cache -t trmnl-items .
    docker run -d --name trmnl-items --restart unless-stopped \
        -e TZ=America/Los_Angeles \
        -e TRMNL_WEBHOOK_UUID=<your-uuid> \
        -e POLL_INTERVAL_SEC=120 \
        -e DATA_FILE=/data/tracker_state.json \
        -v /path/to/TRMNL-Items/airport-tracker/data:/data \
        trmnl-items
    echo "Update complete!"
else
    echo "Already up to date."
fi
```

---

## Useful Commands

| Command | What it does |
|---------|-------------|
| `docker logs trmnl-items` | View container logs |
| `docker logs trmnl-items 2>&1 \| tail -20` | View recent logs |
| `docker stop trmnl-items` | Stop the container |
| `docker start trmnl-items` | Start the container |
| `docker exec trmnl-items python -c "from tracker import *; state = load_state(); push_to_trmnl(build_trmnl_payload(state))"` | Force an immediate data push |

---

## Key Constraints

- **2KB payload limit** — TRMNL's standard plan limits webhook payloads to 2KB. Keep JSON keys short and data arrays small.
- **No grayscale** — e-ink displays render only black and white. Use CSS patterns (diagonal stripes, dots) instead of gray.
- **No external CSS/JS** — TRMNL's built-in CSS framework can conflict with custom styles. Stick to inline/embedded styles.
- **Timezone matters** — Docker containers default to UTC. Always set `-e TZ=` or timestamps will be wrong.
- **State resets daily** — tracker data resets at midnight. The state file stays small and never grows unbounded.

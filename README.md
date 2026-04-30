# TRMNL-Items

Custom plugins for the [TRMNL](https://usetrmnl.com/) e-ink display, powered by Docker and free APIs.

## Projects

### [Airport Tracker](airport-tracker/)
Tracks daily flight activity at a local airport using ADS-B data. Shows arrivals, departures, aircraft types, hourly activity chart, and weather. Configurable for any airport via environment variables (defaults to KMYF in San Diego).

### [Wiki Trending](wiki-trending/)
Shows Wikipedia articles trending well above their normal traffic, with AI-generated explanations of why each article is spiking. Uses Google Gemini with web search grounding, with fallbacks to Google News headlines and Wikipedia intros.

### [TRMNL Weather](weather-board/)
Today's land weather + 3-day forecast + ocean/surf conditions for a coastal beach break. Shows high/low (with comparison to yesterday), feels-like, wind, humidity, UV, rain chance, sunrise/sunset, ocean temperature, swell height/period/direction, and computed wave energy in kJ. Uses Open-Meteo Forecast and Marine APIs. Defaults to San Diego + La Jolla Shores; configurable via env vars.

---

## How It Works

Each project is a Python script that runs in a Docker container. It polls free APIs on a schedule, processes the data, and pushes a JSON payload to a TRMNL e-ink display via webhook.

```
  Free APIs (airplanes.live, Wikipedia, Open-Meteo, Gemini, etc.)
       |
       | poll on schedule
       v
  Docker container (any always-on server)
  - Fetches data from APIs
  - Processes & tracks state (JSON file on disk)
  - Builds payload (must stay under 2KB)
       |
       | push periodically
       v
  TRMNL webhook API
  - Receives JSON via POST
  - Merges variables into the Liquid template
       |
       | display refreshes periodically
       v
  TRMNL e-ink display (800x480, black & white)
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

### 2. Build and Run

Clone the repo:

```bash
git clone https://github.com/KurtMoran/TRMNL-Items.git
cd TRMNL-Items
```

**Airport Tracker:**

```bash
cd airport-tracker
docker build --no-cache -t trmnl-airport .
docker run -d --name trmnl-airport --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=your-uuid-here \
  -e AIRPORT_CODE=KMYF \
  -e AIRPORT_LAT=32.8157 \
  -e AIRPORT_LON=-117.1397 \
  -e AIRPORT_ELEV_FT=427 \
  -v $(pwd)/data:/data \
  trmnl-airport
```

**Wiki Trending:**

```bash
cd wiki-trending
docker build --no-cache -t wiki-trending .
docker run -d --name wiki-trending --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=your-uuid-here \
  -e GEMINI_API_KEY=your-key-here \
  -v $(pwd)/data:/data \
  wiki-trending
```

**TRMNL Weather:**

```bash
cd weather-board
docker build --no-cache -t weather-board .
docker run -d --name weather-board --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=your-uuid-here \
  -v $(pwd)/data:/data \
  weather-board
```

See each project's README for the full list of environment variables.

---

## Updating

An [`update.sh`](update.sh) script is included that pulls the latest code from GitHub, rebuilds all containers, and restarts them. It always rebuilds even if the code hasn't changed, so your containers get fresh data on every run.

### Automated Updates (Unraid)

The recommended way to run this is via the **User Scripts** plugin on Unraid with a daily schedule.

1. Install the **User Scripts** plugin from Community Applications
2. Add a new script (e.g. `trmnl-auto-update`)
3. Paste the following, replacing the placeholder values with your actual keys:

```bash
#!/bin/bash
export GEMINI_API_KEY="your-gemini-api-key"
export AIRPORT_WEBHOOK_UUID="your-airport-webhook-uuid"
export WIKI_WEBHOOK_UUID="your-wiki-webhook-uuid"
export WEATHER_WEBHOOK_UUID="your-weather-webhook-uuid"
bash /mnt/user/appdata/TRMNL-Items/update.sh
```

4. Set the schedule (e.g. daily) or run manually whenever you want fresh data

Your secrets stay in the User Script on your server and are never committed to the repo.

### Manual Updates

You can also run `update.sh` directly from the server terminal:

```bash
export GEMINI_API_KEY="your-gemini-api-key"
export AIRPORT_WEBHOOK_UUID="your-airport-webhook-uuid"
export WIKI_WEBHOOK_UUID="your-wiki-webhook-uuid"
export WEATHER_WEBHOOK_UUID="your-weather-webhook-uuid"
bash /mnt/user/appdata/TRMNL-Items/update.sh
```

After the script finishes, wait 2-3 minutes for the containers to fetch data and push to TRMNL, then force refresh your display.

### Adding a New Plugin

To add a new TRMNL plugin to the update script, add a new block to `update.sh` following the same pattern — stop, remove, build, run. Pass any required API keys as environment variables.

---

## Key Constraints

- **2KB payload limit** — TRMNL's standard plan limits webhook payloads to 2KB. Keep JSON keys short and data arrays small.
- **No grayscale** — e-ink displays render only black and white. Use CSS patterns (diagonal stripes, dots) instead of gray.
- **No external CSS/JS** — TRMNL's built-in CSS framework can conflict with custom styles. Stick to inline/embedded styles.
- **Timezone matters** — Docker containers default to UTC. Always set `-e TZ=` or timestamps will be wrong.

# TRMNL-Items

Custom plugins for the [TRMNL](https://usetrmnl.com/) e-ink display, powered by Docker and free APIs.

## Projects

### [Airport Tracker](airport-tracker/)
Tracks daily flight activity at a local airport using ADS-B data. Shows arrivals, departures, aircraft types, hourly activity chart, and weather. Configurable for any airport via environment variables (defaults to KMYF in San Diego).

### [Wiki Trending](wiki-trending/)
Shows Wikipedia articles trending well above their normal traffic, with AI-generated explanations of why each article is spiking. Uses Google Gemini with web search grounding, with fallbacks to Google News headlines and Wikipedia intros.

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

See each project's README for the full list of environment variables.

---

## Updating

```bash
cd /path/to/TRMNL-Items && git pull

# Rebuild whichever project changed:
docker stop <container-name> && docker rm <container-name>
cd <project-dir> && docker build --no-cache -t <image-name> .
docker run -d --name <container-name> --restart unless-stopped \
  -e TZ=... -e TRMNL_WEBHOOK_UUID=... \
  -v $(pwd)/data:/data \
  <image-name>
docker image prune -f
```

For automated updates on Unraid, use the **User Scripts** plugin with a daily schedule that checks for new commits and rebuilds.

---

## Key Constraints

- **2KB payload limit** — TRMNL's standard plan limits webhook payloads to 2KB. Keep JSON keys short and data arrays small.
- **No grayscale** — e-ink displays render only black and white. Use CSS patterns (diagonal stripes, dots) instead of gray.
- **No external CSS/JS** — TRMNL's built-in CSS framework can conflict with custom styles. Stick to inline/embedded styles.
- **Timezone matters** — Docker containers default to UTC. Always set `-e TZ=` or timestamps will be wrong.

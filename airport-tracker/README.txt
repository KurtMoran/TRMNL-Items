KMYF Airport Tracker for TRMNL E-Ink Display
=============================================

What it does:
  Tracks aircraft arriving and departing Montgomery-Gibbs Executive Airport
  (KMYF) in San Diego and displays daily stats on a TRMNL e-ink display.

How it works:
  A Python script runs in a Docker container on an Unraid server (KServer).
  Every 2 minutes it polls the airplanes.live API for aircraft within 3nm
  of KMYF and below 1500ft AGL. It classifies movements as arrivals
  (descending, baro_rate < -200) or departures (climbing, baro_rate > 200)
  based on vertical rate. Every ~10 minutes it pushes a JSON summary to the
  TRMNL display via webhook. State resets at midnight each day.

  The display shows:
  - Total operations, arrivals, and departures for the day
  - Peak hour and count
  - Top 6 aircraft types seen (e.g. Cessna 172, Piper Cherokee)
  - Hourly activity bar chart (auto-scaled, arrivals solid, departures striped)
  - Daily high/low temperature from Open-Meteo

  The TRMNL has a 2KB payload limit, so all JSON variable names are shortened:
  ops, arr, dep, pk, pkn, hi, lo, updated, types, hourly (with aw/dw for
  pre-computed bar widths).

APIs used (all free, no auth required):
  - airplanes.live - ADS-B flight tracking data
  - Open-Meteo - weather forecasts
  - TRMNL webhook - push data to e-ink display

Files in this folder:
  tracker.py          - Main tracker script (runs inside Docker container)
  trmnl_template.html - Liquid/HTML template (paste into TRMNL markup editor)
  preview.html        - Local browser preview with sample data (open in browser)
  backfill.py         - One-time script to populate a realistic day of data
  Dockerfile          - Docker build instructions (Python 3.12-slim base)
  requirements.txt    - Python dependencies (just "requests")
  README.txt          - This file

Design decisions:
  - No TRMNL CSS framework in templates (it conflicts with custom styles)
  - No TRMNL logo in footer
  - "Remove bleed margin" = Yes in TRMNL plugin settings
  - Departure bars use diagonal stripe pattern (e-ink can't render grayscale)
  - Rounded corners on stat boxes (border-radius: 10px)
  - Uses .format() not f-strings (heredoc compatibility on Unraid terminal)
  - Hourly bar widths pre-computed in tracker.py (aw/dw fields) so the
    busiest hour fills ~300px and all others scale proportionally
  - Aircraft type names use white-space: nowrap to prevent line wrapping

TRMNL plugin config:
  - Plugin type: Private plugin, Webhook strategy
  - Webhook UUID: ac1fa5b5-e77f-485d-b8c0-056ed1db540d
  - Remove bleed margin: Yes

GitHub repo:
  https://github.com/KurtMoran/TRMNL-Items (public)

Server setup (Unraid):
  Repo cloned to: /mnt/user/appdata/TRMNL-Items/
  Data persisted at: /mnt/user/appdata/TRMNL-Items/airport-tracker/data/
  Container name: trmnl-items
  Image name: trmnl-items
  Timezone: America/Los_Angeles (must be set or times show UTC)

  First-time setup:
    git clone https://github.com/KurtMoran/TRMNL-Items.git /mnt/user/appdata/TRMNL-Items
    cd /mnt/user/appdata/TRMNL-Items/airport-tracker
    docker build --no-cache -t trmnl-items .
    docker run -d --name trmnl-items --restart unless-stopped \
      -e TZ=America/Los_Angeles \
      -e TRMNL_WEBHOOK_UUID=ac1fa5b5-e77f-485d-b8c0-056ed1db540d \
      -e POLL_INTERVAL_SEC=120 \
      -e DATA_FILE=/data/tracker_state.json \
      -v /mnt/user/appdata/TRMNL-Items/airport-tracker/data:/data \
      trmnl-items

  Auto-update from GitHub:
    A User Script ("trmnl-auto-update") runs daily via the Unraid User Scripts
    plugin. It checks GitHub for new commits, and if found, pulls the latest
    code, rebuilds the Docker image, and restarts the container. Data is
    preserved since it lives in a mounted volume.

  Manual update from GitHub:
    cd /mnt/user/appdata/TRMNL-Items && git pull
    docker stop trmnl-items && docker rm trmnl-items
    cd airport-tracker && docker build --no-cache -t trmnl-items .
    docker run -d --name trmnl-items --restart unless-stopped \
      -e TZ=America/Los_Angeles \
      -e TRMNL_WEBHOOK_UUID=ac1fa5b5-e77f-485d-b8c0-056ed1db540d \
      -e POLL_INTERVAL_SEC=120 \
      -e DATA_FILE=/data/tracker_state.json \
      -v /mnt/user/appdata/TRMNL-Items/airport-tracker/data:/data \
      trmnl-items

  Useful commands:
    docker logs trmnl-items                  - View logs
    docker logs trmnl-items 2>&1 | tail -20  - Recent logs
    docker stop trmnl-items                  - Stop
    docker start trmnl-items                 - Start

  Force a data push:
    docker exec trmnl-items python -c "
    from tracker import *
    state = load_state()
    payload = build_trmnl_payload(state)
    push_to_trmnl(payload)
    "

How to update the TRMNL template:
  1. Copy contents of trmnl_template.html
  2. Go to TRMNL dashboard > Airport Tracker plugin > Edit Markup
  3. Paste and Save
  4. Force Refresh to see changes

Troubleshooting:
  - Times showing UTC? Add -e TZ=America/Los_Angeles to docker run
  - 422 payload too large? Variable names or data arrays need trimming
  - Bars not showing? Template might need new data pushed (force push above)
  - Docker build using old code? Use --no-cache flag
  - Gray bars invisible on e-ink? Use stripe pattern, not grayscale colors
  - Container not restarting after reboot? Check --restart unless-stopped flag

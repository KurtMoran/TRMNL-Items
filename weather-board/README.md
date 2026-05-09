# TRMNL Weather

E-ink dashboard showing today's land weather, 3-day forecast, and ocean/surf conditions for a coastal beach break.

## How it works

1. Polls Open-Meteo Forecast API for land weather: today's high/low, current conditions, wind, humidity, UV, sunrise/sunset, 3-day outlook, plus yesterday's high (for the "X° cooler/warmer" comparison).
2. Polls Open-Meteo Marine API for ocean swell: height, period, direction (today + 3-day forecast SST).
3. Polls **NOAA CO-OPS station 9410230** (Scripps Pier, 6-min cadence) and **NDBC station LJAC1** (same pier, intermittent) for today's water temperature. The two pier sensors are merged into one hourly observation series; NOAA's freshest sample drives the displayed "now" value. Today's water-temp curve plots **real merged observations for past hours** and **calibrated Open-Meteo forecast for future hours**, so the dot you see for "now" sits on a measured reading rather than a model output.
4. Calibrates the 3-day SST forecast: Open-Meteo's offshore model runs ~2-4°F warm vs nearshore observations in summer/fall (upwelling). Bias = median of today's hourly (real - OM) pairs, robust against internal-bore transients at the pier.
5. Calculates wave energy in kJ from the swell height + period (`0.49 × H² × T`).
6. Pushes a JSON payload to a TRMNL e-ink display via webhook.

Default location: San Diego (land) + La Jolla Shores (ocean). Configurable via env vars.

## APIs used

| API | Auth | Cost | Rate |
|-----|------|------|------|
| Open-Meteo Forecast | None | Free | 1 request/cycle |
| Open-Meteo Marine | None | Free | 1 request/cycle |
| NOAA CO-OPS (Scripps Pier water_temperature, 6-min) | None | Free | 1 request/cycle |
| NDBC realtime2 (Scripps Pier WTMP, secondary) | None | Free | 1 request/cycle |
| Launch Library 2 (Vandenberg launches) | None (optional token) | Free | ~12 requests/hour (~80% of free tier) |
| TRMNL Webhook | Plugin UUID | Included with TRMNL | 1 push/cycle |

Polls every 15 minutes (matches TRMNL's e-ink refresh cadence).

Launch Library 2 is fetched on its own background thread — `LAUNCH_REFRESH_SEC`
(default 300s = 12 calls/hour, ~80% of the free 15/hr tier) controls cadence,
fully independent of `POLL_INTERVAL_SEC`. Cache file persists to disk so
container restarts don't burn extra budget. On `429` or network error we
keep serving the stale cache.

## Setup

### 1. Create TRMNL plugin

- Go to trmnl.com > Plugins > Private Plugin > Create
- Name: "TRMNL Weather"
- Strategy: **Webhook**
- Paste contents of `trmnl_template.html` into the Markup editor
- Set "Remove bleed margin" = Yes
- Copy the webhook UUID

### 2. Build and run

```bash
docker build -t weather-board /path/to/weather-board/

docker run -d \
  --name weather-board \
  --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=your-uuid-here \
  -v /path/to/data:/data \
  weather-board
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRMNL_WEBHOOK_UUID` | Yes | — | From your TRMNL private plugin |
| `WEATHER_LAT` | No | 32.7838 | Land weather latitude (default: San Diego) |
| `WEATHER_LON` | No | -117.1116 | Land weather longitude |
| `LOCATION_NAME` | No | San Diego | Footer label |
| `OCEAN_LAT` | No | 32.8541 | Ocean/marine latitude (default: La Jolla Shores) |
| `OCEAN_LON` | No | -117.2618 | Ocean/marine longitude |
| `OCEAN_NAME` | No | Ocean | Ocean section label |
| `SAME_THRESHOLD` | No | 1 | °F window for "Same as yesterday" |
| `POLL_INTERVAL_SEC` | No | 900 | Seconds between cycles (default: 15 min) |
| `TZ` | No | America/Los_Angeles | Timezone for timestamps & API |
| `DATA_FILE` | No | /data/weather_state.json | State file path |
| `NDBC_STATION` | No | LJAC1 | NDBC station ID for secondary water-temp feed (default: Scripps Pier) |
| `NOAA_WTEMP_STATION` | No | (same as `TIDE_STATION_ID`) | NOAA CO-OPS station ID for primary 6-min water-temp feed |
| `LAUNCH_REFRESH_SEC` | No | 300 | Seconds between Launch Library 2 fetches (default 5min = 12/hour, ~80% of free 15/hr tier) |
| `LAUNCH_LOOKAHEAD_DAYS` | No | 3 | How many days ahead to look for upcoming launches. Today's launches get a curve marker; future-day launches show only in the hero text with a day-of-week prefix |
| `LL2_LOCATION_IDS` | No | 11 | Comma-separated LL2 location IDs (11 = Vandenberg SFB) |
| `LL2_API_KEY` | No | — | Optional LL2 token; lifts the free-tier rate limit |
| `LAUNCH_LOCATION_LABEL` | No | Vandenberg | Short label shown on the e-ink display |
| `LAUNCH_CACHE_FILE` | No | /data/launches_cache.json | Where the launch cache is persisted |

## Files

| File | Purpose |
|------|---------|
| `weather.py` | Main script — polls APIs and pushes to TRMNL |
| `trmnl_template.html` | Liquid template — paste into TRMNL Markup editor |
| `preview.html` | Standalone browser preview with sample data |
| `Dockerfile` | Container build |
| `requirements.txt` | Python dependencies |

## Wave energy formula

`E = (ρg² / 16π) × H² × T² ≈ 1.96 × H² × T²`

- `H` = swell wave height in **meters** (Open-Meteo returns feet, code converts internally)
- `T` = peak swell period in seconds
- Output is wave energy density × wavelength per meter of crest, in kJ

Calibrated against surf-forecast.com's published ranges:
- ~100 kJ — just about surfable at many breaks
- 200-1000 kJ — increasingly punchy
- 1000-5000+ kJ — heavy / dangerous conditions

Sample values:
- 2ft × 11s ≈ 85 kJ (small)
- 4ft × 14s ≈ 440 kJ (moderate)
- 6ft × 16s ≈ 1290 kJ (big)

## Weather icons

Inline SVGs in the template, switched via Liquid `case` on the WMO weather code. 8 icons cover all conditions:

| Icon key | WMO codes | Meaning |
|----------|-----------|---------|
| `sun` | 0 | Clear |
| `sun-cloud` | 1 | Mostly clear |
| `partly-cloudy` | 2 | Partly cloudy |
| `cloud` | 3 | Overcast |
| `fog` | 45, 48 | Fog |
| `rain` | 51-67, 80-82 | Rain / drizzle / showers |
| `snow` | 71-77, 85-86 | Snow |
| `storm` | 95-99 | Thunderstorm |

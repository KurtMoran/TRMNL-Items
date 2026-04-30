# TRMNL Weather

E-ink dashboard showing today's land weather, 3-day forecast, and ocean/surf conditions for a coastal beach break.

## How it works

1. Polls Open-Meteo Forecast API for land weather: today's high/low, current conditions, wind, humidity, UV, sunrise/sunset, 3-day outlook, plus yesterday's high (for the "X° cooler/warmer" comparison).
2. Polls Open-Meteo Marine API for ocean: sea surface temperature, swell height/period/direction.
3. Calculates wave energy in kJ from the swell height + period (`0.49 × H² × T`).
4. Pushes a JSON payload to a TRMNL e-ink display via webhook.

Default location: San Diego (land) + La Jolla Shores (ocean). Configurable via env vars.

## APIs used

| API | Auth | Cost | Rate |
|-----|------|------|------|
| Open-Meteo Forecast | None | Free | 1 request/cycle |
| Open-Meteo Marine | None | Free | 1 request/cycle |
| TRMNL Webhook | Plugin UUID | Included with TRMNL | 1 push/cycle |

Polls every 15 minutes (matches TRMNL's e-ink refresh cadence).

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
| `WEATHER_LAT` | No | 32.7157 | Land weather latitude (default: San Diego) |
| `WEATHER_LON` | No | -117.1611 | Land weather longitude |
| `LOCATION_NAME` | No | San Diego | Footer label |
| `OCEAN_LAT` | No | 32.8567 | Ocean/marine latitude (default: La Jolla Shores) |
| `OCEAN_LON` | No | -117.2547 | Ocean/marine longitude |
| `OCEAN_NAME` | No | La Jolla Shores | Ocean section label |
| `SAME_THRESHOLD` | No | 1 | °F window for "Same as yesterday" |
| `POLL_INTERVAL_SEC` | No | 900 | Seconds between cycles (default: 15 min) |
| `TZ` | No | America/Los_Angeles | Timezone for timestamps & API |
| `DATA_FILE` | No | /data/weather_state.json | State file path |

## Files

| File | Purpose |
|------|---------|
| `weather.py` | Main script — polls APIs and pushes to TRMNL |
| `trmnl_template.html` | Liquid template — paste into TRMNL Markup editor |
| `preview.html` | Standalone browser preview with sample data |
| `Dockerfile` | Container build |
| `requirements.txt` | Python dependencies |

## Wave energy formula

`E = 0.49 × H² × T`

- `H` = swell wave height in **meters** (Open-Meteo returns feet, code converts internally)
- `T` = peak swell period in seconds
- Output is kW/m of wave crest (= kJ/s/m); displayed as "kJ" matching surf-forecast.com convention

Sample values:
- 1m @ 10s ≈ 5 kJ
- 2m @ 12s ≈ 24 kJ
- 3m @ 14s ≈ 62 kJ

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

# TRMNL Weather

E-ink dashboard for a coastal location: today's land weather hero, a 3-day
forecast (with per-day air + ocean data merged into a single card), a
conditions strip (wind, humidity, UV, rain, AQI, sunrise/sunset with quality),
and a bottom ocean strip with today's water-temp curve and tide markers.

## How it works

1. **Land weather comes from two sources, merged field by field** (see
   [Land weather sources](#land-weather-sources)):
   - **National Weather Service** (primary): the local NWS office's forecast
     for each day's hi/lo, sky, rain chance and wind; the nearest airport
     weather station's *measured* feels-like, wind and humidity right now;
     and that station's measured high yesterday for the "X° cooler/warmer
     than yesterday" line.
   - **Open-Meteo Forecast** (base layer): UV, sunrise/sunset, and any field
     NWS didn't supply this cycle. If NWS is down, the board runs entirely on
     Open-Meteo, and vice versa.
2. Polls **Open-Meteo Marine** for ocean data: hourly SST, hourly swell
   height/period, daily swell direction. Daily SST hi *and* lo are computed
   from the hourly buckets for each forecast day.
3. Polls **NOAA CO-OPS station 9410230** (Scripps Pier, 6-min water-temp
   cadence) and **NDBC station LJAC1** (same pier, intermittent ~30 min) as
   redundant nearshore feeds. The two sensors are merged into one hourly
   observation series; NOAA's freshest sample drives the displayed "now"
   value.
4. Today's water-temp curve plots **real merged observations for past hours**
   and **calibrated Open-Meteo forecast for future hours**, sampled every
   2 hours and smoothed with Catmull-Rom interpolation. The "now" dot always
   sits on a measured reading rather than a model output.
5. **SST calibration** for the 3-day forecast: Open-Meteo's offshore model
   runs ~2-4°F warm vs nearshore observations in summer/fall (upwelling).
   Bias = *median* of today's hourly (real - OM) pairs, applied to both the
   forecast hi and lo. The median is robust against internal-bore transients
   at the pier (5-7°F drops that recover within an hour).
6. Polls **Sunsethue `/forecast?days=4`** for sunrise + sunset quality scores
   (0–100%, derived from cloud cover, atmospheric clarity, and other factors)
   covering today + the next 3 days. Today's values render in the conditions
   strip next to the sunrise/sunset times; per-day values appear under each
   forecast card. **Average-fill** kicks in when the Sunsethue model's 78h
   horizon leaves the furthest day's sunset without `model_data` — rather
   than render a blank slot, the card shows the mean of the other days'
   sunset values.
7. **Marine-layer reclassification**: SD's classic "May gray" / "June gloom"
   shows up as Open-Meteo WMO codes 51–57 (light drizzle) with
   `precipitation_probability_max = 0%`. Without intervention the card would
   read "rain icon + Light drizzle + 0% rain" — a contradiction. We
   reclassify those cases as the fog icon labeled "Mist."
8. **Launch Library 2** runs on a background thread fetching upcoming
   Vandenberg launches for today's hero and (if launch is today) a marker on
   the water-temp curve.
9. Pushes a compact JSON payload to a TRMNL e-ink display via webhook
   (`merge_variables`, ≤ 2 KB).

Default location: San Diego (land) + La Jolla Shores (ocean) + Sunset Cliffs
(sunrise/sunset quality location). All configurable via env vars.

## 3-day forecast cards

Each card stacks (top to bottom):

```
              MON                  ← day name
               ☁                   ← weather icon (28px)
             Foggy                 ← WMO phrase, with marine-layer override
          73° / 58°   -1°          ← air hi/lo + delta vs today
         0% rain · UV 8            ← precip probability + UV index
            8 mph WSW              ← daily max wind + dominant direction
         ↑ 28%   ↓ 21%             ← sunrise + sunset quality % (with sun icons)
        ─── OCEAN ───              ← divider
          67° / 65°   0°           ← ocean hi/lo + delta (calibrated)
            2ft 15s ↓              ← swell height + period + dominant arrow
              [≋]                  ← wave-energy silhouette (tier 1-5)
            241 kJ                 ← wave energy
```

The card uses `justify-content: space-between` so all 11 elements distribute
evenly down the card height — no awkward bottom whitespace regardless of
available space.

## Swell-direction arrows

Arrows point at the direction the swell is **coming from** (oceanographic
convention from Open-Meteo's `swell_wave_direction_dominant`):

| Arrow | Origin | Notes for SoCal coast |
|-------|--------|-----------------------|
| `↑` `↖` `↗` | N / NW / NE | Winter Aleutian/Gulf-of-Alaska swells, dominate Nov–Mar |
| `←` | W | Mixed-season, hits most west-facing beaches directly |
| `↙` | SW | Spring/summer transition |
| `↓` `↘` | S / SE | Summer Southern Hemisphere storms, dominate Jun–Sep |

## APIs used

| API | Auth | Cost | Rate / Cycle |
|-----|------|------|--------------|
| NWS forecast (api.weather.gov) | None (User-Agent) | Free | 1 req/cycle |
| NWS latest station observation | None (User-Agent) | Free | 1 req/cycle |
| NWS station history (yesterday's high) | None (User-Agent) | Free | 1 req/day |
| NWS grid + station lookup | None (User-Agent) | Free | 2 req/week (cached) |
| Open-Meteo Forecast | None | Free | 1 req/cycle |
| Open-Meteo Marine | None | Free | 1 req/cycle |
| Open-Meteo Air Quality | None | Free | 1 req/cycle |
| NOAA CO-OPS (water_temperature) | None | Free | 1 req/cycle |
| NOAA CO-OPS (tide predictions) | None | Free | 1 req/cycle |
| NDBC realtime2 (Scripps Pier WTMP) | None | Free | 1 req/cycle |
| Launch Library 2 (Vandenberg) | None (optional token) | Free | ~12 req/hour on background thread (~80% of 15/hr tier) |
| Sunsethue `/forecast?days=4` | API key | Free tier | ~4 req/day (6h cache, 8 events × 5 credits = 160 credits/day) |
| TRMNL Webhook | Plugin UUID | Included | 1 push/cycle |

Polls every 15 minutes (`POLL_INTERVAL_SEC=900`, matches TRMNL's e-ink
refresh cadence). Launch Library 2 runs on its own background thread so its
~5-min cadence is independent of the main poll. Sunsethue caches for 6 hours
because the underlying model only updates twice daily (00z and 12z runs
refresh the full 78h horizon).

### Land weather sources

Open-Meteo is a single global model blend, and its daily weather code is the
*worst* hour of the day, so one rainy hour turns a mostly dry day into "Heavy
rain". The NWS forecast comes from the local office's forecasters
(San Diego = SGX), who handle local effects like the marine layer, and it
describes the day rather than its worst hour.

Each field starts from Open-Meteo and is replaced by NWS whenever NWS
supplied a value:

| Field | Source | Fallback |
|-------|--------|----------|
| Hi / lo, sky icon + phrase, rain %, wind (today + 3 days) | NWS forecast | Open-Meteo |
| Feels-like, wind, humidity (now) | Nearest airport station's latest reading (≤ 2h old) | Open-Meteo current |
| Yesterday's high (for the delta line) | Same station, measured, fetched once a day | Open-Meteo `past_days=1` |
| UV, sunrise/sunset | Open-Meteo only | — |

Details:

- **Day = daytime period + the night after it**, the usual US convention.
  So `lo` is that night's low, not the morning low before the high.
- **Today's high in the evening**: NWS drops the daytime period at ~6pm, so
  the last daytime forecast seen today is kept in `API_CACHE_FILE`. A
  container started fresh in the evening uses Open-Meteo's high until the
  next morning.
- **Phrases** are condensed to fit the ~90px cards: `Slight Chance Rain
  Showers then Mostly Sunny` → "Mostly sunny". Real precipitation wins
  (anything but "Slight Chance"); otherwise the last sky clause (the
  afternoon); fog only if nothing else is forecast. "Chance"/"Likely" are
  dropped because the card already shows the rain %.
- **Feels-like** uses NWS's definition: heat index when hot and humid, wind
  chill when cold and windy, otherwise the measured air temperature.
- **Station**: the grid lookup returns stations nearest-first; the board
  picks the first airport (ICAO-style ID, e.g. KMYF Montgomery Field)
  because those are quality-controlled ASOS stations. Override with
  `NWS_STATION`.
- **Staleness guards**: a forecast NWS hasn't updated in 24h, or a station
  reading older than 2h, is ignored in favor of Open-Meteo.
- **Outside the US** the NWS grid lookup fails and the board runs on
  Open-Meteo alone. Set `NWS_ENABLED=0` to skip the lookup.

### Failed fetches

Open-Meteo's forecast endpoint occasionally hangs past the read timeout. A
failed cycle used to push `--` for every land-weather field, wiping the good
data already on the display. Now:

- Every Open-Meteo, NWS and NOAA tide request is tried up to `FETCH_ATTEMPTS`
  times (5s connect / 10s read timeout, 2s then 4s backoff). Timeouts,
  connection errors, 429s and 5xx are retried; other 4xx are not.
- Each good response is saved to `API_CACHE_FILE`. If every attempt fails,
  the cycle reuses the last good response, as long as it is from the **same
  local date** and younger than `API_CACHE_MAX_AGE_SEC`. The same-date rule
  matters because the parsers index daily arrays by position (forecast
  index 1 = today), so yesterday's response would shift every day by one.
- A cycle served from the cache is still logged as a failure, so outages
  stay visible:
  ```
  ✗ 71°/59° Heavy rain, ... — live fetch failed (Read timed out. ... (after 3 attempts)); using last good from 15m ago
  ```

## Setup

### 1. Create TRMNL plugin

- Go to trmnl.com > Plugins > Private Plugin > Create
- Name: "TRMNL Weather"
- Strategy: **Webhook**
- Paste contents of `trmnl_template.html` into the Markup editor
- Set "Remove bleed margin" = Yes
- Copy the webhook UUID

### 2. (Recommended) Get a Sunsethue API key

- Sign up at [sunsethue.com/dev-api](https://sunsethue.com/dev-api)
- Generate an API key in the portal
- Without it, the sunrise/sunset quality numbers won't render

### 3. Build and run

```bash
docker build -t weather-board /path/to/weather-board/

docker run -d \
  --name weather-board \
  --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=your-uuid-here \
  -e SUNSETHUE_API_KEY=your-sunsethue-key-here \
  -v /path/to/data:/data \
  weather-board
```

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRMNL_WEBHOOK_UUID` | Yes | — | From your TRMNL private plugin |
| `WEATHER_LAT` | No | 32.7838 | Land weather latitude (default: San Diego, Mission Valley area) |
| `WEATHER_LON` | No | -117.1116 | Land weather longitude |
| `LOCATION_NAME` | No | San Diego | Footer label |
| `OCEAN_LAT` | No | 32.8541 | Ocean/marine latitude (default: La Jolla Shores) |
| `OCEAN_LON` | No | -117.2618 | Ocean/marine longitude |
| `OCEAN_NAME` | No | Ocean | Ocean section label |
| `SAME_THRESHOLD` | No | 1 | °F window for "Same as yesterday" |
| `POLL_INTERVAL_SEC` | No | 900 | Seconds between cycles (default: 15 min) |
| `TZ` | No | America/Los_Angeles | Timezone for timestamps & API |
| `DATA_FILE` | No | /data/weather_state.json | State file path |
| `API_CACHE_FILE` | No | /data/api_cache.json | Last-good copy of each API response, used when a live fetch fails |
| `API_CACHE_MAX_AGE_SEC` | No | 21600 | Oldest cached response (same local date only) the fallback will serve |
| `FETCH_ATTEMPTS` | No | 3 | Tries per API request before falling back to the cache |
| `NWS_ENABLED` | No | 1 | Set to `0` to skip the National Weather Service (e.g. outside the US) |
| `NWS_STATION` | No | (nearest airport) | Weather station ID for current conditions + yesterday's high, e.g. `KMYF` |
| `NWS_USER_AGENT` | No | trmnl-weather-board/1.0 | NWS asks clients to identify themselves; add your own contact if you like |
| `TIDE_STATION_ID` | No | 9410230 | NOAA CO-OPS tide station (default: La Jolla / Scripps Pier) |
| `NDBC_STATION` | No | LJAC1 | NDBC station ID for secondary water-temp feed (default: Scripps Pier) |
| `NOAA_WTEMP_STATION` | No | (same as `TIDE_STATION_ID`) | NOAA CO-OPS station ID for primary 6-min water-temp feed |
| `LAUNCH_REFRESH_SEC` | No | 300 | Seconds between Launch Library 2 fetches |
| `LAUNCH_LOOKAHEAD_DAYS` | No | 3 | How many days ahead to look for upcoming launches |
| `LL2_LOCATION_IDS` | No | 11 | Comma-separated LL2 location IDs (11 = Vandenberg SFB) |
| `LL2_API_KEY` | No | — | Optional LL2 token; lifts free-tier rate limit |
| `LAUNCH_LOCATION_LABEL` | No | Vandenberg | Short label shown on display |
| `LAUNCH_CACHE_FILE` | No | /data/launches_cache.json | Where the launch cache is persisted |
| `SUNSETHUE_API_KEY` | No (recommended) | — | Sunsethue API key. When unset, sunrise/sunset quality stays hidden |
| `SUNSETHUE_LAT` | No | 32.7255 | Latitude for sunrise/sunset quality (default: Sunset Cliffs, San Diego) |
| `SUNSETHUE_LON` | No | -117.2580 | Longitude for sunrise/sunset quality |
| `SUNSETHUE_REFRESH_SEC` | No | 21600 | Cache duration in seconds (default 6h, covers both daily model update windows) |
| `SUNSETHUE_CACHE_FILE` | No | /data/sunsethue_cache.json | Where the sunset-quality cache is persisted |

## Files

| File | Purpose |
|------|---------|
| `weather.py` | Main script — polls APIs, builds payload, pushes to TRMNL |
| `trmnl_template.html` | Liquid template — paste into TRMNL Markup editor |
| `preview.html` | Standalone browser preview with sample data |
| `Dockerfile` | Container build |
| `requirements.txt` | Python dependencies |

## Wave energy formula

`E = (ρg² / 16π) × H² × T² ≈ 1.96 × H² × T²`

- `H` = swell wave height in **meters** (Open-Meteo returns feet, code converts internally)
- `T` = peak swell period in seconds
- Output is wave energy density × wavelength per meter of crest, in kJ

Tier mapping (drives the silhouette icon — 1=flat, 5=heavy):

| Tier | kJ range | Character |
|------|----------|-----------|
| 1 | < 100 | Flat / barely surfable |
| 2 | 100–200 | Surfable at most breaks |
| 3 | 200–1000 | Increasingly punchy |
| 4 | 1000–5000 | Heavy |
| 5 | 5000+ | Dangerous |

Sample values:
- 2ft × 11s ≈ 85 kJ (small)
- 4ft × 14s ≈ 440 kJ (moderate)
- 6ft × 16s ≈ 1290 kJ (big)

## Weather icons

Inline SVGs in the template, switched via Liquid `case` on the WMO weather
code. 8 icons cover all conditions:

| Icon key | WMO codes | Phrase examples |
|----------|-----------|-----------------|
| `sun` (`s`) | 0 | Clear |
| `sun-cloud` (`sc`) | 1 | Mostly clear |
| `partly-cloudy` (`pc`) | 2 | Partly cloudy |
| `cloud` (`c`) | 3 | Overcast |
| `fog` (`f`) | 45, 48 | Foggy |
| `rain` (`r`) | 51–67, 80–82 | Drizzle, Rain, Showers |
| `snow` (`sn`) | 71–77, 85–86 | Snow |
| `storm` (`st`) | 95–99 | Thunderstorm |

The hero uses the long-form keys (`'sun'`, `'cloud'`, etc.); the forecast
cards use the 1-2 letter short codes for payload-size reasons.

**Marine-layer override**: codes 51–57 (drizzle) with
`precipitation_probability_max == 0%` get reclassified as `fog` + "Mist" —
this catches SD's coastal marine layer, which Open-Meteo labels as drizzle
even when it's just sub-measurable mist.

## Payload size

TRMNL caps `merge_variables` at **2 KB**. The forecast array alone is
expensive (3 cards × ~17 fields each), so the merged payload uses several
size optimizations:

- **Short field names** in the forecast cards (1-2 chars: `day` → `d`,
  `precip` → `pp`, `ocean_hi` → `oh`, etc.). Saves ~370 bytes vs verbose names.
- **Raw integers** instead of formatted strings — the template adds suffixes
  back (e.g. `{{ d.pp }}% rain`, `UV {{ d.uv }}`, `{{ d.e }} kJ`).
- **`ensure_ascii=False`** on `json.dumps` so unicode (`°`, swell arrows,
  tide arrows) stay as 2-3 byte UTF-8 instead of 6-char `\uXXXX` escapes.
  Saves ~50 bytes.
- **Curve resampled every 2 hours** (was every hour) — halves the SVG
  cubic-Bezier path string from ~24 segments to ~13. Saves ~220 bytes.

Typical payload size after these optimizations: **~1.8-1.9 KB**.

The actual size is logged each cycle:
```
→ TRMNL webhook — POST trmnl.com/api/custom_plugins/... — merge_variables (1885 bytes)
  ✓ 200 OK (1885 bytes sent)
```

## Water temperature physical context

The displayed "Now" ocean temp comes from NOAA station 9410230 (Scripps
Pier), sensor `E1`, hanging **11.3 ft below MLLW** (always 8–15 ft
underwater depending on tide). This is a **subsurface** measurement of bulk
water mass, not a sea-surface skin temperature. Sea-Bird Electronics
oceanographic thermistor; accuracy ±0.005°C.

Implications:
- For divers, this is essentially the temperature you'll experience at
  recreational depths near the pier.
- For swimmers/snorkelers at the surface in summer, the actual surface might
  be 1-3°F warmer due to solar heating of the top few inches.
- Internal bores (cold deep water briefly upwelling to sensor depth) show up
  as 5-10°F dips in the raw NOAA chart. Our hourly bucketing smooths these
  out for the displayed curve and the calibration delta.

## Sunsethue notes

Sunsethue's `/forecast` endpoint has a 78-hour horizon. The model runs 4×
daily (00z, 06z, 12z, 18z UTC), but only the 00z and 12z runs refresh the
full horizon — 06z and 18z only update the first 28h. So at certain times
of day, the furthest forecast event (the last day's sunset) may come back
with `model_data: false`. Our average-fill logic catches this: any expected
day missing sunrise or sunset gets filled in with the mean of the other
days' values for that event type, flagged `estimated: True` in the cache
(unused by the template currently but available for future visual
differentiation).

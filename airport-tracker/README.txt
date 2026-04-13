Airport Tracker for TRMNL E-Ink Display
========================================

Tracks aircraft arriving and departing a local airport and displays daily
stats on a TRMNL e-ink display.

How it works:
  A Python script runs in a Docker container, polling airplanes.live every
  2 minutes for aircraft within 3nm of the airport and below 1500ft AGL.
  It classifies movements as arrivals (descending, baro_rate < -200) or
  departures (climbing, baro_rate > 200). Every ~10 minutes it pushes a
  JSON summary to the TRMNL display via webhook. State resets at midnight.

  The display shows:
  - Total operations, arrivals, and departures for the day
  - Peak hour and count
  - Top 6 aircraft types seen
  - Hourly activity bar chart (arrivals solid, departures striped)
  - Daily high/low temperature

APIs used (all free, no auth required):
  - airplanes.live — ADS-B flight tracking data
  - Open-Meteo — weather forecasts
  - TRMNL webhook — push data to e-ink display

Environment variables:
  TRMNL_WEBHOOK_UUID  (required) From your TRMNL private plugin
  AIRPORT_LAT         Latitude (default: 32.8157 / KMYF)
  AIRPORT_LON         Longitude (default: -117.1397 / KMYF)
  AIRPORT_ELEV_FT     Field elevation in feet (default: 427 / KMYF)
  AIRPORT_CODE        Used in log messages (default: KMYF)
                      Note: the display name in the footer is set via
                      a Custom Field on the TRMNL plugin settings page.
  TZ                  Timezone (default: UTC)
  POLL_INTERVAL_SEC   Seconds between polls (default: 120)
  DATA_FILE           State file path (default: /data/tracker_state.json)

Files:
  tracker.py          Main tracker script
  trmnl_template.html Liquid template (paste into TRMNL markup editor)
  preview.html        Browser preview with sample data
  Dockerfile          Docker build (Python 3.12-slim)
  requirements.txt    Python dependencies
  README.txt          This file

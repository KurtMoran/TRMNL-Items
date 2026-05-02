# scratch/

**One-off analysis scripts. Not used by any of the running services.**

None of these files are required for `airport-tracker`, `weather-board`, or
`wiki-trending` to function. None of them are imported by any Dockerfile, none
of them run on the Unraid server. You can safely delete this whole folder
without affecting anything in production.

This is a scratchpad — keep these around only because re-running them later
might be useful, or because they're worth referring back to.

## What's here

| File | What it does |
|---|---|
| `ljac1_year_overlay.py` | Static matplotlib PNG overlaying every day of the last year of LJAC1 (Scripps Pier) water-temp readings on one chart, hour-of-day vs °F. Highlights today. |
| `ljac1_year_overlay.png` | Output of the above. |
| `ljac1_year_overlay_interactive.py` | Same idea but Plotly HTML — hover any line to highlight that day, fade the others, and see a date tooltip. |
| `ljac1_year_overlay.html` | Output of the above. Open in any browser. |
| `test_calibration_delta.py` | Simulation comparing the old single-point vs new windowed-median SST calibration math in `weather-board/weather.py`. Pulls live NDBC data and walks hour-by-hour through today to show what `delta` would have been at each 15-min refresh. Used to validate that the windowed median ignores transient internal-bore spikes. |

## Why these exist

These scripts were created while investigating a sharp dip in the La Jolla
Shores water temp shown on the weather TRMNL display on 2026-05-02. The dip
turned out to be a real internal-bore event at Scripps Pier (cold deep water
from La Jolla Canyon surging into the shallows for ~30 min). The investigation
led to a fix in `weather-board/weather.py` that switched the SST bias
calibration from a single-point delta to a median over today's hourly pairs,
so transient spikes can no longer corrupt the multi-day ocean forecast.

## Running them

From inside this folder:

```bash
python3 ljac1_year_overlay.py            # writes ljac1_year_overlay.png
python3 ljac1_year_overlay_interactive.py # writes ljac1_year_overlay.html
python3 test_calibration_delta.py         # prints simulation table
```

Requires `requests`, `matplotlib`, `plotly` — install locally with `pip3
install`. None of these dependencies are in any Dockerfile.

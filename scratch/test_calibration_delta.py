"""Simulate old vs new calibration delta during today's 7am cold-bore spike.

Builds NDBC hourly values from the LJAC1 realtime feed for today, mocks plausible
OM-modeled SST values for the same hours, and compares:
  - old:  delta = NDBC[now] - OM[now]
  - new:  delta = median(NDBC[h] - OM[h] for h in today)

Walks through each hour 0..N (where N is "now") to show how the bias would have
been different at each refresh during the spike.
"""
import os
import sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "weather-board"))

from datetime import datetime, timedelta, timezone
import requests

from weather import compute_calibration_delta


# Pull today's NDBC hourly from the live feed
def get_today_ndbc_hourly():
    r = requests.get("https://www.ndbc.noaa.gov/data/realtime2/LJAC1.txt", timeout=15)
    r.raise_for_status()
    utc_offset_hours = (datetime.now() - datetime.utcnow()).total_seconds() / 3600
    today = datetime.now().date()
    by_hour = {}
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split()
        if len(cols) < 15: continue
        try:
            yr, mo, dy, hr, mn = (int(c) for c in cols[:5])
            wtmp = cols[14]
            if wtmp in ("MM", "999.0"): continue
            wtmp_c = float(wtmp)
            if wtmp_c > 50 or wtmp_c < -5: continue
        except (ValueError, IndexError):
            continue
        sample_local = datetime(yr, mo, dy, hr, mn) + timedelta(hours=utc_offset_hours)
        if sample_local.date() != today: continue
        if sample_local.hour in by_hour: continue
        by_hour[sample_local.hour] = wtmp_c * 9 / 5 + 32
    return by_hour


def main():
    ndbc_today = get_today_ndbc_hourly()
    print("NDBC hourly (today, °F):")
    for h in sorted(ndbc_today):
        print(f"  {h:02d}:00  {ndbc_today[h]:.1f}")

    # Mock OM-modeled SST: slightly warm + smooth diurnal (typical OM behavior).
    # Real OM values for La Jolla typically 2-3°F warmer than the buoy with a
    # ~1°F diurnal swing peaking late afternoon. We use this just to demo the math.
    today_str = datetime.now().strftime("%Y-%m-%d")
    sst_by_hour = {}
    for h in range(24):
        # gentle sinusoid: 65 +/- 0.7°F, peak at 4pm
        import math
        diurnal = 0.7 * math.sin((h - 10) * math.pi / 12)
        sst_by_hour[f"{today_str}T{h:02d}:00"] = 65.0 + diurnal

    print("\nMock OM SST (typical behavior, °F):")
    for h in sorted(ndbc_today):
        print(f"  {h:02d}:00  {sst_by_hour[f'{today_str}T{h:02d}:00']:.1f}")

    # Walk through each hour, simulating a refresh that happened then
    print("\n" + "=" * 78)
    print("Simulated refresh-by-refresh: what delta would the page have used?")
    print("=" * 78)
    print(f"{'hour':>6}  {'NDBC':>6}  {'OM':>6}  "
          f"{'OLD delta':>10}  {'NEW delta':>10}  {'n':>3}  "
          f"{'OLD fc':>7}  {'NEW fc':>7}")
    print("-" * 78)
    om_typical_fc_F = 64.0  # what the multi-day forecast tile would show pre-cal

    for h in sorted(ndbc_today):
        ndbc_now = ndbc_today[h]
        om_now = sst_by_hour[f"{today_str}T{h:02d}:00"]
        partial_today = {k: v for k, v in ndbc_today.items() if k <= h}

        old_delta = ndbc_now - om_now
        new_delta, n = compute_calibration_delta(
            partial_today, sst_by_hour, today_str,
            fallback_ndbc=ndbc_now, fallback_om=om_now,
        )

        old_fc = round(om_typical_fc_F + old_delta)
        new_fc = round(om_typical_fc_F + new_delta)

        print(f"  {h:02d}:00  {ndbc_now:>5.1f}  {om_now:>5.1f}  "
              f"{old_delta:>+9.2f}  {new_delta:>+9.2f}  {n:>3}  "
              f"{old_fc:>5}°F  {new_fc:>5}°F")


if __name__ == "__main__":
    main()

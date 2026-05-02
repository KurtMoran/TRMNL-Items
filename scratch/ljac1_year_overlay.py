"""
Plot every day of LJAC1 (Scripps Pier) water temp over the last year as
overlaid lines on one chart. X = hour of day (local), Y = temp (°F).
Today's curve is highlighted.

Sources combined:
  - Annual archive   ljac1h2025.txt.gz  (May 2 2025 - Dec 31 2025)
  - Monthly archives ljac1{1,2}2026.txt.gz  (Jan + Feb 2026)
  - Realtime feed    LJAC1.txt          (last ~45 days, Mar 18 - today)
NDBC's March 2026 monthly archive isn't published yet, so ~17 days
(Mar 1-17 2026) are missing.
"""

import gzip
import io
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import requests
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable

LOCAL_OFFSET_HOURS = -7  # PDT
TODAY = date(2026, 5, 2)
ONE_YEAR_AGO = TODAY - timedelta(days=365)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(SCRIPT_DIR, "ljac1_year_overlay.png")

SOURCES = [
    ("https://www.ndbc.noaa.gov/data/historical/stdmet/ljac1h2025.txt.gz", True),
    ("https://www.ndbc.noaa.gov/data/stdmet/Jan/ljac112026.txt.gz", True),
    ("https://www.ndbc.noaa.gov/data/stdmet/Feb/ljac122026.txt.gz", True),
    ("https://www.ndbc.noaa.gov/data/realtime2/LJAC1.txt", False),
]


def fetch_text(url, gzipped):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    if gzipped:
        return gzip.decompress(r.content).decode("utf-8", errors="replace")
    return r.text


def parse_wtmp(text):
    """Yield (local_datetime, wtmp_F) for every valid WTMP sample.

    Annual/monthly archive header: YY MM DD hh mm ... WTMP at col 14
    Realtime header is the same column layout.
    """
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split()
        if len(cols) < 15:
            continue
        try:
            yr, mo, dy, hr, mn = (int(c) for c in cols[:5])
            wtmp_raw = cols[14]
        except (ValueError, IndexError):
            continue
        if wtmp_raw in ("MM", "999.0", "99.0"):
            continue
        try:
            wtmp_c = float(wtmp_raw)
        except ValueError:
            continue
        if wtmp_c < -5 or wtmp_c > 50:
            continue
        try:
            sample_utc = datetime(yr, mo, dy, hr, mn, tzinfo=timezone.utc)
        except ValueError:
            continue
        local = sample_utc + timedelta(hours=LOCAL_OFFSET_HOURS)
        wtmp_f = wtmp_c * 9 / 5 + 32
        yield local, wtmp_f


def collect_samples():
    by_day = defaultdict(list)  # date -> list of (hour_frac, temp_F)
    for url, gzipped in SOURCES:
        print(f"fetching {url}")
        text = fetch_text(url, gzipped)
        n_added = 0
        for local_dt, wtmp_f in parse_wtmp(text):
            d = local_dt.date()
            if d < ONE_YEAR_AGO or d > TODAY:
                continue
            hour_frac = local_dt.hour + local_dt.minute / 60
            by_day[d].append((hour_frac, wtmp_f))
            n_added += 1
        print(f"  +{n_added} samples")
    return by_day


def plot(by_day):
    fig, ax = plt.subplots(figsize=(13, 7), dpi=140)
    cmap = plt.get_cmap("viridis")
    norm = Normalize(vmin=0, vmax=365)

    days_sorted = sorted(by_day)
    today_xy = None
    for d in days_sorted:
        samples = sorted(by_day[d])
        if len(samples) < 4:
            continue
        xs = [s[0] for s in samples]
        ys = [s[1] for s in samples]
        if d == TODAY:
            today_xy = (xs, ys)
            continue
        days_ago = (TODAY - d).days
        color = cmap(norm(365 - days_ago))
        ax.plot(xs, ys, color=color, lw=0.6, alpha=0.35)

    if today_xy:
        ax.plot(today_xy[0], today_xy[1], color="crimson", lw=2.4,
                label=f"Today ({TODAY.isoformat()})", zorder=10)

    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xticklabels(["12a", "3a", "6a", "9a", "noon", "3p", "6p", "9p", "12a"])
    ax.set_xlabel("Hour of day (local, PDT)")
    ax.set_ylabel("Water temperature (°F)")
    ax.set_title(
        f"LJAC1 (Scripps Pier) water temp — every day from "
        f"{ONE_YEAR_AGO.isoformat()} to {TODAY.isoformat()}\n"
        f"({len(days_sorted)} days plotted; ~17 days missing in early Mar 2026 — "
        f"NDBC monthly archive not yet published)",
        fontsize=11,
    )
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right")

    sm = ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.01)
    cbar.set_label("Days ago (0 = today, 365 = one year ago)")
    cbar.set_ticks([0, 90, 180, 270, 365])
    cbar.set_ticklabels(["365", "275", "185", "95", "0"])

    fig.tight_layout()
    fig.savefig(OUT_PATH)
    print(f"\nsaved {OUT_PATH}")


if __name__ == "__main__":
    by_day = collect_samples()
    print(f"\n{len(by_day)} days collected total")
    plot(by_day)

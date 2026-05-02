"""
Interactive version of the LJAC1 year overlay.
Hover any line -> that day is bolded, others fade, tooltip shows the date.
Outputs a self-contained HTML file you can open in any browser.
"""

import gzip
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import plotly.graph_objects as go
import requests
from matplotlib import colormaps
from matplotlib.colors import Normalize, to_hex

LOCAL_OFFSET_HOURS = -7  # PDT
TODAY = date(2026, 5, 2)
ONE_YEAR_AGO = TODAY - timedelta(days=365)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(SCRIPT_DIR, "ljac1_year_overlay.html")

SOURCES = [
    ("https://www.ndbc.noaa.gov/data/historical/stdmet/ljac1h2025.txt.gz", True),
    ("https://www.ndbc.noaa.gov/data/stdmet/Jan/ljac112026.txt.gz", True),
    ("https://www.ndbc.noaa.gov/data/stdmet/Feb/ljac122026.txt.gz", True),
    ("https://www.ndbc.noaa.gov/data/realtime2/LJAC1.txt", False),
]


def fetch_text(url, gzipped):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return gzip.decompress(r.content).decode("utf-8", errors="replace") if gzipped else r.text


def parse_wtmp(text):
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
    by_day = defaultdict(list)
    for url, gzipped in SOURCES:
        print(f"fetching {url}")
        text = fetch_text(url, gzipped)
        n = 0
        for local_dt, wtmp_f in parse_wtmp(text):
            d = local_dt.date()
            if d < ONE_YEAR_AGO or d > TODAY:
                continue
            by_day[d].append((local_dt.hour + local_dt.minute / 60, wtmp_f))
            n += 1
        print(f"  +{n} samples")
    return by_day


def build_figure(by_day):
    cmap = colormaps["viridis"]
    norm = Normalize(vmin=0, vmax=365)

    days_sorted = sorted(by_day)
    fig = go.Figure()

    today_idx = None
    for i, d in enumerate(days_sorted):
        samples = sorted(by_day[d])
        if len(samples) < 4:
            continue
        xs = [s[0] for s in samples]
        ys = [round(s[1], 2) for s in samples]
        days_ago = (TODAY - d).days
        is_today = d == TODAY

        if is_today:
            today_idx = i
            color = "crimson"
            width = 3
            opacity = 1.0
        else:
            color = to_hex(cmap(norm(365 - days_ago)))
            width = 1
            opacity = 0.35

        fig.add_trace(go.Scatter(
            x=xs, y=ys,
            mode="lines",
            line=dict(color=color, width=width),
            opacity=opacity,
            name=d.isoformat(),
            customdata=[[d.isoformat(), days_ago]] * len(xs),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]} days ago<br>"
                "%{x:.2f}h - %{y:.1f}°F"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

    fig.update_layout(
        title=(
            f"LJAC1 (Scripps Pier) water temp - every day from "
            f"{ONE_YEAR_AGO.isoformat()} to {TODAY.isoformat()}<br>"
            f"<sub>{len(days_sorted)} days plotted - hover any line to highlight - "
            f"~17 days missing in early Mar 2026 (NDBC archive not yet published); "
            f"Feb 2026 was a sensor outage</sub>"
        ),
        xaxis=dict(
            title="Hour of day (local, PDT)",
            tickmode="array",
            tickvals=list(range(0, 25, 3)),
            ticktext=["12a", "3a", "6a", "9a", "noon", "3p", "6p", "9p", "12a"],
            range=[0, 24],
            gridcolor="rgba(0,0,0,0.08)",
        ),
        yaxis=dict(
            title="Water temperature (°F)",
            gridcolor="rgba(0,0,0,0.08)",
        ),
        plot_bgcolor="white",
        hovermode="closest",
        width=1300,
        height=720,
        margin=dict(l=70, r=40, t=90, b=60),
    )

    return fig, today_idx


def write_html(fig, today_idx):
    # JS that runs after Plotly renders. On hover, we restyle:
    #   - hovered trace: width=4, opacity=1
    #   - all others: opacity=0.05
    # On unhover, restore original styles (we cache them per trace).
    post_js = f"""
    var gd = document.querySelectorAll('.plotly-graph-div')[0];
    var origLineWidth = gd.data.map(function(t){{ return t.line.width; }});
    var origOpacity = gd.data.map(function(t){{ return t.opacity; }});
    var todayIdx = {today_idx if today_idx is not None else "null"};

    gd.on('plotly_hover', function(ev) {{
      if (!ev.points || !ev.points.length) return;
      var hi = ev.points[0].curveNumber;
      var widths = origLineWidth.slice();
      var opacities = origOpacity.map(function(o, i) {{
        if (i === hi) return 1.0;
        if (i === todayIdx) return 0.6;
        return 0.05;
      }});
      widths[hi] = 4;
      Plotly.restyle(gd, {{'line.width': widths, 'opacity': opacities}});
    }});

    gd.on('plotly_unhover', function() {{
      Plotly.restyle(gd, {{'line.width': origLineWidth, 'opacity': origOpacity}});
    }});
    """

    fig.write_html(
        OUT_PATH,
        include_plotlyjs="cdn",
        post_script=post_js,
        full_html=True,
    )
    print(f"\nsaved {OUT_PATH}")


if __name__ == "__main__":
    by_day = collect_samples()
    print(f"\n{len(by_day)} days collected total")
    fig, today_idx = build_figure(by_day)
    write_html(fig, today_idx)

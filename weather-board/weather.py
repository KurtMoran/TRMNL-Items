#!/usr/bin/env python3
"""Weather Board for TRMNL e-ink display.

Polls Open-Meteo Forecast + Marine APIs every 15 minutes and pushes
today's weather, ocean conditions, and 3-day forecast to a TRMNL
display via webhook.
"""
import json, logging, os, threading, time
from datetime import datetime, timedelta
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("weather-board")

WEATHER_LAT = float(os.getenv("WEATHER_LAT", "32.78377629393423"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "-117.11162158373665"))
LOCATION_NAME = os.getenv("LOCATION_NAME", "San Diego")
OCEAN_LAT = float(os.getenv("OCEAN_LAT", "32.85407591442029"))
OCEAN_LON = float(os.getenv("OCEAN_LON", "-117.26182783426711"))
OCEAN_NAME = os.getenv("OCEAN_NAME", "Ocean")
SAME_THRESHOLD = int(os.getenv("SAME_THRESHOLD", "1"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "900"))
TZ_NAME = os.getenv("TZ", "America/Los_Angeles")
TRMNL_WEBHOOK_UUID = os.getenv("TRMNL_WEBHOOK_UUID", "")
TRMNL_API_URL = "https://trmnl.com/api/custom_plugins"
DATA_FILE = os.getenv("DATA_FILE", "/data/weather_state.json")
TIDE_STATION_ID = os.getenv("TIDE_STATION_ID", "9410230")  # NOAA La Jolla (Scripps Pier)
NDBC_STATION = os.getenv("NDBC_STATION", "LJAC1")  # NDBC Scripps Pier sensor (water temp)
NDBC_URL = "https://www.ndbc.noaa.gov/data/realtime2/{}.txt".format(NDBC_STATION)

# Launch Library 2 (free) — refreshed on a background thread so timing is fully
# decoupled from POLL_INTERVAL_SEC. Free unauthenticated tier: ~15 req/hour.
# Default 480s = 7.5 calls/hour (~50% of free tier). Cache file persists across
# container restarts so a restart never burns extra budget.
LAUNCH_CACHE_FILE = os.getenv("LAUNCH_CACHE_FILE", "/data/launches_cache.json")
LAUNCH_REFRESH_SEC = int(os.getenv("LAUNCH_REFRESH_SEC", "480"))
LL2_LOCATION_IDS = os.getenv("LL2_LOCATION_IDS", "11")  # 11 = Vandenberg SFB
LL2_API_KEY = os.getenv("LL2_API_KEY", "")  # optional; lifts rate limit when set
LAUNCH_LOCATION_LABEL = os.getenv("LAUNCH_LOCATION_LABEL", "Vandenberg")

FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
    "wind_speed_10m,wind_direction_10m,weather_code"
    "&daily=temperature_2m_max,temperature_2m_min,weather_code,sunrise,sunset,"
    "uv_index_max,precipitation_probability_max"
    "&temperature_unit=fahrenheit&wind_speed_unit=mph"
    "&timezone={tz}&past_days=1&forecast_days=4"
).format(lat=WEATHER_LAT, lon=WEATHER_LON, tz=TZ_NAME)

MARINE_URL = (
    "https://marine-api.open-meteo.com/v1/marine"
    "?latitude={lat}&longitude={lon}"
    "&hourly=sea_surface_temperature,swell_wave_height,swell_wave_period"
    "&daily=wave_height_max,wave_period_max,wave_direction_dominant,"
    "swell_wave_height_max,swell_wave_period_max,swell_wave_direction_dominant"
    "&temperature_unit=fahrenheit&length_unit=imperial"
    "&timezone={tz}&forecast_days=4"
).format(lat=OCEAN_LAT, lon=OCEAN_LON, tz=TZ_NAME)

AIR_QUALITY_URL = (
    "https://air-quality-api.open-meteo.com/v1/air-quality"
    "?latitude={lat}&longitude={lon}"
    "&current=us_aqi"
    "&timezone={tz}"
).format(lat=WEATHER_LAT, lon=WEATHER_LON, tz=TZ_NAME)


def wmo_to_icon(code):
    """Map WMO weather code to a template icon key."""
    if code is None:
        return "cloud"
    code = int(code)
    if code == 0:
        return "sun"
    if code == 1:
        return "sun-cloud"
    if code == 2:
        return "partly-cloudy"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "cloud"


def wmo_to_phrase(code):
    if code is None:
        return ""
    code = int(code)
    return {
        0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Foggy",
        51: "Light drizzle", 53: "Drizzle", 55: "Drizzle",
        56: "Freezing drizzle", 57: "Freezing drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain",
        66: "Freezing rain", 67: "Freezing rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
        80: "Showers", 81: "Showers", 82: "Heavy showers",
        85: "Snow showers", 86: "Snow showers",
        95: "Thunderstorm", 96: "Storm + hail", 99: "Severe storm",
    }.get(code, "")


def cardinal(deg):
    if deg is None:
        return ""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[round(deg / 22.5) % 16]


def energy_tier(kj):
    """Map kJ to a 1-5 tier matching surf-forecast.com's energy guide:
    <100 flat, 100-200 surfable, 200-1000 punchy,
    1000-5000 heavy, 5000+ dangerous. 0 = no data."""
    if not isinstance(kj, (int, float)):
        return 0
    if kj < 100:
        return 1
    if kj < 200:
        return 2
    if kj < 1000:
        return 3
    if kj < 5000:
        return 4
    return 5


def fmt_delta(d):
    """3 -> '+3°', -1 -> '-1°', 0 -> '0°'."""
    if not isinstance(d, int):
        return ""
    return "{:+d}°".format(d) if d != 0 else "0°"


def swell_energy_at(dt, swell_by_hour):
    """Returns (swell_str, energy_str, energy_tier_int) for the given datetime,
    using the closest hourly swell sample. Empty strings + 0 tier if missing.
    swell_by_hour maps 'YYYY-MM-DDTHH:00' -> (height_ft, period_s)."""
    if dt is None or not swell_by_hour:
        return "", "", 0
    key = dt.strftime("%Y-%m-%dT%H:00")
    sample = swell_by_hour.get(key)
    if sample is None:
        return "", "", 0
    h_ft, t_s = sample
    if not isinstance(h_ft, (int, float)) or not isinstance(t_s, (int, float)):
        return "", "", 0
    h_m = h_ft * 0.3048
    kj = round(1.96 * h_m * h_m * t_s * t_s)
    return ("{}ft {}s".format(round(h_ft), round(t_s)),
            "{} kJ".format(kj), energy_tier(kj))


def tide_url():
    """NOAA CO-OPS predictions URL covering today + tomorrow."""
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    return (
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        "?product=predictions"
        "&application=trmnl-weather"
        "&begin_date={start}"
        "&end_date={end}"
        "&datum=MLLW"
        "&station={station}"
        "&time_zone=lst_ldt"
        "&units=english"
        "&interval=hilo"
        "&format=json"
    ).format(
        start=today.strftime("%Y%m%d"),
        end=tomorrow.strftime("%Y%m%d"),
        station=TIDE_STATION_ID,
    )


def fmt_time(iso_str):
    """ISO datetime ('2026-04-29T06:12') -> '6:12a'."""
    if not iso_str:
        return "--"
    try:
        dt = datetime.fromisoformat(iso_str)
        h, m = dt.hour, dt.minute
        if h == 0:
            return "12:{:02d}a".format(m)
        if h < 12:
            return "{}:{:02d}a".format(h, m)
        if h == 12:
            return "12:{:02d}p".format(m)
        return "{}:{:02d}p".format(h - 12, m)
    except Exception:
        return "--"


def day_label(iso_date):
    """'2026-05-01' -> 'THU'."""
    try:
        return datetime.fromisoformat(iso_date).strftime("%a").upper()
    except Exception:
        return "---"


def fetch_json(url, name):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error("%s fetch failed: %s", name, e)
        return None


def fetch_ndbc():
    """Returns (current_wtmp_F_or_None, hourly_today: dict {hour_int: temp_F_float}).
    Hourly values are kept as floats (~0.18°F precision) so the curve renders smoothly.
    NDBC realtime2 reports UTC; we convert to local time for the today-curve.
    """
    hourly_today = {}
    current = None
    try:
        resp = requests.get(NDBC_URL, timeout=15)
        resp.raise_for_status()
        local_today = datetime.now().date()
        utc_offset_hours = datetime.now().astimezone().utcoffset().total_seconds() / 3600
        for line in resp.text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            cols = line.split()
            if len(cols) < 15:
                continue
            try:
                yr, mo, dy, hr, mn = (int(c) for c in cols[:5])
                wtmp = cols[14]
                if wtmp in ("MM", "999.0"):
                    continue
                wtmp_c = float(wtmp)
                if wtmp_c > 50 or wtmp_c < -5:
                    continue
                wtmp_f = wtmp_c * 9 / 5 + 32
                if current is None:
                    current = round(wtmp_f)  # display value is rounded
                sample_utc = datetime(yr, mo, dy, hr, mn)
                sample_local = sample_utc + timedelta(hours=utc_offset_hours)
                if sample_local.date() == local_today and sample_local.hour not in hourly_today:
                    hourly_today[sample_local.hour] = wtmp_f  # keep float for curve
            except (ValueError, IndexError):
                continue
    except Exception as e:
        log.error("NDBC %s fetch failed: %s", NDBC_STATION, e)
    return current, hourly_today


def fetch_ndbc_wtmp():
    """Backward-compatible wrapper — returns just the current reading."""
    return fetch_ndbc()[0]


def safe_round(v):
    return round(v) if isinstance(v, (int, float)) else "--"


def _hour_label(h):
    """0..23 -> '12am' / '4pm' etc."""
    if h == 0: return "12am"
    if h < 12: return "{}am".format(h)
    if h == 12: return "12pm"
    return "{}pm".format(h - 12)


# SVG dimensions for the today-water-curve sparkline.
WATER_CURVE_W, WATER_CURVE_H = 380, 50


def _iso_to_curve_x(iso_str):
    """ISO datetime '2026-05-02T05:55' -> x position on the 24h water curve.
    Returns int — sub-pixel precision is invisible on a 380px-wide e-ink chart."""
    try:
        dt = datetime.fromisoformat(iso_str)
        hour_frac = dt.hour + dt.minute / 60
        return round(hour_frac / 24 * WATER_CURVE_W)
    except Exception:
        return None


def _curve_geometry(series, now, w, h, pad):
    """Returns (points, now_x, now_y, hi_temp, hi_hour) from {hour: temp}.
    All coordinates rounded to ints to keep the TRMNL payload under 2 KB."""
    hours = sorted(series)
    temps = [series[k] for k in hours]
    t_min, t_max = min(temps), max(temps)
    span = max(t_max - t_min, 1)

    def x_of(k): return round(k / 24 * w)
    def y_of(t): return round(h - pad - (t - t_min) / span * (h - 2 * pad))
    points = " ".join("{},{}".format(x_of(k), y_of(series[k])) for k in hours)

    cur_hour = now.hour + now.minute / 60
    now_x = round(min(max(cur_hour / 24 * w, 0), w))
    now_y = _interp_curve_y(series, cur_hour, w, h, pad)
    hi_hour = hours[temps.index(t_max)]
    return points, now_x, now_y, t_max, hi_hour


def _interp_curve_y(series, hour_frac, w, h, pad):
    """Linear interpolation of the SVG curve y-value at a fractional hour."""
    if not series:
        return None
    hours = sorted(series)
    temps = [series[k] for k in hours]
    t_min, t_max = min(temps), max(temps)
    span = max(t_max - t_min, 1)
    if hour_frac <= hours[0]:
        t = temps[0]
    elif hour_frac >= hours[-1]:
        t = temps[-1]
    else:
        for i in range(1, len(hours)):
            if hours[i] >= hour_frac:
                lo, hi_h = hours[i - 1], hours[i]
                frac = (hour_frac - lo) / (hi_h - lo)
                t = temps[i - 1] + (temps[i] - temps[i - 1]) * frac
                break
    return round(h - pad - (t - t_min) / span * (h - 2 * pad))


def _sunset_marker_y(curve_y):
    """Sunset sits at chart bottom, nudged down if curve dips so it never overlaps."""
    default_y, cap_y = 44, 48
    if curve_y is None:
        return default_y
    return max(default_y, min(curve_y + 6, cap_y))


SUNRISE_MARKER_Y = 4  # always at the top of the chart


_launch_lock = threading.Lock()


def _load_launch_cache():
    with _launch_lock:
        try:
            with open(LAUNCH_CACHE_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}


def _save_launch_cache(cache):
    with _launch_lock:
        try:
            os.makedirs(os.path.dirname(LAUNCH_CACHE_FILE), exist_ok=True)
            with open(LAUNCH_CACHE_FILE, "w") as f:
                json.dump(cache, f)
        except Exception as e:
            log.warning("Could not save launch cache: %s", e)


def launch_refresh_loop():
    """Background thread — keeps the launch cache fresh on its own clock,
    independent of the TRMNL poll interval. The main loop just reads cache."""
    while True:
        time.sleep(LAUNCH_REFRESH_SEC)
        try:
            fetch_launches_smart(datetime.now())
        except Exception as e:
            log.error("Launch refresh thread failed: %s", e)


def fetch_launches_smart(now):
    """Returns today's Vandenberg launches in local (Pacific) time.

    Cache file persists across container restarts. Refresh is gated by
    LAUNCH_REFRESH_SEC AND a date-key match — so changing POLL_INTERVAL_SEC
    later does NOT change how often we hit Launch Library 2. Default 6h
    refresh = 4 API calls/day, well under the 15 req/hour free tier.
    """
    today_key = now.date().isoformat()
    cache = _load_launch_cache()
    fetched_at = None
    if cache.get("fetched_at"):
        try:
            fetched_at = datetime.fromisoformat(cache["fetched_at"])
        except ValueError:
            fetched_at = None

    cache_fresh = (
        cache.get("date_key") == today_key
        and fetched_at is not None
        and (now - fetched_at).total_seconds() < LAUNCH_REFRESH_SEC
    )
    if cache_fresh:
        age = int((now - fetched_at).total_seconds())
        log.info("Launches: using cache (%ds old, %d entries)",
                 age, len(cache.get("launches", [])))
        return cache.get("launches", [])

    # Pad the UTC window by ±1 day so launches near local midnight aren't missed
    # by the timezone shift.
    win_start = (now.date() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    win_end = (now.date() + timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
    url = (
        "https://ll.thespacedevs.com/2.3.0/launches/"
        "?location__ids={loc}&net__gte={start}&net__lt={end}&limit=20&mode=normal"
    ).format(loc=LL2_LOCATION_IDS, start=win_start, end=win_end)
    headers = {"User-Agent": "trmnl-weather-board/1.0"}
    if LL2_API_KEY:
        headers["Authorization"] = "Token {}".format(LL2_API_KEY)

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 429:
            log.warning("Launch Library 2 rate-limited; keeping stale cache")
            return cache.get("launches", []) if cache.get("date_key") == today_key else []
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("Launch Library 2 fetch failed: %s", e)
        return cache.get("launches", []) if cache.get("date_key") == today_key else []

    utc_offset_hours = datetime.now().astimezone().utcoffset().total_seconds() / 3600
    launches = []
    for r in data.get("results", []):
        net_iso = r.get("net")
        if not net_iso:
            continue
        try:
            net_utc = datetime.fromisoformat(net_iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        net_local = (net_utc + timedelta(hours=utc_offset_hours)).replace(tzinfo=None)
        if net_local.date() != now.date():
            continue
        rocket_obj = r.get("rocket") or {}
        config = rocket_obj.get("configuration") or {}
        mission_obj = r.get("mission") or {}
        pad_obj = r.get("pad") or {}
        status_obj = r.get("status") or {}
        launches.append({
            "name": r.get("name", ""),
            "net_local": net_local.isoformat(),
            "rocket": config.get("name", ""),
            "mission": mission_obj.get("name", "") or "",
            "pad": pad_obj.get("name", "") or "",
            "status": status_obj.get("abbrev", "") or "",
        })

    _save_launch_cache({
        "date_key": today_key,
        "fetched_at": now.isoformat(),
        "launches": launches,
    })
    log.info("Launches: fetched %d for %s from Vandenberg (next refresh in %dh)",
             len(launches), today_key, LAUNCH_REFRESH_SEC // 3600)
    return launches


def pick_todays_launch(launches, now):
    """Returns (net_local_dt, launch_dict) for the next launch today, or — if all
    of today's launches have already happened — the most recent one. None if no
    launches today."""
    items = []
    for L in launches:
        try:
            dt = datetime.fromisoformat(L["net_local"])
        except (KeyError, ValueError):
            continue
        items.append((dt, L))
    if not items:
        return None
    items.sort(key=lambda x: x[0])
    for dt, L in items:
        if dt >= now:
            return dt, L
    return items[-1]


def shorten_pad(pad_name):
    """'Space Launch Complex 4E' -> 'SLC-4E'. Other formats pass through."""
    if not pad_name:
        return ""
    p = pad_name.strip()
    low = p.lower()
    if low.startswith("space launch complex"):
        rest = p[len("Space Launch Complex"):].strip()
        return "SLC-{}".format(rest) if rest else "SLC"
    return p


def build_launch_fields(now, launches):
    """Returns merge-var dict for a launch happening today, or zeros/blanks if none."""
    fields = {
        "has_launch": False,
        "launch_x": None,
        "launch_time_str": "",
        "launch_what": "",
        "launch_where": "",
    }
    pick = pick_todays_launch(launches, now)
    if not pick:
        return fields
    net_dt, L = pick
    rocket = L.get("rocket", "")
    mission = (L.get("mission") or "").strip()
    pad_short = shorten_pad(L.get("pad", ""))
    name = L.get("name", "")

    # "Falcon 9 / Starlink 9-3" if both present, else fall back to launch name
    if rocket and mission:
        what = "{} / {}".format(rocket, mission)
    elif rocket:
        what = rocket
    else:
        what = name or "Launch"

    where = LAUNCH_LOCATION_LABEL
    if pad_short:
        where = "{} {}".format(LAUNCH_LOCATION_LABEL, pad_short)

    hour_frac = net_dt.hour + net_dt.minute / 60
    raw_x = hour_frac / 24 * WATER_CURVE_W
    # Clamp so the ~8px-wide rocket glyph and its fins never clip the chart edge.
    clamped_x = min(max(raw_x, 5), WATER_CURVE_W - 5)
    fields.update({
        "has_launch": True,
        "launch_x": round(clamped_x, 1),
        "launch_time_str": fmt_time(net_dt.isoformat()),
        "launch_what": what,
        "launch_where": where,
    })
    return fields


def compute_calibration_delta(ndbc_today_hourly, sst_by_hour, today_str,
                               fallback_ndbc, fallback_om):
    """Median of today's hourly (NDBC - OM) pairs, in °F.

    Pairs each NDBC hourly sample with OM's modeled SST for the same wall-clock
    hour and returns the median difference. Robust to single-hour outliers from
    internal-bore events at Scripps Pier (5-7°F transients that recover within
    an hour). Falls back to the single-point delta if fewer than 3 pairs.

    Returns (delta_F, n_pairs).
    """
    diffs = []
    for hour_int, ndbc_f in ndbc_today_hourly.items():
        om_f = sst_by_hour.get("{}T{:02d}:00".format(today_str, hour_int))
        if om_f is None:
            continue
        diffs.append(ndbc_f - om_f)
    if len(diffs) >= 3:
        diffs.sort()
        n = len(diffs)
        median = diffs[n // 2] if n % 2 == 1 else (diffs[n // 2 - 1] + diffs[n // 2]) / 2
        return median, n
    if fallback_ndbc is not None and fallback_om is not None:
        return fallback_ndbc - fallback_om, len(diffs)
    return 0, len(diffs)


def build_today_curve(now, ndbc_hourly, om_hourly, delta, sunrise_x=None, sunset_x=None,
                       launch_x=None):
    """Calibrated OM forecast across the full 24-hour day. NDBC samples are
    still used upstream to compute `delta`, but the curve itself stays smooth
    by avoiding the spikey raw sensor values. Returns dict of payload fields,
    or {} if no data."""
    today_str = now.strftime("%Y-%m-%d")
    series = {}
    for k in range(24):
        om = om_hourly.get("{}T{:02d}:00".format(today_str, k))
        if om is not None:
            series[k] = om + delta  # float, no rounding
    if not series:
        return {}
    points, nx, ny, hi_t, hi_h = _curve_geometry(series, now, WATER_CURVE_W, WATER_CURVE_H, pad=4)

    # Interpolate curve y at sunrise/sunset, then compute where the sun glyph sits.
    def y_at_x(x):
        if x is None:
            return None
        return _interp_curve_y(series, x / WATER_CURVE_W * 24,
                               WATER_CURVE_W, WATER_CURVE_H, pad=4)

    sunrise_y_curve = y_at_x(sunrise_x)
    sunset_y_curve = y_at_x(sunset_x)
    launch_y_curve = y_at_x(launch_x)

    return {
        "today_curve_points": points,
        "today_hi": round(hi_t), "today_hi_time": _hour_label(hi_h),
        "today_now_x": nx, "today_now_y": ny,
        "sunrise_y_curve": sunrise_y_curve,
        "sunset_y_curve": sunset_y_curve,
        "sunrise_sun_y": SUNRISE_MARKER_Y,
        "sunset_sun_y": _sunset_marker_y(sunset_y_curve),
        "launch_y_curve": launch_y_curve,
    }


def build_payload():
    forecast = fetch_json(FORECAST_URL, "Forecast")
    marine = fetch_json(MARINE_URL, "Marine")
    now = datetime.now()

    p = {
        "loc": LOCATION_NAME,
        "ocean_loc": OCEAN_NAME,
        "date": now.strftime("%A, %B %d"),
        "updated": now.strftime("%-I:%M %p"),
        "hi": "--", "lo": "--", "icon": "cloud", "phrase": "",
        "delta": "", "tdelta": "", "feels": "--",
        "wind": "--", "humid": "--", "uv": "--", "rain": "--",
        "rise": "--", "set": "--", "forecast": [],
        "ocean": "--",
        "ocean_forecast": [],
        "aqi": "--",
        "tide1_arrow": "", "tide1_time": "--", "tide1_height": "",
        "tide1_swell": "", "tide1_energy": "", "tide1_energy_tier": 0,
        "tide2_arrow": "", "tide2_time": "--", "tide2_height": "",
        "tide2_swell": "", "tide2_energy": "", "tide2_energy_tier": 0,
        "today_curve_points": "", "today_hi": "--", "today_hi_time": "--",
        "today_now_x": 0, "today_now_y": 0,
        "today_tides": [],
        "sunrise_x": None, "sunset_x": None,
        "sunrise_y_curve": None, "sunset_y_curve": None,
        "sunrise_sun_y": 4, "sunset_sun_y": 44,
        "has_launch": False, "launch_x": None, "launch_y_curve": None,
        "launch_time_str": "", "launch_what": "", "launch_where": "",
    }

    launches_today = fetch_launches_smart(now)
    p.update(build_launch_fields(now, launches_today))

    if forecast:
        daily = forecast.get("daily", {})
        current = forecast.get("current", {})
        time_arr = daily.get("time", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        wcodes = daily.get("weather_code", [])
        sunrise = daily.get("sunrise", [])
        sunset = daily.get("sunset", [])
        uv_max = daily.get("uv_index_max", [])
        pop = daily.get("precipitation_probability_max", [])

        # Index 0 = yesterday (past_days=1), 1 = today, 2..4 = next 3 days
        if len(temp_max) >= 2:
            yest_hi = temp_max[0]
            today_hi = temp_max[1]
            today_lo = temp_min[1]
            today_code = wcodes[1] if len(wcodes) > 1 else None

            p["hi"] = safe_round(today_hi)
            p["lo"] = safe_round(today_lo)
            p["icon"] = wmo_to_icon(today_code)
            p["phrase"] = wmo_to_phrase(today_code)

            if isinstance(yest_hi, (int, float)) and isinstance(today_hi, (int, float)):
                delta = round(today_hi) - round(yest_hi)
                if abs(delta) <= SAME_THRESHOLD:
                    p["delta"] = "Same as yesterday"
                elif delta > 0:
                    p["delta"] = "{}° warmer than yesterday".format(delta)
                else:
                    p["delta"] = "{}° cooler than yesterday".format(abs(delta))

            if len(temp_max) >= 3 and isinstance(temp_max[2], (int, float)) and isinstance(today_hi, (int, float)):
                tdelta = round(temp_max[2]) - round(today_hi)
                if abs(tdelta) <= SAME_THRESHOLD:
                    p["tdelta"] = "Tomorrow about the same"
                elif tdelta > 0:
                    p["tdelta"] = "Tomorrow {}° warmer".format(tdelta)
                else:
                    p["tdelta"] = "Tomorrow {}° cooler".format(abs(tdelta))

            p["feels"] = safe_round(current.get("apparent_temperature"))

        wind_spd = current.get("wind_speed_10m")
        wind_dir = current.get("wind_direction_10m")
        if isinstance(wind_spd, (int, float)):
            p["wind"] = "{} mph {}".format(round(wind_spd), cardinal(wind_dir)).strip()

        humidity = current.get("relative_humidity_2m")
        if isinstance(humidity, (int, float)):
            p["humid"] = "{}%".format(round(humidity))

        if len(uv_max) > 1 and isinstance(uv_max[1], (int, float)):
            p["uv"] = round(uv_max[1])

        if len(pop) > 1 and isinstance(pop[1], (int, float)):
            p["rain"] = "{}%".format(round(pop[1]))

        if len(sunrise) > 1:
            p["rise"] = fmt_time(sunrise[1])
            p["sunrise_x"] = _iso_to_curve_x(sunrise[1])
        if len(sunset) > 1:
            p["set"] = fmt_time(sunset[1])
            p["sunset_x"] = _iso_to_curve_x(sunset[1])

        forecast_days = []
        for i in range(2, 5):
            if i < len(temp_max) and i < len(time_arr):
                d_hi = temp_max[i]
                delta_str = ""
                if isinstance(d_hi, (int, float)) and isinstance(today_hi, (int, float)):
                    delta_str = fmt_delta(round(d_hi) - round(today_hi))
                forecast_days.append({
                    "day": day_label(time_arr[i]),
                    "icon": wmo_to_icon(wcodes[i] if i < len(wcodes) else None),
                    "hi": safe_round(d_hi),
                    "lo": safe_round(temp_min[i]),
                    "delta": delta_str,
                })
        p["forecast"] = forecast_days

    om_now_sst = None  # OM's prediction for the current hour — for calibration
    sst_by_hour = {}
    swell_by_hour = {}  # 'YYYY-MM-DDTHH:00' -> (height_ft, period_s)
    if marine:
        m_daily = marine.get("daily", {})
        m_hourly = marine.get("hourly", {})

        # Index hourly SST by ISO timestamp so we can look up the current hour;
        # also build per-day max for the forecast cards.
        sst_by_day = {}
        for ts, t in zip(m_hourly.get("time", []),
                          m_hourly.get("sea_surface_temperature", [])):
            if t is None or "T" not in ts:
                continue
            sst_by_hour[ts] = t
            d = ts.split("T")[0]
            if d not in sst_by_day or t > sst_by_day[d]:
                sst_by_day[d] = t

        for ts, h, t_s in zip(m_hourly.get("time", []),
                               m_hourly.get("swell_wave_height", []),
                               m_hourly.get("swell_wave_period", [])):
            if h is None or t_s is None or "T" not in ts:
                continue
            swell_by_hour[ts] = (h, t_s)

        now_hour_key = now.strftime("%Y-%m-%dT%H:00")
        om_now_sst = sst_by_hour.get(now_hour_key)

        today_str = now.strftime("%Y-%m-%d")
        om_today_sst = sst_by_day.get(today_str)
        if om_today_sst is not None:
            p["ocean"] = round(om_today_sst)

        m_time = m_daily.get("time", [])
        sh_arr = m_daily.get("swell_wave_height_max", [])
        st_arr = m_daily.get("swell_wave_period_max", [])
        ocean_fc = []
        for i in range(1, 4):
            if i < len(sh_arr) and i < len(st_arr) and i < len(m_time):
                h = sh_arr[i]
                t = st_arr[i]
                date = m_time[i]
                if isinstance(h, (int, float)) and isinstance(t, (int, float)):
                    h_m_i = h * 0.3048
                    kj_i = round(1.96 * h_m_i * h_m_i * t * t)
                    day_temp = sst_by_day.get(date)
                    ocean_fc.append({
                        "day": day_label(date),
                        "ocean": round(day_temp) if day_temp is not None else "--",
                        "swell": "{}ft {}s".format(round(h), round(t)),
                        "energy": "{} kJ".format(kj_i),
                        "energy_tier": energy_tier(kj_i),
                    })
        p["ocean_forecast"] = ocean_fc

    # Prefer the NDBC sensor reading at Scripps Pier over Open-Meteo's modeled SST.
    # Also calibrate the forecast: Open-Meteo's offshore-modeled SST runs ~2-4°F warm
    # vs the nearshore buoy in summer/fall (upwelling). The bias is the median of
    # today's hourly (NDBC - OM) pairs — a single-point delta would get poisoned by
    # internal-bore spikes at Scripps Pier (5-7°F drops that recover within an hour).
    ndbc_wtmp, ndbc_today_hourly = fetch_ndbc()
    delta = 0
    if ndbc_wtmp is not None:
        p["ocean"] = ndbc_wtmp
        if om_now_sst is not None:
            delta, n_pairs = compute_calibration_delta(
                ndbc_today_hourly, sst_by_hour, today_str,
                fallback_ndbc=ndbc_wtmp, fallback_om=om_now_sst,
            )
            log.info("SST calibration delta=%+.2f°F (n=%d paired hours)",
                     delta, n_pairs)
            for day in p["ocean_forecast"]:
                if isinstance(day.get("ocean"), (int, float)):
                    day["ocean"] = round(day["ocean"] + delta)

    # Today's water-temp curve: NDBC actuals for past hours, calibrated OM for future.
    today_curve = build_today_curve(
        now, ndbc_today_hourly, sst_by_hour, delta,
        sunrise_x=p.get("sunrise_x"), sunset_x=p.get("sunset_x"),
        launch_x=p.get("launch_x"),
    )
    if today_curve:
        p.update(today_curve)

    aqi_data = fetch_json(AIR_QUALITY_URL, "AirQuality")
    if aqi_data:
        us_aqi = aqi_data.get("current", {}).get("us_aqi")
        if isinstance(us_aqi, (int, float)):
            p["aqi"] = round(us_aqi)

    tide_data = fetch_json(tide_url(), "Tides")
    if tide_data:
        next_high = None
        next_low = None
        today_date = now.date()
        today_tides = []  # markers for the today-water curve
        for pred in tide_data.get("predictions", []):
            try:
                t_dt = datetime.strptime(pred["t"], "%Y-%m-%d %H:%M")
            except (ValueError, KeyError):
                continue
            kind = pred.get("type", "")
            # Collect today's tide events for the curve markers (only x and type
            # are used by the template — drop the human-readable label to save bytes)
            if t_dt.date() == today_date and kind in ("H", "L"):
                hour_frac = t_dt.hour + t_dt.minute / 60
                today_tides.append({
                    "x": round(hour_frac / 24 * WATER_CURVE_W),
                    "type": kind,
                })
            # Tide widget shows the next high/low after now
            if t_dt <= now:
                continue
            try:
                height = float(pred.get("v", 0))
            except (TypeError, ValueError):
                height = 0.0
            if kind == "H" and next_high is None:
                next_high = (t_dt, height)
            elif kind == "L" and next_low is None:
                next_low = (t_dt, height)

        # Order the next high/low by time so the soonest event renders first.
        events = []
        if next_high:
            events.append(("↑", next_high[0], next_high[1]))
        if next_low:
            events.append(("↓", next_low[0], next_low[1]))
        events.sort(key=lambda e: e[1])
        for slot, ev in zip(("tide1", "tide2"), events):
            arrow, t_dt, height = ev
            p["{}_arrow".format(slot)] = arrow
            p["{}_time".format(slot)] = fmt_time(t_dt.isoformat())
            p["{}_height".format(slot)] = "{:.1f}ft".format(height)
            sw, en, tier = swell_energy_at(t_dt, swell_by_hour)
            p["{}_swell".format(slot)] = sw
            p["{}_energy".format(slot)] = en
            p["{}_energy_tier".format(slot)] = tier
        p["today_tides"] = today_tides

    return {"merge_variables": p}


def push_to_trmnl(payload):
    if not TRMNL_WEBHOOK_UUID:
        log.info("No TRMNL webhook configured, skipping push")
        return
    url = "{}/{}".format(TRMNL_API_URL, TRMNL_WEBHOOK_UUID)
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            log.info("TRMNL updated successfully")
        elif resp.status_code == 429:
            log.warning("TRMNL rate limited, will retry next cycle")
        else:
            log.warning("TRMNL push returned %d: %s", resp.status_code, resp.text)
    except Exception as e:
        log.error("TRMNL push failed: %s", e)


def save_state(payload):
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        log.warning("Could not save state: %s", e)


def main():
    log.info("Starting Weather Board for %s + %s", LOCATION_NAME, OCEAN_NAME)
    log.info("Polling every %ds", POLL_INTERVAL_SEC)
    log.info("Launch refresh every %ds (~%.1f calls/hour)",
             LAUNCH_REFRESH_SEC, 3600 / LAUNCH_REFRESH_SEC)
    if TRMNL_WEBHOOK_UUID:
        log.info("TRMNL webhook configured")
    else:
        log.info("No TRMNL webhook - console only mode")
    threading.Thread(target=launch_refresh_loop, daemon=True,
                     name="launch-refresh").start()
    while True:
        payload = build_payload()
        mv = payload["merge_variables"]
        log.info("Today: %s°/%s° %s | Ocean %s°F",
                 mv.get("hi"), mv.get("lo"), mv.get("phrase"), mv.get("ocean"))
        if mv.get("has_launch"):
            log.info("Launch today: %s %s @ %s",
                     mv.get("launch_what"), mv.get("launch_where"),
                     mv.get("launch_time_str"))
        push_to_trmnl(payload)
        save_state(payload)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()

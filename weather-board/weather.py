#!/usr/bin/env python3
"""Weather Board for TRMNL e-ink display.

Polls Open-Meteo Forecast + Marine APIs every 15 minutes and pushes
today's weather, ocean conditions, and 3-day forecast to a TRMNL
display via webhook.
"""
import json, logging, os, time
from datetime import datetime
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("weather-board")

WEATHER_LAT = float(os.getenv("WEATHER_LAT", "32.78377629393423"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "-117.11162158373665"))
LOCATION_NAME = os.getenv("LOCATION_NAME", "San Diego")
OCEAN_LAT = float(os.getenv("OCEAN_LAT", "32.85407591442029"))
OCEAN_LON = float(os.getenv("OCEAN_LON", "-117.26182783426711"))
OCEAN_NAME = os.getenv("OCEAN_NAME", "La Jolla Shores")
SAME_THRESHOLD = int(os.getenv("SAME_THRESHOLD", "1"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "900"))
TZ_NAME = os.getenv("TZ", "America/Los_Angeles")
TRMNL_WEBHOOK_UUID = os.getenv("TRMNL_WEBHOOK_UUID", "")
TRMNL_API_URL = "https://trmnl.com/api/custom_plugins"
DATA_FILE = os.getenv("DATA_FILE", "/data/weather_state.json")

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
    "&hourly=sea_surface_temperature"
    "&daily=wave_height_max,wave_period_max,wave_direction_dominant,"
    "swell_wave_height_max,swell_wave_period_max,swell_wave_direction_dominant"
    "&temperature_unit=fahrenheit&length_unit=imperial"
    "&timezone={tz}&forecast_days=4"
).format(lat=OCEAN_LAT, lon=OCEAN_LON, tz=TZ_NAME)


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


def safe_round(v):
    return round(v) if isinstance(v, (int, float)) else "--"


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
        "ocean": "--", "swell": "--", "energy": "--", "energy_tier": 0,
        "ocean_forecast": [],
    }

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
        if len(sunset) > 1:
            p["set"] = fmt_time(sunset[1])

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

    if marine:
        m_daily = marine.get("daily", {})
        m_hourly = marine.get("hourly", {})

        # Build per-day max SST from hourly data
        sst_by_day = {}
        for ts, t in zip(m_hourly.get("time", []),
                          m_hourly.get("sea_surface_temperature", [])):
            if t is None or "T" not in ts:
                continue
            d = ts.split("T")[0]
            if d not in sst_by_day or t > sst_by_day[d]:
                sst_by_day[d] = t

        today_str = now.strftime("%Y-%m-%d")
        if today_str in sst_by_day:
            p["ocean"] = round(sst_by_day[today_str])

        swell_h = (m_daily.get("swell_wave_height_max") or [None])[0]
        swell_t = (m_daily.get("swell_wave_period_max") or [None])[0]
        swell_d = (m_daily.get("swell_wave_direction_dominant") or [None])[0]

        if isinstance(swell_h, (int, float)) and isinstance(swell_t, (int, float)):
            p["swell"] = "{}ft @ {}s {}".format(
                round(swell_h), round(swell_t), cardinal(swell_d)
            ).strip()
            # Wave energy: rho*g^2/(16*pi) * H^2 * T^2 (kJ)
            # Calibrated against surf-forecast.com ranges:
            # 100 kJ surfable, 200-1000 punchy, 1000-5000 heavy.
            # H in meters, T in seconds.
            h_m = swell_h * 0.3048
            kj = round(1.96 * h_m * h_m * swell_t * swell_t)
            p["energy"] = "{} kJ".format(kj)
            p["energy_tier"] = energy_tier(kj)

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
    if TRMNL_WEBHOOK_UUID:
        log.info("TRMNL webhook configured")
    else:
        log.info("No TRMNL webhook - console only mode")
    while True:
        payload = build_payload()
        mv = payload["merge_variables"]
        log.info("Today: %s°/%s° %s | Ocean %s°F | Swell %s | %s",
                 mv.get("hi"), mv.get("lo"), mv.get("phrase"),
                 mv.get("ocean"), mv.get("swell"), mv.get("energy"))
        push_to_trmnl(payload)
        save_state(payload)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()

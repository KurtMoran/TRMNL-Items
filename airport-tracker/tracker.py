#!/usr/bin/env python3
"""Airport Traffic Tracker for TRMNL e-ink display.

Polls airplanes.live every 2 minutes for aircraft near a configured airport,
detects arrivals/departures, and pushes daily stats to a TRMNL e-ink
display via webhook.
"""
import json, logging, os, time
from datetime import datetime
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("airport-tracker")

AIRPORT_LAT = float(os.getenv("AIRPORT_LAT", "32.8157"))
AIRPORT_LON = float(os.getenv("AIRPORT_LON", "-117.1397"))
AIRPORT_ELEV_FT = int(os.getenv("AIRPORT_ELEV_FT", "427"))
AIRPORT_CODE = os.getenv("AIRPORT_CODE", "KMYF")
QUERY_RADIUS_NM = 5
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "120"))
TRMNL_WEBHOOK_UUID = os.getenv("TRMNL_WEBHOOK_UUID", "")
TRMNL_API_URL = "https://trmnl.com/api/custom_plugins"
DATA_FILE = os.getenv("DATA_FILE", "/data/tracker_state.json")
MAX_ALT_AGL = 1500
CLOSE_RADIUS_NM = 3
GONE_TIMEOUT_SEC = 300
API_URL = "https://api.airplanes.live/v2/point/{}/{}/{}".format(AIRPORT_LAT, AIRPORT_LON, QUERY_RADIUS_NM)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit&timezone=America/Los_Angeles&forecast_days=1".format(AIRPORT_LAT, AIRPORT_LON)

AIRCRAFT_DB = {
    "C150": ("Cessna 150", "single-high"), "C152": ("Cessna 152", "single-high"),
    "C162": ("Cessna Skycatcher", "single-high"), "C170": ("Cessna 170", "single-high"),
    "C172": ("Cessna 172", "single-high"), "C175": ("Cessna 175", "single-high"),
    "C177": ("Cessna Cardinal", "single-high"), "C180": ("Cessna 180", "single-high"),
    "C182": ("Cessna 182", "single-high"), "C185": ("Cessna 185", "single-high"),
    "C206": ("Cessna 206", "single-high"), "C207": ("Cessna 207", "single-high"),
    "C208": ("Cessna Caravan", "turboprop"), "C210": ("Cessna 210", "single-high"),
    "C205": ("Cessna 205", "single-high"),
    "P28A": ("Piper Cherokee", "single-low"), "P28B": ("Piper Cherokee", "single-low"),
    "P28R": ("Piper Arrow", "single-low"), "P28T": ("Piper Turbo Arrow", "single-low"),
    "PA28": ("Piper Cherokee", "single-low"), "PA24": ("Piper Comanche", "single-low"),
    "PA32": ("Piper Saratoga", "single-low"), "PA38": ("Piper Tomahawk", "single-low"),
    "PA46": ("Piper Malibu", "single-low"), "PA18": ("Piper Cub", "single-high"),
    "PA22": ("Piper Tri-Pacer", "single-high"),
    "SR20": ("Cirrus SR20", "single-low"), "SR22": ("Cirrus SR22", "single-low"),
    "SF50": ("Cirrus Vision Jet", "jet"),
    "DA20": ("Diamond DA20", "single-low"), "DA40": ("Diamond DA40", "single-low"),
    "DA42": ("Diamond DA42", "twin"), "DA62": ("Diamond DA62", "twin"),
    "BE33": ("Beech Bonanza", "single-low"), "BE35": ("Beech Bonanza", "single-low"),
    "BE36": ("Beech Bonanza", "single-low"), "BE55": ("Beech Baron", "twin"),
    "BE58": ("Beech Baron", "twin"), "BE76": ("Beech Duchess", "twin"),
    "BE9L": ("Beech King Air", "turboprop"), "BE20": ("Beech King Air", "turboprop"),
    "B350": ("Beech King Air 350", "turboprop"),
    "M20P": ("Mooney", "single-low"), "M20T": ("Mooney", "single-low"),
    "M20J": ("Mooney", "single-low"), "M20K": ("Mooney", "single-low"),
    "M20R": ("Mooney", "single-low"),
    "AA5": ("Grumman Tiger", "single-low"), "AA1": ("Grumman Trainer", "single-low"),
    "PA34": ("Piper Seneca", "twin"), "PA44": ("Piper Seminole", "twin"),
    "PA31": ("Piper Navajo", "twin"), "C310": ("Cessna 310", "twin"),
    "C340": ("Cessna 340", "twin"), "C402": ("Cessna 402", "twin"),
    "C414": ("Cessna 414", "twin"), "C421": ("Cessna 421", "twin"),
    "PC12": ("Pilatus PC-12", "turboprop"), "TBM7": ("TBM 700", "turboprop"),
    "TBM8": ("TBM 850", "turboprop"), "TBM9": ("TBM 900", "turboprop"),
    "P180": ("Piaggio Avanti", "turboprop"),
    "C525": ("Citation CJ", "jet"), "C510": ("Citation Mustang", "jet"),
    "C550": ("Citation II", "jet"), "C560": ("Citation V", "jet"),
    "C56X": ("Citation Excel", "jet"), "C680": ("Citation Sovereign", "jet"),
    "C700": ("Citation Longitude", "jet"), "C750": ("Citation X", "jet"),
    "LJ35": ("Learjet 35", "jet"), "LJ45": ("Learjet 45", "jet"),
    "LJ60": ("Learjet 60", "jet"), "EA50": ("Eclipse 500", "jet"),
    "E500": ("Eclipse 500", "jet"), "E55P": ("Embraer Phenom", "jet"),
    "GL5T": ("Gulfstream G500", "jet"), "GLEX": ("Global Express", "jet"),
    "GLF4": ("Gulfstream IV", "jet"), "GLF5": ("Gulfstream V", "jet"),
    "FA50": ("Falcon 50", "jet"), "FA7X": ("Falcon 7X", "jet"),
    "H25B": ("Hawker 800", "jet"), "CL30": ("Challenger 300", "jet"),
    "CL35": ("Challenger 350", "jet"), "CL60": ("Challenger 600", "jet"),
    "PRM1": ("Premier I", "jet"),
    "R22": ("Robinson R22", "helo"), "R44": ("Robinson R44", "helo"),
    "R66": ("Robinson R66", "helo"), "EC35": ("Eurocopter EC135", "helo"),
    "EC30": ("Eurocopter EC130", "helo"), "EC45": ("Eurocopter EC145", "helo"),
    "A139": ("AW139", "helo"), "B06": ("Bell 206", "helo"),
    "B407": ("Bell 407", "helo"), "B412": ("Bell 412", "helo"),
    "S76": ("Sikorsky S-76", "helo"), "AS50": ("AS350 Squirrel", "helo"),
    "T6": ("T-6 Texan II", "turboprop"), "T38": ("T-38 Talon", "jet"),
    "RV7": ("Van's RV-7", "single-low"), "RV8": ("Van's RV-8", "single-low"),
    "RV6": ("Van's RV-6", "single-low"), "RV10": ("Van's RV-10", "single-low"),
    "RV14": ("Van's RV-14", "single-low"),
}

def get_aircraft_info(ac_type, ac_desc=""):
    if ac_type in AIRCRAFT_DB:
        return AIRCRAFT_DB[ac_type]
    desc_lower = (ac_desc or "").lower()
    if any(w in desc_lower for w in ["helicopter", "rotor"]):
        return (ac_desc or ac_type, "helo")
    if any(w in desc_lower for w in ["jet", "gulfstream", "learjet", "citation"]):
        return (ac_desc or ac_type, "jet")
    if any(w in desc_lower for w in ["twin", "baron", "duchess"]):
        return (ac_desc or ac_type, "twin")
    if any(w in desc_lower for w in ["cessna", "maule", "stol"]):
        return (ac_desc or ac_type, "single-high")
    name = ac_desc or ac_type or "Unknown"
    if name.isupper() and len(name) > 5:
        name = name.title()
    return (name, "single-low")

def to_12hr(hk):
    h = int(hk)
    if h == 0: return "12am"
    elif h < 12: return "{}am".format(h)
    elif h == 12: return "12pm"
    else: return "{}pm".format(h - 12)

def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("Could not load state file, starting fresh")
    return {"active_aircraft": {}, "today": datetime.now().strftime("%Y-%m-%d"),
            "hourly_counts": {}, "type_counts": {}, "total_arrivals": 0,
            "total_departures": 0, "recent_movements": []}

def save_state(state):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(state, f)

def reset_if_new_day(state):
    today = datetime.now().strftime("%Y-%m-%d")
    if state["today"] != today:
        log.info("New day detected, resetting counters")
        state.update({"today": today, "hourly_counts": {}, "type_counts": {},
                       "total_arrivals": 0, "total_departures": 0,
                       "recent_movements": [], "active_aircraft": {}})
    return state

def fetch_weather():
    try:
        resp = requests.get(WEATHER_URL, timeout=15)
        resp.raise_for_status()
        daily = resp.json().get("daily", {})
        return {"high": round(daily["temperature_2m_max"][0]), "low": round(daily["temperature_2m_min"][0])}
    except Exception as e:
        log.error("Weather fetch failed: %s", e)
        return {"high": "--", "low": "--"}

def fetch_aircraft():
    try:
        resp = requests.get(API_URL, timeout=15)
        resp.raise_for_status()
        return resp.json().get("ac", [])
    except Exception as e:
        log.error("API fetch failed: %s", e)
        return []

def classify_movement(ac):
    baro_rate = ac.get("baro_rate", 0) or 0
    if baro_rate < -200:
        return "arrival"
    elif baro_rate > 200:
        return "departure"
    return None

def process_aircraft(state, aircraft_list):
    now = time.time()
    hour_key = datetime.now().strftime("%H")
    if hour_key not in state["hourly_counts"]:
        state["hourly_counts"][hour_key] = {"arrivals": 0, "departures": 0}
    for ac in aircraft_list:
        hex_id = ac.get("hex", "")
        if not hex_id:
            continue
        alt_baro = ac.get("alt_baro")
        if alt_baro is None or alt_baro == "ground":
            alt_agl = 0
        else:
            alt_agl = alt_baro - AIRPORT_ELEV_FT
        dst = ac.get("dst", 99)
        if dst > CLOSE_RADIUS_NM or alt_agl > MAX_ALT_AGL:
            continue
        ac_type = ac.get("t", "Unknown")
        ac_desc = ac.get("desc", ac_type)
        registration = ac.get("r", "")
        callsign = (ac.get("flight") or "").strip()
        if hex_id not in state["active_aircraft"]:
            movement = classify_movement(ac)
            if movement:
                if movement == "arrival":
                    state["total_arrivals"] += 1
                    state["hourly_counts"][hour_key]["arrivals"] += 1
                else:
                    state["total_departures"] += 1
                    state["hourly_counts"][hour_key]["departures"] += 1
                friendly_name, category = get_aircraft_info(ac_type, ac_desc)
                if ac_type and ac_type != "Unknown":
                    type_key = friendly_name or ac_type
                    state["type_counts"][type_key] = state["type_counts"].get(type_key, 0) + 1
                state["recent_movements"].append({
                    "time": datetime.now().strftime("%-I:%M %p"),
                    "type": movement, "aircraft": friendly_name,
                    "registration": registration,
                })
                state["recent_movements"] = state["recent_movements"][-20:]
                log.info("%s: %s %s (%s) - %s", movement.upper(), ac_type, registration, callsign, ac_desc)
        state["active_aircraft"][hex_id] = {"last_seen": now, "type": ac_type, "registration": registration}
    stale = [h for h, info in state["active_aircraft"].items() if now - info["last_seen"] > GONE_TIMEOUT_SEC]
    for h in stale:
        del state["active_aircraft"][h]
    return state

def build_trmnl_payload(state):
    now = datetime.now()
    hour_key = now.strftime("%H")
    current_hour = state["hourly_counts"].get(hour_key, {"arrivals": 0, "departures": 0})
    sorted_types = sorted(state["type_counts"].items(), key=lambda x: -x[1])[:6]
    top_types = [{"type": t, "count": c} for t, c in sorted_types]
    peak_hour = ""
    peak_hour_count = 0
    for hk, counts in state["hourly_counts"].items():
        total = counts["arrivals"] + counts["departures"]
        if total > peak_hour_count:
            peak_hour_count = total
            peak_hour = to_12hr(hk)
    recent = [{"time": m["time"], "type": m["type"], "aircraft": m["aircraft"],
               "registration": m.get("registration", "")} for m in state["recent_movements"][-6:]]
    recent.reverse()
    hourly_list = []
    for h in range(24):
        hk = "{:02d}".format(h)
        if hk in state["hourly_counts"]:
            counts = state["hourly_counts"][hk]
            total = counts["arrivals"] + counts["departures"]
            if total > 0:
                hourly_list.append({"hour": to_12hr(hk), "arr": counts["arrivals"],
                                     "dep": counts["departures"], "total": total})
    max_hourly = max((h["total"] for h in hourly_list), default=1)
    for h in hourly_list:
        h["aw"] = int(h["arr"] * 85 / max_hourly)
        h["dw"] = int(h["dep"] * 85 / max_hourly)
    total_movements = state["total_arrivals"] + state["total_departures"]
    weather = fetch_weather()
    return {"merge_variables": {
        "date": now.strftime("%A, %B %d"), "updated": now.strftime("%-I:%M %p"),
        "hi": weather["high"], "lo": weather["low"],
        "ops": total_movements, "arr": state["total_arrivals"],
        "dep": state["total_departures"],
        "pk": peak_hour or "--", "pkn": peak_hour_count,
        "types": top_types, "hourly": hourly_list,
    }}

def push_to_trmnl(payload):
    if not TRMNL_WEBHOOK_UUID:
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

def main():
    log.info("Starting %s Airport Tracker", AIRPORT_CODE)
    log.info("Polling every %ds, radius %dnm", POLL_INTERVAL_SEC, QUERY_RADIUS_NM)
    if TRMNL_WEBHOOK_UUID:
        log.info("TRMNL webhook configured")
    else:
        log.info("No TRMNL webhook - console only mode")
    state = load_state()
    push_counter = 0
    PUSH_EVERY_N = max(1, 600 // POLL_INTERVAL_SEC)
    while True:
        state = reset_if_new_day(state)
        aircraft = fetch_aircraft()
        log.info("Fetched %d aircraft nearby", len(aircraft))
        state = process_aircraft(state, aircraft)
        save_state(state)
        push_counter += 1
        if push_counter >= PUSH_EVERY_N:
            payload = build_trmnl_payload(state)
            log.info("Stats - Today: %d movements (%d arr / %d dep) | Types: %d",
                payload["merge_variables"]["ops"], payload["merge_variables"]["arr"],
                payload["merge_variables"]["dep"], len(state["type_counts"]))
            push_to_trmnl(payload)
            push_counter = 0
        time.sleep(POLL_INTERVAL_SEC)

if __name__ == "__main__":
    main()

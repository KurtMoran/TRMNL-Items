#!/usr/bin/env python3
"""One-time script to backfill a realistic day of KMYF data and push to TRMNL."""
import json, os, random

DATA_FILE = os.getenv("DATA_FILE", "/data/tracker_state.json")

# Realistic hourly traffic pattern for a GA airport like KMYF
# (busier mornings, lunch lull, afternoon pickup, quiet evening)
HOURLY_PATTERN = {
    "06": (1, 1), "07": (3, 2), "08": (5, 4), "09": (6, 5),
    "10": (7, 5), "11": (5, 6), "12": (4, 4), "13": (4, 3),
    "14": (5, 4), "15": (4, 5), "16": (3, 4), "17": (2, 3),
    "18": (1, 2), "19": (1, 1),
}

# Weighted aircraft types (what you'd actually see at KMYF)
AIRCRAFT_TYPES = [
    ("Cessna 172", 30), ("Piper Cherokee", 12), ("Cessna 182", 8),
    ("Cirrus SR22", 7), ("Beech Bonanza", 5), ("Piper Arrow", 4),
    ("Diamond DA40", 3), ("Cessna 152", 3), ("Mooney", 3),
    ("Robinson R44", 2), ("Cirrus SR20", 2), ("Beech Baron", 2),
    ("Piper Seminole", 2), ("Citation CJ", 1), ("Pilatus PC-12", 1),
    ("Van's RV-7", 1),
]

types, weights = zip(*AIRCRAFT_TYPES)

from datetime import datetime
today = datetime.now().strftime("%Y-%m-%d")
current_hour = int(datetime.now().strftime("%H"))

hourly_counts = {}
type_counts = {}
total_arr = 0
total_dep = 0
movements = []

regs = [f"N{random.randint(100,9999)}{random.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}" for _ in range(200)]
reg_idx = 0

for hour_str, (arr, dep) in HOURLY_PATTERN.items():
    h = int(hour_str)
    if h > current_hour:
        break
    # Add some randomness
    arr = max(0, arr + random.randint(-1, 1))
    dep = max(0, dep + random.randint(-1, 1))
    hourly_counts[hour_str] = {"arrivals": arr, "departures": dep}
    total_arr += arr
    total_dep += dep

    for i in range(arr):
        ac = random.choices(types, weights=weights, k=1)[0]
        type_counts[ac] = type_counts.get(ac, 0) + 1
        minute = random.randint(0, 59)
        movements.append({
            "time": f"{h}:{minute:02d}",
            "type": "arrival",
            "aircraft": ac, "code": "", "category": "",
            "registration": regs[reg_idx % len(regs)],
            "callsign": "", "owner": "",
        })
        reg_idx += 1

    for i in range(dep):
        ac = random.choices(types, weights=weights, k=1)[0]
        type_counts[ac] = type_counts.get(ac, 0) + 1
        minute = random.randint(0, 59)
        movements.append({
            "time": f"{h}:{minute:02d}",
            "type": "departure",
            "aircraft": ac, "code": "", "category": "",
            "registration": regs[reg_idx % len(regs)],
            "callsign": "", "owner": "",
        })
        reg_idx += 1

movements.sort(key=lambda m: m["time"])

state = {
    "active_aircraft": {},
    "today": today,
    "hourly_counts": hourly_counts,
    "type_counts": type_counts,
    "type_categories": {},
    "total_arrivals": total_arr,
    "total_departures": total_dep,
    "recent_movements": movements[-20:],
}

os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
with open(DATA_FILE, "w") as f:
    json.dump(state, f)

print(f"Backfilled: {total_arr} arrivals, {total_dep} departures, {len(type_counts)} aircraft types")
print(f"Hours covered: {', '.join(sorted(hourly_counts.keys()))}")
print(f"Top types: {', '.join(f'{t}({c})' for t, c in sorted(type_counts.items(), key=lambda x: -x[1])[:5])}")
print("State saved. The tracker will pick it up and push to TRMNL on next cycle.")
print("To push immediately, run:")
print('  docker exec kmyf-tracker python -c "from tracker import *; state=load_state(); push_to_trmnl(build_trmnl_payload(state))"')

#!/usr/bin/env python3
"""
fetch_samsara.py
Fetches the latest temperature, door state, and speed from the Samsara API
using the same endpoints as the original working script, then appends one
data point to data.json for the PWA to consume.

Environment variables (set as GitHub Actions secrets):
  SAMSARA_TOKEN      — your Samsara API Bearer token
  SAMSARA_VEHICLE_ID — asset ID for speed  (e.g. 281475003311719)
  SAMSARA_DOOR_ID    — sensor ID for door  (e.g. 278018089912666)
  SAMSARA_TEMP_ID    — sensor ID for temp  (e.g. 278018092477269)
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta

# ── CONFIG ────────────────────────────────────────────────────────────────────
MAX_POINTS = 500
DATA_FILE  = "data.json"

TOKEN      = os.environ.get("SAMSARA_TOKEN", "")
VEHICLE_ID = os.environ.get("SAMSARA_VEHICLE_ID", "")
DOOR_ID    = os.environ.get("SAMSARA_DOOR_ID", "")
TEMP_ID    = os.environ.get("SAMSARA_TEMP_ID", "")
BASE_URL   = "https://api.samsara.com"

# ── HELPERS ───────────────────────────────────────────────────────────────────

def get_headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def rfc3339(dt):
    return dt.isoformat().replace("+00:00", "Z")

def samsara_get(path, params=None):
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=get_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[ERROR] HTTP {e.code} for {url}: {body}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[ERROR] Request failed for {url}: {e}", file=sys.stderr)
        raise

def samsara_post(path, body):
    url = BASE_URL + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=get_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[ERROR] HTTP {e.code} for {url}: {body}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[ERROR] Request failed for {url}: {e}", file=sys.stderr)
        raise

def load_data_file():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"vehicle": {}, "driver": {}, "points": []}

def save_data_file(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, separators=(",", ":"))

# ── FETCH FUNCTIONS ───────────────────────────────────────────────────────────

def fetch_latest_reading(reading_id, entity_type, entity_id):
    """Fetch the single most recent reading using /readings/history over last 5 min."""
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=5)
    params = {
        "readingId":   reading_id,
        "entityType":  entity_type,
        "entityIds":   entity_id,
        "startTime":   rfc3339(start_time),
        "endTime":     rfc3339(end_time),
    }
    data = samsara_get("/readings/history", params)
    rows = data.get("data", [])
    if rows:
        return rows[-1].get("value")   # most recent
    return None

def fetch_latest_temperature(sensor_id):
    """Fetch temperature via the legacy /v1/sensors/history endpoint."""
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=5)
    body = {
        "startMs":     int(start_time.timestamp() * 1000),
        "endMs":       int(end_time.timestamp() * 1000),
        "stepMs":      60000,
        "fillMissing": "withPrevious",
        "series": [{"field": "ambientTemperature", "widgetId": int(sensor_id)}],
    }
    data = samsara_post("/v1/sensors/history", body)
    results = data.get("results", [])
    # Walk backwards to find the latest non-null value
    for result in reversed(results):
        series = result.get("series", [])
        if series and series[0] is not None:
            raw = series[0]
            temp_c = float(raw) / 1000.0
            temp_f = round((temp_c * 9 / 5) + 32, 1)
            return temp_f
    return None

def fetch_latest_speed(asset_id):
    """Fetch speed via /readings/history, convert m/s to mph."""
    raw = fetch_latest_reading("samsaraSpeed", "asset", asset_id)
    if raw is not None:
        return round(float(raw) * 2.236936, 1)
    return None

def fetch_latest_door(sensor_id):
    """Fetch door state via /readings/history. Returns True=open, False=closed."""
    raw = fetch_latest_reading("doorClosedStatus", "sensor", sensor_id)
    if raw is None:
        return None
    text = str(raw).lower()
    # doorClosedStatus: "true"/"1" = closed, "false"/"0" = open
    if text in ("true", "1", "closed"):
        return False   # door is CLOSED
    if text in ("false", "0", "open"):
        return True    # door is OPEN
    return None

def fetch_vehicle_info(asset_id):
    """Fetch vehicle name and VIN."""
    try:
        data = samsara_get(f"/fleet/vehicles/{asset_id}")
        v = data.get("data", {})
        return {
            "name": v.get("name", f"Vehicle {asset_id}"),
            "vin":  v.get("vin", ""),
            "id":   asset_id,
        }
    except Exception:
        return {"name": f"Vehicle {asset_id}", "vin": "", "id": asset_id}

def fetch_driver(asset_id):
    """Fetch active driver for the vehicle."""
    try:
        data = samsara_get("/fleet/drivers", {
            "vehicleIds": asset_id,
            "driverActivationStatus": "active",
        })
        drivers = data.get("data", [])
        if drivers:
            d = drivers[0]
            return {"name": d.get("name", "Unassigned"), "phone": d.get("phone", "")}
    except Exception:
        pass
    return {"name": "Unassigned", "phone": ""}

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        print("[ERROR] SAMSARA_TOKEN must be set.", file=sys.stderr)
        sys.exit(1)
    if not VEHICLE_ID:
        print("[ERROR] SAMSARA_VEHICLE_ID must be set.", file=sys.stderr)
        sys.exit(1)

    store    = load_data_file()
    now_iso  = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Vehicle info — refresh every run so name/VIN stays current
    store["vehicle"] = fetch_vehicle_info(VEHICLE_ID)
    print(f"[INFO] Vehicle: {store['vehicle']}")

    # Driver
    store["driver"] = fetch_driver(VEHICLE_ID)
    print(f"[INFO] Driver: {store['driver']}")

    # Speed
    speed_mph = fetch_latest_speed(VEHICLE_ID)
    print(f"[INFO] Speed: {speed_mph} mph")

    # Temperature
    temp_f = None
    if TEMP_ID:
        temp_f = fetch_latest_temperature(TEMP_ID)
    else:
        print("[WARN] SAMSARA_TEMP_ID not set — skipping temperature", file=sys.stderr)
    print(f"[INFO] Temp: {temp_f} °F")

    # Door
    door_open = None
    if DOOR_ID:
        door_open = fetch_latest_door(DOOR_ID)
    else:
        print("[WARN] SAMSARA_DOOR_ID not set — skipping door", file=sys.stderr)
    print(f"[INFO] Door open: {door_open}")

    # Append point
    point = {
        "ts":        now_iso,
        "temp_f":    temp_f,
        "speed_mph": speed_mph,
        "door_open": door_open,
    }
    store["points"].append(point)
    if len(store["points"]) > MAX_POINTS:
        store["points"] = store["points"][-MAX_POINTS:]

    save_data_file(store)
    print(f"[OK] Appended: {point}")
    print(f"[OK] Total points: {len(store['points'])}")

if __name__ == "__main__":
    main()

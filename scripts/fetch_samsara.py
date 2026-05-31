#!/usr/bin/env python3
"""
fetch_samsara.py — Perch by Parliament Trucking
Fetches temperature, door, speed, geofence status from Samsara API.

Secrets required:
  SAMSARA_TOKEN      — Bearer token
  SAMSARA_VEHICLE_ID — asset ID
  SAMSARA_DOOR_ID    — door sensor ID
  SAMSARA_TEMP_ID    — temp sensor ID
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta

MAX_POINTS = 500
DATA_FILE  = "data.json"

TOKEN      = os.environ.get("SAMSARA_TOKEN", "")
VEHICLE_ID = os.environ.get("SAMSARA_VEHICLE_ID", "")
DOOR_ID    = os.environ.get("SAMSARA_DOOR_ID", "")
TEMP_ID    = os.environ.get("SAMSARA_TEMP_ID", "")
BASE_URL   = "https://api.samsara.com"

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
        print(f"[ERROR] {url}: {e}", file=sys.stderr)
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
        print(f"[ERROR] {url}: {e}", file=sys.stderr)
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
    end_time   = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=5)
    params = {
        "readingId":  reading_id,
        "entityType": entity_type,
        "entityIds":  entity_id,
        "startTime":  rfc3339(start_time),
        "endTime":    rfc3339(end_time),
    }
    data = samsara_get("/readings/history", params)
    rows = data.get("data", [])
    return rows[-1].get("value") if rows else None

def fetch_latest_temperature(sensor_id):
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
    for result in reversed(data.get("results", [])):
        series = result.get("series", [])
        if series and series[0] is not None:
            temp_c = float(series[0]) / 1000.0
            return round((temp_c * 9 / 5) + 32, 1)
    return None

def fetch_latest_speed(asset_id):
    raw = fetch_latest_reading("samsaraSpeed", "asset", asset_id)
    if raw is not None:
        return round(float(raw) * 2.236936, 1)
    return None

def fetch_latest_door(sensor_id):
    raw = fetch_latest_reading("doorClosedStatus", "sensor", sensor_id)
    if raw is None:
        return None
    text = str(raw).lower()
    if text in ("true", "1", "closed"):
        return False  # CLOSED
    if text in ("false", "0", "open"):
        return True   # OPEN
    return None

def fetch_vehicle_info(asset_id):
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

def fetch_geofence_status(asset_id, speed_mph):
    """
    Determine operational status by checking current GPS position against geofences.
    Uses /fleet/vehicles/stats?types=gps which returns address/geofence data.
    Then looks up the address tags to determine DC vs Customer.

    Returns one of: 'Loading', 'Unloading', 'Driving', 'Unknown'
    """
    try:
        data = samsara_get("/fleet/vehicles/stats", {
            "vehicleIds": asset_id,
            "types": "gps",
        })
        entries = data.get("data", [])
        if not entries:
            return "Unknown"

        gps = entries[0].get("gps", {})
        geofence = gps.get("reverseGeo", {}).get("geofence") or gps.get("geofence")

        # Some API versions nest it differently — try both
        if not geofence:
            # Try the decorations path
            rev = gps.get("reverseGeo", {})
            geofence_id = rev.get("geofenceId") or rev.get("id")
        else:
            geofence_id = geofence.get("id") if isinstance(geofence, dict) else geofence

        if not geofence_id:
            # Not inside any geofence
            if speed_mph is not None and speed_mph > 0.5:
                return "Driving"
            return "Unknown"

        # Look up the address to get its tags
        addr_data = samsara_get(f"/addresses/{geofence_id}")
        addr = addr_data.get("data", {})
        tags = addr.get("tags", [])
        tag_names = [t.get("name", "").upper() for t in tags]

        print(f"[INFO] Geofence ID: {geofence_id}, tags: {tag_names}")

        if "DC" in tag_names:
            return "Loading"
        if "CUSTOMER" in tag_names:
            return "Unloading"

        # Inside a geofence but no matching tag
        return "Unknown"

    except Exception as e:
        print(f"[WARN] Geofence status fetch failed: {e}", file=sys.stderr)
        # Fall back to speed-based status
        if speed_mph is not None and speed_mph > 0.5:
            return "Driving"
        return "Unknown"

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        print("[ERROR] SAMSARA_TOKEN must be set.", file=sys.stderr)
        sys.exit(1)
    if not VEHICLE_ID:
        print("[ERROR] SAMSARA_VEHICLE_ID must be set.", file=sys.stderr)
        sys.exit(1)

    store   = load_data_file()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    store["vehicle"] = fetch_vehicle_info(VEHICLE_ID)
    print(f"[INFO] Vehicle: {store['vehicle']}")

    store["driver"] = fetch_driver(VEHICLE_ID)
    print(f"[INFO] Driver: {store['driver']}")

    speed_mph = fetch_latest_speed(VEHICLE_ID)
    print(f"[INFO] Speed: {speed_mph} mph")

    temp_f = None
    if TEMP_ID:
        temp_f = fetch_latest_temperature(TEMP_ID)
    print(f"[INFO] Temp: {temp_f} °F")

    door_open = None
    if DOOR_ID:
        door_open = fetch_latest_door(DOOR_ID)
    print(f"[INFO] Door open: {door_open}")

    status = fetch_geofence_status(VEHICLE_ID, speed_mph)
    print(f"[INFO] Status: {status}")

    point = {
        "ts":        now_iso,
        "temp_f":    temp_f,
        "speed_mph": speed_mph,
        "door_open": door_open,
        "status":    status,
    }
    store["points"].append(point)
    if len(store["points"]) > MAX_POINTS:
        store["points"] = store["points"][-MAX_POINTS:]

    save_data_file(store)
    print(f"[OK] Appended: {point}")
    print(f"[OK] Total points: {len(store['points'])}")

if __name__ == "__main__":
    main()

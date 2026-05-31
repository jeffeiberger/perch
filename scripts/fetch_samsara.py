#!/usr/bin/env python3
"""
fetch_samsara.py
Fetches the latest temperature, door state, speed, vehicle info, and
active driver from the Samsara API, then appends one data point to
data.json (kept in the repo root) for the PWA to consume.

Environment variables (set as GitHub Actions secrets):
  SAMSARA_TOKEN   — your Samsara API Bearer token
  VEHICLE_ID      — Samsara numeric vehicle ID  (e.g. 281474978123456)

The script keeps up to MAX_POINTS readings in data.json so the file
stays small regardless of how long the workflow runs.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── CONFIG ────────────────────────────────────────────────────────────────────
MAX_POINTS  = 500        # rolling window of data points stored in data.json
DATA_FILE   = "data.json"

TOKEN      = os.environ.get("SAMSARA_TOKEN", "")
VEHICLE_ID = os.environ.get("VEHICLE_ID", "")
BASE_URL   = "https://api.samsara.com"

# Samsara returns temperature in millidegrees Celsius
TEMP_STAT  = "ambientAirTemperatureMilliC"
# Door/cargo sensor stat type — adjust if your gateway uses a different key
# Common alternatives: "cargoStatus", "gatewaySensor"
DOOR_STAT  = "obdEngineSeconds"   # placeholder — see note below
# Speed in milliMeters per second
SPEED_STAT = "gpsSpeedMilliMetersPerSecond"

# ── HELPERS ───────────────────────────────────────────────────────────────────

def samsara_get(path: str) -> dict:
    """Make an authenticated GET request to the Samsara API."""
    url = BASE_URL + path
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
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


def milliC_to_F(milli_c: float) -> float:
    """Convert millidegrees Celsius to Fahrenheit, rounded to 1 decimal."""
    celsius = milli_c / 1000.0
    return round((celsius * 9 / 5) + 32, 1)


def mm_per_sec_to_mph(mm_s: float) -> float:
    """Convert mm/s to mph, rounded to 1 decimal."""
    return round(mm_s * 0.00223694, 1)


def load_data_file() -> dict:
    """Load existing data.json or return a fresh structure."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "vehicle": {},
        "driver":  {},
        "points":  []
    }


def save_data_file(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, separators=(",", ":"))  # compact JSON


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    if not TOKEN or not VEHICLE_ID:
        print("[ERROR] SAMSARA_TOKEN and VEHICLE_ID must be set.", file=sys.stderr)
        sys.exit(1)

    store = load_data_file()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ── 1. Vehicle info (cached — only refresh if empty) ──────────────────
    if not store.get("vehicle"):
        try:
            vdata = samsara_get(f"/fleet/vehicles/{VEHICLE_ID}")
            v = vdata.get("data", {})
            store["vehicle"] = {
                "name": v.get("name", VEHICLE_ID),
                "vin":  v.get("vin", ""),
                "id":   v.get("id", VEHICLE_ID),
            }
            print(f"[INFO] Vehicle: {store['vehicle']}")
        except Exception:
            store["vehicle"] = {"name": f"Vehicle {VEHICLE_ID}", "vin": "", "id": VEHICLE_ID}

    # ── 2. Active driver ──────────────────────────────────────────────────
    try:
        ddata = samsara_get(f"/fleet/vehicles/{VEHICLE_ID}/driver-assignments")
        assignments = ddata.get("data", [])
        if assignments:
            d = assignments[0].get("driver", {})
            store["driver"] = {
                "name":  d.get("name", "Unassigned"),
                "phone": d.get("phone", ""),
            }
        else:
            store["driver"] = {"name": "Unassigned", "phone": ""}
    except Exception:
        store.setdefault("driver", {"name": "Unassigned", "phone": ""})

    # ── 3. Latest vehicle stats ───────────────────────────────────────────
    # Request temperature + speed in one call.
    # NOTE on door state: Samsara exposes door/cargo sensors through the
    # industrial sensor API (/industrial/assets) or as a custom stat if
    # you have a Samsara CM31/CM32 gateway wired to a door switch.
    # We request the stat here; if your setup uses a different key, change
    # DOOR_STAT above. The script falls back gracefully if it's missing.
    stats_path = (
        f"/fleet/vehicles/stats"
        f"?vehicleIds={VEHICLE_ID}"
        f"&types={TEMP_STAT},{SPEED_STAT}"
    )
    temp_f    = None
    speed_mph = None
    door_open = None  # will be populated below if sensor is available

    try:
        sdata  = samsara_get(stats_path)
        ventry = sdata.get("data", [{}])[0]

        # Temperature
        temp_raw = ventry.get(TEMP_STAT, {}).get("value")
        if temp_raw is not None:
            temp_f = milliC_to_F(float(temp_raw))

        # Speed
        spd_raw = ventry.get(SPEED_STAT, {}).get("value")
        if spd_raw is not None:
            speed_mph = mm_per_sec_to_mph(float(spd_raw))

    except Exception as e:
        print(f"[WARN] Stats fetch failed: {e}", file=sys.stderr)

    # ── 4. Door / cargo sensor ────────────────────────────────────────────
    # Try the industrial assets endpoint for a door sensor wired to the
    # Samsara gateway. This section is best-effort — if you have a CM31/32
    # with a door switch, the asset will appear here.
    try:
        idata  = samsara_get(f"/industrial/assets?parentIds={VEHICLE_ID}")
        assets = idata.get("data", [])
        for asset in assets:
            for dp in asset.get("datapoints", []):
                label = dp.get("type", "").lower()
                if "door" in label or "cargo" in label:
                    door_open = (str(dp.get("value", "")).lower() in ("1", "open", "true"))
                    break
    except Exception:
        pass  # door sensor not available / different setup

    # ── 5. Append data point ──────────────────────────────────────────────
    point = {
        "ts":        now_iso,
        "temp_f":    temp_f,
        "speed_mph": speed_mph,
        "door_open": door_open,   # None = unknown, True = open, False = closed
    }
    store["points"].append(point)

    # Trim to rolling window
    if len(store["points"]) > MAX_POINTS:
        store["points"] = store["points"][-MAX_POINTS:]

    save_data_file(store)
    print(f"[OK] Appended point: {point}")
    print(f"[OK] Total points stored: {len(store['points'])}")


if __name__ == "__main__":
    main()

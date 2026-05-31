# ColdChain Monitor PWA

Real-time refrigerated cargo dashboard. A GitHub Action polls the Samsara
API every ~30 seconds, writes telemetry to `data.json`, and commits it back
to the repo. The GitHub Pages PWA polls that file — no backend, no proxy,
no extra services needed.

---

## Repo layout

```
/
├── index.html                       ← PWA front-end
├── manifest.json                    ← PWA manifest
├── sw.js                            ← Service worker (offline shell)
├── data.json                        ← Written by the Action; read by the PWA
└── scripts/
│   └── fetch_samsara.py             ← Fetches Samsara API, appends to data.json
└── .github/
    └── workflows/
        └── fetch-samsara.yml        ← Scheduled Action (every ~30 s)
```

---

## Setup (one-time)

### 1. Add secrets to your GitHub repo

Go to **Settings → Secrets and variables → Actions → New repository secret**
and add:

| Secret name          | Value                                      |
|----------------------|--------------------------------------------|
| `SAMSARA_API_TOKEN`  | Your Samsara API Bearer token              |
| `SAMSARA_VEHICLE_ID` | Numeric Samsara vehicle ID (e.g. `281474978123456`) |

Your token never appears in the browser or in any committed file.

### 2. Enable GitHub Pages

Go to **Settings → Pages**, set source to **Deploy from a branch**,
pick `main` (or `master`) and `/ (root)`.

### 3. Enable Actions write permissions

Go to **Settings → Actions → General → Workflow permissions**
and select **Read and write permissions**. This lets the Action commit
`data.json` back to the repo.

### 4. Enable the workflow

The workflow runs automatically once you push. You can also trigger it
manually from the **Actions** tab → **Fetch Samsara Data** → **Run workflow**.

---

## How it works

```
[GitHub Action — every 1 min]
  ├─ Pass 1: call Samsara API → append point to data.json
  ├─ sleep 30 s
  └─ Pass 2: call Samsara API → append point to data.json
       └─ git commit + push → data.json updated in repo

[GitHub Pages PWA — every 35 s]
  └─ fetch data.json?_=<timestamp>   (cache-busted)
       ├─ update header (vehicle / driver)
       ├─ update temp + door status cards
       └─ redraw scrollable chart
```

Effective refresh rate: **~30 seconds**. GitHub's cron minimum is 1 minute,
so the Action runs twice per trigger (with a `sleep 30` in between) to
halve the latency.

---

## Samsara API notes

### Temperature
Fetched via `/fleet/vehicles/stats?types=ambientAirTemperatureMilliC`.
Samsara returns millidegrees Celsius; the script converts to °F.

### Door sensor
The script tries `/industrial/assets?parentIds=<vehicleId>` and looks for
any datapoint whose type contains "door" or "cargo". This works if you have
a Samsara CM31/CM32 gateway wired to a door switch.

If your setup is different (e.g. a custom tag or a trailer sensor), edit
`scripts/fetch_samsara.py` — search for the comment `── 4. Door / cargo sensor`.

If no door sensor is found, the door card shows "N/A" and the chart omits
the door state line gracefully.

### Driver
Fetched from `/fleet/vehicles/{id}/driver-assignments`. Requires the
**Read Drivers** scope on your API token.

### Required API token scopes
- Read Vehicle Statistics
- Read Vehicles
- Read Drivers
- Read Industrial Assets (for door sensor)

---

## Staleness warning

If the newest data point is more than 3 minutes old (e.g. the Action is
queued or GitHub is slow), a yellow banner appears on the page.

---

## Customisation

| What to change | Where |
|---------------|-------|
| Goods label | `index.html` — search "Potatoes" |
| Customer name | `index.html` — search "Stater Bros" |
| Temp thresholds (40–45°F) | `index.html` top of `<script>` (`TEMP_LOW`, `TEMP_HIGH`) |
| Rolling history length | `scripts/fetch_samsara.py` → `MAX_POINTS` |
| Poll frequency | `index.html` → `POLL_MS` |

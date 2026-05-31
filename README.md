# ColdChain Monitor PWA

Real-time refrigerated cargo dashboard powered by the Samsara Fleet API.

## Setup

1. **Open `index.html`** and set your credentials at the top of the `<script>` block:
   ```js
   const SAMSARA_API_TOKEN = 'samsara_api_xxxxxxxxxxxxxxxx';
   const VEHICLE_ID        = '281474978000000';  // your Samsara vehicle ID
   ```

2. **Serve over HTTPS** (required for PWA install + service worker):
   ```bash
   # Quick local test with Python
   python3 -m http.server 8080
   # Then open https://localhost:8080 or use a tunnel like ngrok
   ```

3. **Install as PWA**: In Chrome/Edge, click the install icon in the address bar. On iOS Safari, tap Share → Add to Home Screen.

## Samsara API Notes

### Temperature
The app calls `/fleet/vehicles/stats?types=ambientAirTemperature`. Samsara returns temperature in **Celsius** — the app converts to °F automatically.

If your vehicle uses a **trailer sensor** instead, change the endpoint to:
```
/fleet/trailers/stats?trailerIds=YOUR_TRAILER_ID&types=ambientAirTemperature
```

### Door Sensor
The app checks `stats.doorSensor.value === 'open'`. Your sensor's key may differ depending on your gateway/tag configuration. Common alternatives:
- `stats.cargoStatus.value`
- `stats.gatewaySensor.value`

Check the raw API response and adjust the key in `fetchLiveStats()` accordingly.

### Driver
Fetched from `/fleet/drivers?vehicleId=...`. Requires the `read:fleet` scope on your API token.

## Demo Mode
If `SAMSARA_API_TOKEN` is left as the placeholder, the app runs in **demo mode** — simulated temperature (hovering around 42°F with occasional excursions) and random door open events. Great for testing the UI.

## Files
| File | Purpose |
|------|---------|
| `index.html` | Main app — all UI + logic |
| `manifest.json` | PWA metadata |
| `sw.js` | Service worker (offline shell) |

## Future Enhancements (planned)
- Alert/notification on temperature excursion
- Multi-vehicle selector
- CSV export from the chart history
- Speed overlay on the graph

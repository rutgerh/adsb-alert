
# ADSB.lol provider switch

Set environment variable in your UI and worker containers:
```
ADSB_PROVIDER=adsb_lol
```

No code changes elsewhere required; the existing `fetch_states(center_lat, center_lon, radius_km)` now calls ADSB.lol at:
```
GET https://api.adsb.lol/api/aircraft/lat/{lat}/lon/{lon}/dist/{nm}/
```
(ADSBExchange-compatible path). Distance is calculated from your `radius_km`.

## Test with curl
```
curl 'https://api.adsb.lol/api/aircraft/lat/52.155/lon/5.387/dist/50/'
```

## Notes
- ADSB.lol currently advertises **no rate limits** (subject to change). Be kind with your interval.
- If you want to fall back to OpenSky, unset `ADSB_PROVIDER` or set to `opensky`.

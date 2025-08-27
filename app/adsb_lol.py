import math
import time
import requests

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def _nm_from_km(km):
    return km / 1.852

def fetch_states_adsblol_v2(center_lat: float, center_lon: float, radius_km: float, timeout: int = 8):
    """Fetch aircraft around a point from ADSB.lol v2 API and normalize like OpenSky states."""
    # Clamp distance: API expects NM and sensible bounds
    dist_nm = max(1.0, min(250.0, _nm_from_km(float(radius_km))))
    url = f"https://api.adsb.lol/v2/point/{center_lat:.6f}/{center_lon:.6f}/{dist_nm:.0f}"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    j = r.json() or {}
    raw = j.get("ac") or j.get("aircraft") or []

    now = int(time.time())
    states = []
    for a in raw:
        try:
            lat = a.get('lat'); lon = a.get('lon')
            if lat is None or lon is None:
                continue
            icao24 = (a.get('hex') or a.get('icao') or a.get('icao24') or '').lower()
            callsign = (a.get('flight') or a.get('call') or a.get('callsign') or '').strip().upper() or None
            geo_alt = a.get('alt_geom') or a.get('alt') or a.get('geo_altitude')
            baro_alt = a.get('alt_baro') or a.get('baro_altitude')
            vel = a.get('gs') or a.get('speed') or a.get('spd') or a.get('velocity')
            track = a.get('trak') or a.get('track') or a.get('true_track')
            d_km = _haversine_km(center_lat, center_lon, float(lat), float(lon))
            states.append({
                "icao24": icao24,
                "callsign": callsign,
                "origin_country": None,
                "time_position": now,
                "last_contact": now,
                "lon": float(lon),
                "lat": float(lat),
                "baro_altitude": float(baro_alt) if baro_alt is not None else None,
                "geo_altitude": float(geo_alt) if geo_alt is not None else None,
                "on_ground": bool(a.get('onground') or a.get('on_ground') or False),
                "velocity": float(vel) if vel is not None else None,
                "true_track": float(track) if track is not None else None,
                "vertical_rate": a.get('baro_rate') or a.get('vrate') or a.get('vertical_rate'),
                "squawk": a.get('squawk'),
                "spi": False,
                "position_source": None,
                "category": a.get('category'),
                "distance_km": d_km
            })
        except Exception:
            continue

    states.sort(key=lambda s: s.get("distance_km", 9e9))
    return {"states": states, "_source_url": url, "_source_total": len(states)}

# Public alias used by app.main / app.worker
def fetch_states(center_lat, center_lon, radius_km, **kwargs):
    return fetch_states_adsblol_v2(center_lat, center_lon, radius_km, timeout=kwargs.get('timeout', 8))

import os
import json
import time
from .notify import send_telegram
from .adsb_lol import fetch_states_adsblol_v2 as fetch_states

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_FILE = os.environ.get("APP_CONFIG", os.path.join(DATA_DIR, "config.json"))
CACHE_FILE = os.path.join(DATA_DIR, "last_states.json")
ALERT_STATE_FILE = os.path.join(DATA_DIR, "alerts_state.json")

DEFAULT_CFG = {
    "center": {"lat": 52.155, "lon": 5.387},
    "radius_km": 50,
    "monitor_interval_seconds": 25,
    "watchlist": [],
    "telegram": {"token": "", "chat_id": "", "cooldown_minutes": 15},
}

def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default)) if default is not None else None

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def get_cfg():
    c = load_json(CONFIG_FILE, default=DEFAULT_CFG) or DEFAULT_CFG
    try:
        c["center"]["lat"] = float(c["center"]["lat"])
        c["center"]["lon"] = float(c["center"]["lon"])
    except Exception:
        c["center"] = dict(DEFAULT_CFG["center"])
    try:
        c["radius_km"] = float(c.get("radius_km", DEFAULT_CFG["radius_km"]))
    except Exception:
        c["radius_km"] = DEFAULT_CFG["radius_km"]
    return c

def load_alert_state():
    st = load_json(ALERT_STATE_FILE, default={"last_sent": {}})
    return st if isinstance(st, dict) else {"last_sent": {}}

def mark_alert_sent(key: str):
    st = load_alert_state()
    st.setdefault("last_sent", {})[key] = time.time()
    save_json(ALERT_STATE_FILE, st)

def cooldown_ok(key: str, minutes: int) -> bool:
    st = load_alert_state()
    last = st.get("last_sent", {}).get(key, 0)
    return (time.time() - last) > (minutes * 60)

def main():
    print("[worker] starting, provider=", os.getenv("ADSB_PROVIDER", "adsb_lol"))
    while True:
        try:
            c = get_cfg()
            lat = float(c["center"]["lat"])
            lon = float(c["center"]["lon"])
            radius_km = float(c.get("radius_km", 50))
            interval = int(c.get("monitor_interval_seconds", 25))
            if interval < 5:
                interval = 5

            # fetch from provider
            data = fetch_states(center_lat=lat, center_lon=lon, radius_km=radius_km)
            data["_written_at"] = int(time.time())

            # write cache for UI
            save_json(CACHE_FILE, data)
            print(f"[worker] wrote cache with {len(data.get('states') or [])} states")

            # Telegram alerts
            tg = (c.get("telegram") or {})
            token = tg.get("token", "")
            chat_id = tg.get("chat_id", "")
            cooldown = int(tg.get("cooldown_minutes", 15))
            watchlist = {(w or "").strip().upper() for w in c.get("watchlist", []) if (w or "").strip()}

            if token and chat_id and watchlist:
                for s in data.get("states", []):
                    cs = (s.get("callsign") or "").strip().upper()
                    if not cs or cs not in watchlist:
                        continue

                    key = f"{cs}:{s.get('icao24')}"
                    if cooldown_ok(key, cooldown):
                        icao = (s.get("icao24") or "").lower()
                        s_lat = s.get("lat")
                        s_lon = s.get("lon")

                        adsbx_url = f"https://globe.adsbexchange.com/?icao={icao}" if icao else None

                        if s_lat is not None and s_lon is not None:
                            pos_line = f"Positie: {s_lat:.4f}, {s_lon:.4f}\n"
                        else:
                            pos_line = "Positie: ?\n"

                        # bewust mojibake vliegtuigje laten staan
                        msg = (
                            f"âœˆï¸ {cs} gezien binnen {radius_km:.0f} km\n"
                            f"Afstand: {s.get('distance_km', 0):.1f} km\n"
                            f"{pos_line}"
                            f"Hoogte: {s.get('geo_altitude') or s.get('baro_altitude')}\n"
                            f"Snelheid: {s.get('velocity')} m/s"
                        )

                        if adsbx_url:
                            msg += f"\n{adsbx_url}"

                        if send_telegram(token, chat_id, msg):
                            mark_alert_sent(key)

        except Exception as e:
            print("[worker] error:", e)

        time.sleep(int(get_cfg().get("monitor_interval_seconds", 25)))

if __name__ == "__main__":
    main()
185.199.109.133

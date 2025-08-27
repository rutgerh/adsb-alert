from flask import Flask, render_template, jsonify, request
import json, os, time, threading, requests
from .adsb_lol import fetch_states_adsblol_v2 as fetch_states
from .notify import send_telegram

def get_metrics():
    return {"requests_total": 0, "errors_total": 0}

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG_FILE = os.environ.get("APP_CONFIG", os.path.join(DATA_DIR, "config.json"))
CREDENTIALS_FILE = os.environ.get("APP_CREDENTIALS", os.path.join(DATA_DIR, "credentials.json"))
CACHE_FILE = os.path.join(DATA_DIR, "last_states.json")
ALERT_STATE_FILE = os.path.join(DATA_DIR, "alerts_state.json")

START_TS = time.time()
HEALTH = {'last_aircraft_ts': None, 'last_states': 0, 'last_error': None, 'last_source': 'unknown', 'cache_age': None}
lock = threading.Lock()

DEFAULT_CFG = {
    "center": {"lat": 52.155, "lon": 5.387},
    "radius_km": 50,
    "refresh_seconds": 8,
    "monitor_interval_seconds": 25,
    "ui_reads_cache_only": True,
    "cache_max_age_seconds": 45,
    "watchlist": [],
    "telegram": {"token": "", "chat_id": "", "cooldown_minutes": 15},
    }

def ensure_data_dir():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass

def load_json_safe(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        if default is not None:
            try:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=2)
                os.replace(tmp, path)
            except Exception:
                pass
            return json.loads(json.dumps(default))
        return None

def save_json_safe(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False

def cfg():
    ensure_data_dir()
    c = load_json_safe(CONFIG_FILE, default=DEFAULT_CFG)
    try:
        c["center"]["lat"] = float(c["center"]["lat"])
        c["center"]["lon"] = float(c["center"]["lon"])
    except Exception:
        c["center"] = dict(DEFAULT_CFG["center"])
    try:
        c["radius_km"] = float(c.get("radius_km", DEFAULT_CFG["radius_km"]))
    except Exception:
        c["radius_km"] = DEFAULT_CFG["radius_km"]
    if "telegram" not in c or not isinstance(c["telegram"], dict):
        c["telegram"] = dict(DEFAULT_CFG["telegram"])
    if "watchlist" not in c or not isinstance(c["watchlist"], list):
        c["watchlist"] = []
    if "ui_reads_cache_only" not in c:
        c["ui_reads_cache_only"] = True
    if "cache_max_age_seconds" not in c:
        c["cache_max_age_seconds"] = 45
    return c

def get_center():
    c = cfg()["center"]
    return float(c["lat"]), float(c["lon"])

def get_radius():
    return float(cfg().get("radius_km", 50))

def read_cache():
    if not os.path.exists(CACHE_FILE):
        return None, None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = time.time() - data.get("_written_at", data.get("timestamp", time.time()))
        return data, age
    except Exception:
        return None, None

@app.route("/")
def index():
    lat, lon = get_center()
    c = cfg()
    return render_template(
        "index.html",
        center_lat=lat,
        center_lon=lon,
        radius_km=get_radius(),
        refresh_seconds=c.get("refresh_seconds", 8),
        show_test_markers=c.get("show_test_markers", False),
        asset_v=int(time.time()),
    )

@app.route("/api/aircraft")
def api_aircraft():
    c = cfg()
    use_cache_only = bool(c.get("ui_reads_cache_only", True))
    cache_max_age = int(c.get("cache_max_age_seconds", 45))

    data, age = read_cache()
    if data and (use_cache_only or (age is not None and age <= cache_max_age)):
        HEALTH['last_aircraft_ts'] = int(time.time())
        HEALTH['last_states'] = len(data.get('states') or [])
        HEALTH['last_error'] = None
        HEALTH['last_source'] = 'cache'
        HEALTH['cache_age'] = int(age or 0)
        return jsonify(data)

    if not use_cache_only:
        lat, lon = get_center()
        try:
            out = fetch_states(center_lat=lat, center_lon=lon, radius_km=get_radius())
            out["_written_at"] = int(time.time())
            HEALTH['last_aircraft_ts'] = int(time.time())
            HEALTH['last_states'] = len(out.get('states') or [])
            HEALTH['last_error'] = None
            HEALTH['last_source'] = 'live'
            HEALTH['cache_age'] = None
            save_json_safe(CACHE_FILE, out)
            return jsonify(out)
        except Exception as e:
            HEALTH['last_error'] = str(e)[:200]
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    HEALTH['last_error'] = "No cache available yet"
    HEALTH['last_source'] = 'cache-miss'
    HEALTH['cache_age'] = None
    return jsonify({"states": [], "timestamp": int(time.time()), "stale": True})

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    c = cfg()
    token = (c.get("telegram", {}) or {}).get("token") or ""
    token_masked = f"***{token[-4:]}" if token else ""
    resp = {
        "center": c.get("center"),
        "radius_km": c.get("radius_km"),
        "watchlist": c.get("watchlist"),
        "telegram": {
            "token_masked": token_masked,
            "chat_id": (c.get("telegram", {}) or {}).get("chat_id", ""),
            "cooldown_minutes": (c.get("telegram", {}) or {}).get("cooldown_minutes", 15),
        },
        "ui_reads_cache_only": bool(c.get("ui_reads_cache_only", True)),
        "cache_max_age_seconds": int(c.get("cache_max_age_seconds", 45)),
        "provider": os.getenv("ADSB_PROVIDER", "adsb_lol"),
    }
    return jsonify(resp)

@app.route("/api/settings", methods=["POST"])
def api_set_settings():
    body = request.get_json(force=True, silent=True) or {}
    c = cfg()
    updated = False

    with lock:
        if isinstance(body.get("center"), dict):
            try:
                lat = float(body["center"]["lat"]); lon = float(body["center"]["lon"])
                c["center"] = {"lat": lat, "lon": lon}; updated = True
            except Exception:
                pass

        if "radius_km" in body:
            try:
                r = float(body["radius_km"])
                if 1 <= r <= 300:
                    c["radius_km"] = r; updated = True
            except Exception:
                pass

        if isinstance(body.get("watchlist"), list):
            wl = [(w or "").strip().upper() for w in body["watchlist"] if (w or "").strip()]
            c["watchlist"] = sorted(set(wl)); updated = True

        if isinstance(body.get("telegram"), dict):
            tg = c.setdefault("telegram", {})
            if "token" in body["telegram"]:
                t = str(body["telegram"]["token"]).strip()
                if t: tg["token"] = t; updated = True
            if "chat_id" in body["telegram"]:
                tg["chat_id"] = str(body["telegram"]["chat_id"]).strip(); updated = True
            if "cooldown_minutes" in body["telegram"]:
                try:
                    cm = int(body["telegram"]["cooldown_minutes"])
                    if 1 <= cm <= 1440:
                        tg["cooldown_minutes"] = cm; updated = True
                except Exception:
                    pass

        if "ui_reads_cache_only" in body:
            c["ui_reads_cache_only"] = bool(body["ui_reads_cache_only"]); updated = True
        if "cache_max_age_seconds" in body:
            try:
                c["cache_max_age_seconds"] = int(body["cache_max_age_seconds"]); updated = True
            except Exception:
                pass

        if updated:
            save_json_safe(CONFIG_FILE, c)

    return jsonify({"ok": True, "updated": updated})

@app.route("/api/health")
def api_health():
    now = time.time()
    m = get_metrics()
    c = cfg()
    return jsonify({
        "ok": HEALTH.get('last_error') is None,
        "uptime_seconds": int(now - START_TS),
        "last_aircraft_ts": HEALTH.get('last_aircraft_ts'),
        "last_states": HEALTH.get('last_states'),
        "last_error": HEALTH.get('last_error'),
        "center": c.get('center'),
        "radius_km": c.get('radius_km'),
        "provider": os.getenv("ADSB_PROVIDER", "adsb_lol"),
        "source": HEALTH.get('last_source'),
        "cache_age_seconds": HEALTH.get('cache_age'),
        "metrics": {
            "requests_total": m.get('requests_total', 0),
            "errors_total": m.get('errors_total', 0),
            "last_status_code": m.get('last_status_code'),
            "last_retry_after": m.get('last_retry_after'),
            "last_backoff_s": m.get('last_backoff_s', 0)
        }
    })

@app.route("/api/ping")
def api_ping():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

@app.route("/api/settings/test-telegram", methods=["POST"])
def api_test_telegram():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    tg = cfg.get("telegram", {}) if isinstance(cfg, dict) else {}
    token = (tg.get("token") or os.environ.get("TG_TOKEN") or "").strip()
    chat_id = (tg.get("chat_id") or os.environ.get("TG_CHAT_ID") or "").strip()
    ok = False
    if token and chat_id:
        ok = send_telegram(token, chat_id, "🛠️ Test: ADSB-alert testbericht")
    return jsonify({"ok": bool(ok), "has_token": bool(token), "has_chat_id": bool(chat_id)})


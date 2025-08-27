import requests

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=8)
        if r.status_code != 200:
            return False
        try:
            j = r.json()
        except Exception:
            j = {}
        return bool(j.get("ok", True))
    except requests.RequestException:
        return False

"""
panel_tempnumbers.py — TempNumbers Panel (WEBHOOK based)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Polling nahi hai. Panel SMS aate hi is server ko POST karta hai.
Webhook URL (panel me daalna):
    https://<your-koyeb-app>.koyeb.app/<TEMPNUMBERS_WEBHOOK_PATH>

Use: main.py me
    import panel7_scraper
    panel7_scraper.register_routes(app)
"""

import os
import re
import json
import logging
import threading
from datetime import datetime
from collections import deque

import phonenumbers
import pycountry
from flask import Flask, request, jsonify

from shared_storage import shared_storage

logger = logging.getLogger(__name__)

PANEL_ID   = "tempnumbers"
PANEL_NAME = "TempNumbers Panel"

# ===== CONFIG =====
# Ye path secret rakho (provider token nahi bhejta, to yahi suraksha hai)
WEBHOOK_PATH = os.getenv("TEMPNUMBERS_WEBHOOK_PATH", "gen-1lpTArh7dt88").strip("/")
PORT         = int(os.getenv("PORT", "8000"))   # Koyeb PORT env deta hai

SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tempnumbers_seen.txt")

seen_messages = set()
seen_order    = deque(maxlen=200000)
_seen_lock    = threading.Lock()

# ===== PERSISTENT SEEN =====

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                for line in f:
                    uid = line.strip()
                    if uid:
                        seen_messages.add(uid)
                        seen_order.append(uid)
            logger.info(f"[{PANEL_ID}] 📂 Loaded {len(seen_messages)} seen IDs from disk")
        except Exception as e:
            logger.warning(f"[{PANEL_ID}] Could not load seen file: {e}")

def is_message_seen(msg_id: str) -> bool:
    return msg_id in seen_messages

def mark_seen(msg_id: str):
    with _seen_lock:
        seen_messages.add(msg_id)
        seen_order.append(msg_id)
        try:
            with open(SEEN_FILE, "a") as f:
                f.write(msg_id + "\n")
        except Exception as e:
            logger.warning(f"[{PANEL_ID}] Could not save seen ID: {e}")

# ===== HELPERS (zone panel jaise) =====

def mask_number(number: str) -> str:
    return number[:2] + "••" + number[-4:] if len(number) > 6 else number

def country_from_number(num: str):
    try:
        parsed = phonenumbers.parse("+" + num)
        region = phonenumbers.region_code_for_number(parsed)
        country = pycountry.countries.get(alpha_2=region).name
        flag = "".join(chr(127397 + ord(c)) for c in region)
        return country, flag
    except Exception:
        return "Unknown", "🌍"

def extract_otp(message: str):
    text = message.replace("\n", " ").strip()

    m = re.search(r"\b(\d{3})[-\s](\d{3})\b", text)
    if m:
        return m.group(1) + m.group(2)

    m = re.search(r"(otp|code|pin|password|verification|код|кода)[^\d]{0,10}(\d{4,8})", text, re.I)
    if m:
        return m.group(2)

    m = re.search(r"(\d{4,8})[^\w]{0,10}(otp|code|pin|password|verification|код|кода)", text, re.I)
    if m:
        return m.group(1)

    for g in re.findall(r"\b\d{4,8}\b", text):
        if not (1900 <= int(g) <= 2099):
            return g

    return None

def parse_payload():
    """Provider JSON ko string ke andar bhejta hai (double-encoded), isliye 2 baar parse."""
    payload = request.get_json(silent=True)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    return payload if isinstance(payload, dict) else {}

# ===== WEBHOOK HANDLER =====

def webhook_view():
    d = parse_payload().get("data")
    if not isinstance(d, dict):
        logger.warning(f"[{PANEL_ID}] ⚠️ Bad payload: {request.get_data(as_text=True)[:200]}")
        return jsonify(status="bad_payload"), 400

    num     = str(d.get("num") or "").strip()
    sender  = str(d.get("cli") or "Unknown").strip()
    message = str(d.get("sms") or "").strip()
    time_   = str(d.get("datetime") or "").strip()

    if not num and not message:
        return jsonify(status="empty"), 400

    msg_id = f"{time_}_{num}_{message[:50]}"

    if is_message_seen(msg_id):
        return jsonify(status="duplicate"), 200

    otp           = extract_otp(message)
    country, flag = country_from_number(num)

    otp_data = {
        'id':            msg_id,
        'time':          time_,
        'country':       country,
        'flag':          flag,
        'number':        num,
        'masked_number': mask_number(num),
        'sender':        sender,
        'message':       message,
        'otp':           otp,
        'timestamp':     datetime.now().isoformat(),
        'panel':         PANEL_NAME
    }

    try:
        if shared_storage.add_otp(otp_data):
            logger.info(f"[{PANEL_ID}] 📨 {num} | {otp or 'N/A'} | {sender}")
        mark_seen(msg_id)
    except Exception as e:
        logger.error(f"[{PANEL_ID}] ❌ add_otp error: {e}")
        return jsonify(status="error"), 500

    return jsonify(status="ok"), 200

# ===== OPTION 2: main Flask app me route jodo =====

def register_routes(app: Flask):
    load_seen()
    app.add_url_rule(f"/{WEBHOOK_PATH}", endpoint=f"{PANEL_ID}_webhook",
                     view_func=webhook_view, methods=["POST"])
    logger.info(f"[{PANEL_ID}] 🔗 Webhook route registered: /{WEBHOOK_PATH}")

# ===== ENTRY POINT =====

def start_scraper():
    """
    main.py ka loader ise har panel*_scraper.py ke liye chalata hai.
    Webhook ka route main.py me register_routes(app) se judta hai, isliye yahan
    koi alag server NAHI chalana (port conflict hota hai). Sirf seen-IDs load karta hai.

    Alag se akela test karna ho to: TEMPNUMBERS_STANDALONE=1 python panel7_scraper.py
    """
    if os.getenv("TEMPNUMBERS_STANDALONE") != "1":
        logger.info(f"[{PANEL_ID}] ✅ Webhook panel ready (route main.py se juda hai)")
        return

    logger.info(f"[{PANEL_ID}] 🚀 Starting {PANEL_NAME} (standalone webhook server)...")
    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def health():
        return "OK", 200

    register_routes(app)
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    start_scraper()

"""Alerts + operator commands. Always logs to data/outbox.log; also Telegram when data/secrets/telegram.json exists
({"token": "...", "chat_id": 123}). A SEPARATE bot from Hermes (ADR-0012). Commands are accepted only from chat_id.
/resume is deliberately NOT available remotely: only the local operator can lift a halt."""
import json, pathlib, urllib.request, urllib.parse, datetime
from . import halt
ROOT = pathlib.Path(__file__).resolve().parents[1]
import os
CFG = pathlib.Path(os.environ.get("FARMV2_TELEGRAM_CFG", ROOT / "data" / "secrets" / "telegram.json"))
OUTBOX = pathlib.Path(os.environ.get("FARMV2_OUTBOX", ROOT / "data" / "outbox.log"))

def _cfg():
    try: return json.loads(CFG.read_text())
    except Exception: return None

def _api(token, method, **params):
    data = urllib.parse.urlencode(params).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data), timeout=20).read())

def send(level: str, text: str, transport=None):
    line = f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')} [{level}] {text}"
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTBOX, "a") as f: f.write(line + "\n")
    c = _cfg()
    if not c: return False
    try:
        (transport or _api)(c["token"], "sendMessage", chat_id=c["chat_id"], text=f"{'🚨 ' if level in ('HALT','SEV1') else ''}{text}"[:3900])
        return True
    except Exception:
        return False

def poll(L, handlers: dict, transport=None):
    """Fetch commands since last offset. handlers: {"status": fn()->str, "halt": fn(reason)->str, "approve": fn(id,code)->str, "deny": fn(id)->str}."""
    c = _cfg()
    if not c: return 0
    api = transport or _api
    off = int(L.kv_get("tg_offset", 0))
    try: updates = api(c["token"], "getUpdates", offset=off + 1, timeout=0).get("result", [])
    except Exception: return 0
    n = 0
    for u in updates:
        L.kv_set("tg_offset", u["update_id"])
        m = u.get("message") or {}
        if str((m.get("chat") or {}).get("id")) != str(c["chat_id"]): continue     # ignore everyone else
        parts = (m.get("text") or "").strip().split()
        if not parts or not parts[0].startswith("/"): continue
        cmd, args = parts[0][1:].split("@")[0].lower(), parts[1:]
        try:
            if cmd == "status": reply = handlers["status"]()
            elif cmd == "halt": reply = handlers["halt"](" ".join(args) or "operator via telegram")
            elif cmd == "approve" and len(args) == 2: reply = handlers["approve"](args[0], args[1])
            elif cmd == "deny" and len(args) == 1: reply = handlers["deny"](args[0])
            else: reply = "commands: /status /halt [reason] /approve <id> <code> /deny <id>"
        except Exception as e:
            reply = f"error: {e}"
        send("INFO", reply, transport); n += 1
    return n

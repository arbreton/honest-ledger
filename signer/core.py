import hashlib, hmac, json, os, pathlib, subprocess, time

DIR = pathlib.Path(os.environ.get("FARMV2_SIGNER_DIR", pathlib.Path(__file__).resolve().parents[1] / "data" / "signer"))
HALT_FLAG = pathlib.Path(os.environ.get("FARMV2_HALT_DIR", pathlib.Path(__file__).resolve().parents[1] / "data" / "halt")) / "HALT"
PW_FILE = pathlib.Path(os.environ.get("FARMV2_SIGNER_PW", "/dev/shm/farmv2-signer.pw"))
CAST = os.environ.get("FARMV2_CAST", str(pathlib.Path.home() / ".foundry" / "bin" / "cast"))
UINT_BIG = 1 << 200

def canon(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()

def plan_hash(tx: dict) -> str:
    keys = ("chain_id", "nonce", "to", "data", "value", "gas", "max_fee_per_gas", "max_priority_fee_per_gas")
    return hashlib.sha256(canon({k: (str(tx[k]).lower() if k in ("to", "data") else int(tx[k])) for k in keys})).hexdigest()

def receipt_sig(key: bytes, r: dict) -> str:
    body = {k: r[k] for k in ("receipt_id", "plan_hash", "decision", "expires_at", "intent_id")}
    return hmac.new(key, canon(body), hashlib.sha256).hexdigest()

def make_receipt(key: bytes, tx: dict, intent_id: str, ttl_s: int, receipt_id: str) -> dict:
    r = {"receipt_id": receipt_id, "plan_hash": plan_hash(tx), "decision": "ALLOW", "expires_at": int(time.time()) + ttl_s, "intent_id": intent_id}
    r["sig"] = receipt_sig(key, r)
    return r

def _word(data_hex: str, i: int) -> int:
    h = data_hex[2:]
    return int(h[8 + 64 * i: 8 + 64 * (i + 1)] or "0", 16)

def check(tx: dict, receipt: dict, allow: dict, key: bytes, spent: dict, used: set, now=None):
    """Pure validation. Returns (ok, code, detail). Order matters little; every failure is fatal."""
    now = now or time.time()
    if HALT_FLAG.exists():
        return False, "HALTED", ""
    L = allow["limits"]
    if int(tx["chain_id"]) != allow["chain_id"]:
        return False, "CHAIN", ""
    to = (tx.get("to") or "").lower()
    if not to:
        return False, "CREATE", "contract creation is never allowed"
    if receipt.get("decision") != "ALLOW":
        return False, "BAD_RECEIPT", "not ALLOW"
    if not hmac.compare_digest(receipt.get("sig", ""), receipt_sig(key, receipt)):
        return False, "BAD_RECEIPT", "signature"
    if receipt["plan_hash"] != plan_hash(tx):
        return False, "BAD_RECEIPT", "plan hash mismatch"
    if now > receipt["expires_at"]:
        return False, "EXPIRED", ""
    if receipt["receipt_id"] in used:
        return False, "REPLAY", "receipt already used"
    t = allow["targets"].get(to)
    if not t:
        return False, "NOT_ALLOWLISTED", to
    data = tx.get("data", "0x")
    sel = data[:10].lower()
    s = t["selectors"].get(sel)
    if not s:
        return False, "NOT_ALLOWLISTED", f"{t['id']} selector {sel}"
    if int(tx["gas"]) > L["max_gas_limit"]:
        return False, "LIMIT", "gas limit"
    if int(tx["max_fee_per_gas"]) > int(L["max_fee_gwei"] * 1e9):
        return False, "LIMIT", "max fee above absolute cap"
    if int(tx["value"]) > int(L["max_value_wei"]):
        return False, "LIMIT", "value per tx"
    if spent["count"] + 1 > L["daily_tx"] or spent["value"] + int(tx["value"]) > int(L["daily_value_wei"]):
        return False, "LIMIT", "daily cap"
    for idx, rule in s["args"].items():
        w = _word(data, int(idx))
        if rule == "wallet" and w != int(allow["wallet"], 16):
            return False, "RECIPIENT", f"arg {idx} must be the wallet"
        if rule == "spender" and ("0x" + format(w, "040x")) not in t.get("spenders", []):
            return False, "RECIPIENT", "approve spender not allowed"
        if rule == "max_approve" and (w > int(t.get("max_approve", "0")) or w >= UINT_BIG):
            return False, "LIMIT", "approval amount above cap or unlimited"
    return True, "OK", ""

def load_state():
    f = DIR / "state.json"
    today = time.strftime("%Y-%m-%d", time.gmtime())
    st = json.loads(f.read_text()) if f.exists() else {}
    if st.get("day") != today:
        st = {"day": today, "count": 0, "value": 0, "used": st.get("used", [])[-500:]}
    return st

def save_state(st):
    (DIR / "state.json").write_text(json.dumps(st))
    os.chmod(DIR / "state.json", 0o600)

def sign(tx: dict, keystore: str) -> str:
    """cast mktx signs offline (all fields given, no RPC). Password only ever read from the tmpfs file."""
    cmd = [CAST, "mktx", tx["to"], tx["data"], "--keystore", keystore, "--password-file", str(PW_FILE),
           "--chain", str(tx["chain_id"]), "--nonce", str(tx["nonce"]), "--gas-limit", str(tx["gas"]),
           "--gas-price", str(tx["max_fee_per_gas"]), "--priority-gas-price", str(tx["max_priority_fee_per_gas"]),
           "--value", str(tx["value"])]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError("cast mktx failed: " + out.stderr.strip()[:200])
    return out.stdout.strip()

def handle(req: dict, allow: dict, key: bytes, keystore: str):
    if req.get("op") == "status":
        return {"ok": True, "locked": not PW_FILE.exists(), "wallet": allow["wallet"]}
    if req.get("op") != "sign":
        return {"ok": False, "code": "BAD_REQUEST"}
    if not PW_FILE.exists():
        return {"ok": False, "code": "LOCKED"}
    st = load_state()
    ok, code, detail = check(req["tx"], req["receipt"], allow, key, st, set(st["used"]))
    if not ok:
        return {"ok": False, "code": code, "detail": detail}
    raw = sign(req["tx"], keystore)
    st["count"] += 1; st["value"] += int(req["tx"]["value"]); st["used"].append(req["receipt"]["receipt_id"])
    save_state(st)
    return {"ok": True, "raw": raw}

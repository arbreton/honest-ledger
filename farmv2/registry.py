"""Contract registry: checksummed addresses, pinned code hashes, change detection (FR-R3..R5)."""
import json, pathlib
from .keccak import keccak256, is_valid_address, is_checksummed
ROOT = pathlib.Path(__file__).resolve().parents[1]
FILE = ROOT / "registry-data" / "contracts.json"
LOCAL = ROOT / "registry-data" / "local.json"      # git-ignored: your real wallet address, Netlify site id, anything personal

class RegistryError(Exception):
    pass

def local_settings() -> dict:
    try: return json.loads(LOCAL.read_text())
    except Exception: return {}

def _raw(path=FILE) -> dict:
    return json.loads(pathlib.Path(path).read_text())

def load(path=FILE) -> dict:
    d = _raw(path)
    if pathlib.Path(path) == FILE and "wallet" in local_settings():        # override the placeholder wallet with the operator's own
        d["wallet"] = {**d["wallet"], **local_settings()["wallet"]}
    seen = set()
    for c in d["contracts"] + [d["wallet"]]:
        a = c["address"]
        if not is_valid_address(a):
            raise RegistryError(f"malformed address {a!r} ({c.get('id', 'wallet')})")
        if not is_checksummed(a):
            raise RegistryError(f"address not EIP-55 checksummed: {a}")
        if a.lower() in seen:
            raise RegistryError(f"duplicate address {a}")
        seen.add(a.lower())
    return d

def by_id(reg, cid):
    return next(c for c in reg["contracts"] if c["id"] == cid)

def addr(reg, cid) -> str:
    return by_id(reg, cid)["address"]

def code_hash(rpc, address, block="latest") -> str:
    code = rpc.call("eth_getCode", [address, block])
    return "0x" + keccak256(bytes.fromhex(code.removeprefix("0x"))).hex()

def pin_all(rpc, path=FILE) -> dict:
    """Operator action: record current code hash for every contract. Emits the diff vs previous pins."""
    load(path)                                   # validates
    d = _raw(path)                               # write back ONLY the committed file (placeholder wallet stays a placeholder)
    changed = {}
    for c in d["contracts"]:
        h = code_hash(rpc, c["address"])
        if c.get("code_hash") and c["code_hash"] != h:
            changed[c["id"]] = (c["code_hash"], h)
        c["code_hash"] = h
        if h == "0x" + keccak256(b"").hex():
            raise RegistryError(f"{c['id']} has no code at {c['address']}")
    pathlib.Path(path).write_text(json.dumps(d, indent=2) + "\n")
    return changed

def verify_pins(rpc, path=FILE):
    """Returns list of (id, pinned, live) mismatches (R-04). Missing pin counts as mismatch."""
    d = load(path)
    bad = []
    for c in d["contracts"]:
        live = code_hash(rpc, c["address"])
        if c.get("code_hash") != live:
            bad.append((c["id"], c.get("code_hash"), live))
    return bad

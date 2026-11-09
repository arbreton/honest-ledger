"""Exports the signer's static allowlist from registry + policy. The signer never imports farmv2: it reads this file,
whose sha256 the operator approves (data/signer/allowlist.sha256)."""
import json, hashlib, pathlib
from . import registry
from .keccak import selector
ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY = ROOT / "registry-data" / "policy.json"
OUT = ROOT / "data" / "signer" / "allowlist.json"
# argument rules by signature: index -> ("wallet"|"spender"|"max_approve")
ARG_RULES = {
    "deposit(uint256,address)": {1: "wallet"},
    "redeem(uint256,address,address)": {1: "wallet", 2: "wallet"},
    "withdraw(uint256,address,address)": {1: "wallet", 2: "wallet"},
    "approve(address,uint256)": {0: "spender", 1: "max_approve"},
    # static tuples are flattened: word index = field index. Every call that can move value must send it back to the wallet.
    "collect((uint256,address,uint128,uint128))": {1: "wallet"},
    "mint((address,address,int24,int24,int24,uint256,uint256,uint256,uint256,address,uint256,uint160))": {9: "wallet"},
    "exactInputSingle((address,address,int24,address,uint256,uint256,uint256,uint160))": {3: "wallet"},
}

def build(reg=None):
    reg, pol = reg or registry.load(), json.loads(POLICY.read_text())
    a = {"chain_id": pol["chain_id"], "wallet": reg["wallet"]["address"].lower(), "limits": pol["limits"], "targets": {}}
    for c in pol["calls"]:
        addr = registry.addr(reg, c["contract"]).lower()
        a["targets"][addr] = {"id": c["contract"], "selectors": {
            selector(s): {"sig": s, "args": ARG_RULES.get(s, {})} for s in c["sigs"]}}
        if c["contract"] in pol["max_approve"]:
            a["targets"][addr]["max_approve"] = pol["max_approve"][c["contract"]]
        a["targets"][addr]["spenders"] = [registry.addr(reg, x).lower() for x in pol["approve_spenders"].get(c["contract"], [])]
    return a

def export(path=OUT, reg=None):
    a = build(reg)
    body = json.dumps(a, indent=1, sort_keys=True)
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(body)
    return hashlib.sha256(body.encode()).hexdigest()

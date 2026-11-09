"""Adversarial canaries run through the REAL Risk Gate. Any canary that is allowed = Sev-1 (SS-5)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from farmv2.rules import Plan, State, evaluate

GOOD = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
def base_state(**kw):
    s = State(allow={GOOD.lower(): {"selectors": {"0x095ea7b3", "0x6e553f65"}, "code_hash_ok": True}}, nav_usd=66.0, head_block=1000)
    for k, v in kw.items():
        setattr(s, k, v)
    return s

def base_plan(**kw):
    p = Plan(to=GOOD, selector="0x6e553f65", notional_usd=2.0, max_fee_gwei=0.01, gas_limit=250_000, eth_usd=2100.0,
             benefit_usd=0.5, other_cost_usd=0.0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p

CANARIES = {
    "v1-8gwei-swap (tx 0x130bdc9f)": (base_plan(max_fee_gwei=8.0, gas_limit=208_834, notional_usd=0.96, benefit_usd=0.0), base_state()),
    "unlimited approval": (base_plan(approvals=[{"spender": GOOD, "amount": (1 << 256) - 1}]), base_state()),
    "unknown contract": (base_plan(to="0x1111111111111111111111111111111111111111"), base_state()),
    "malformed allowlist address (v1 veAERO, 41 hex chars)": (base_plan(to="0xebf418fe2512e7e6bd9b87a8f0f294a5cdc67e6b4"), base_state()),
    "selector not allowed": (base_plan(selector="0xa9059cbb"), base_state()),
    "code hash changed": (base_plan(), base_state(allow={GOOD.lower(): {"selectors": None, "code_hash_ok": False}})),
    "halted": (base_plan(), base_state(halted=True)),
    "stale reconciliation": (base_plan(), base_state(recon_age_min=999)),
    "stale price": (base_plan(), base_state(price_age_min=60)),
    "rpc disagreement": (base_plan(), base_state(rpc_agree=False)),
    "value to non-registry recipient": (base_plan(recipient_outside_registry=True), base_state()),
    "over per-tx cap": (base_plan(notional_usd=40.0, benefit_usd=5.0), base_state(nav_usd=500.0)),
    "$2 position with 35-year payback": (base_plan(benefit_usd=0.00005), base_state()),
    "expired plan": (base_plan(expires_block=10), base_state()),
    "approval spender not in registry": (base_plan(approvals=[{"spender": "0x2222222222222222222222222222222222222222", "amount": 2_000_000}]), base_state()),
    "expensive plan labelled 'canary'": (base_plan(purpose="canary", max_fee_gwei=0.05, gas_limit=900_000, eth_usd=3000.0, benefit_usd=0.0), base_state()),
    "multi-call plan with one non-allowlisted step": (base_plan(calls=[(GOOD, "0x095ea7b3"), ("0x1111111111111111111111111111111111111111", "0x6e553f65")]), base_state()),
    "failed simulation": (base_plan(sim_ok=False), base_state()),
}

def run():
    out = []
    for name, (plan, state) in CANARIES.items():
        decision, res = evaluate(plan, state)
        blocked_by = [r.rule for r in res if not r.ok]
        out.append((name, decision, blocked_by, decision == "REJECT"))
    # control: a healthy plan must be allowed to a human or through, else the gate is simply rejecting everything
    d, _ = evaluate(base_plan(), base_state())
    out.append(("CONTROL healthy $2 plan is not rejected", d, [], d in ("ALLOW", "NEEDS_HUMAN")))
    return out

if __name__ == "__main__":
    res = run()
    for n, d, b, ok in res:
        print(("PASS " if ok else "FAIL ") + f"{n}: {d} {b}")
    sys.exit(0 if all(ok for *_, ok in res) else 1)

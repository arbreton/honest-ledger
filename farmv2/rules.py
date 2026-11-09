"""Risk Gate rules (LLD §5). Pure functions: (plan, state) -> RuleResult. Deterministic, no network, no LLM.
S0 limits are explicit constants so changing them is a reviewed code change (ADR-0004)."""
from dataclasses import dataclass, field
from .keccak import is_valid_address

BLOCK, HUMAN = "BLOCK", "HUMAN"
ABS_MAX_FEE_GWEI = 0.05          # R-05 absolute cap on Base (reviewed per chain)
PER_TX_USD, DAILY_USD, AUTO_APPROVE_USD = 25.0, 50.0, 5.0
INTERNAL_PER_TX_USD, INTERNAL_NAV_FRACTION = 60.0, 0.95   # internal rebalances may touch most of NAV, never more than $60
GAS_PCT_OF_NOTIONAL = 0.01
PAYBACK_MULT = 3.0
UINT_MAX = (1 << 256) - 1
CANARY_MAX_COST_USD = 0.10

@dataclass(frozen=True)
class RuleResult:
    rule: str
    ok: bool
    severity: str
    msg: str

@dataclass
class Plan:
    to: str
    selector: str
    notional_usd: float
    max_fee_gwei: float
    gas_limit: int
    eth_usd: float
    approvals: list = field(default_factory=list)       # [{"spender":..., "amount": int}]
    benefit_usd: float = 0.0                            # expected benefit over the holding horizon
    other_cost_usd: float = 0.0                         # fees + slippage
    recipient_outside_registry: bool = False
    expires_block: int = 0
    sim_ok: bool = True
    calls: list = field(default_factory=list)           # [(to, selector)] for multi-call plans
    expected_fee_gwei: float = 0.0                       # what the tx will actually pay (base + tip); 0 = assume worst case (the cap)
    internal: bool = False                               # value moves only between the wallet's own positions (every recipient = wallet)
    purpose: str = ""                                   # "canary" = pipeline test, cost-capped instead of payback-tested

@dataclass
class State:
    halted: bool = False
    recon_ok: bool = True
    recon_age_min: float = 0.0
    allow: dict = field(default_factory=dict)           # address.lower() -> {"selectors": set|None, "code_hash_ok": bool}
    base_fee_p50_gwei: float = 0.005
    spent_today_usd: float = 0.0
    price_age_min: float = 0.0
    rpc_agree: bool = True
    head_block: int = 0
    nav_usd: float = 0.0

def gas_cap_gwei(s: State) -> float:
    return min(3 * s.base_fee_p50_gwei + 0.001, ABS_MAX_FEE_GWEI)

def gas_cost_usd(p: Plan) -> float:
    """Cost tests (R-06/R-07) use the price the tx will really pay; R-05 separately bounds the worst case."""
    price = min(p.max_fee_gwei, p.expected_fee_gwei) if p.expected_fee_gwei > 0 else p.max_fee_gwei
    return p.gas_limit * price * 1e-9 * p.eth_usd

def evaluate(p: Plan, s: State):
    R = []
    add = lambda rule, ok, sev, msg: R.append(RuleResult(rule, bool(ok), sev, msg))
    add("R-01", not s.halted, BLOCK, "global halt is set" if s.halted else "not halted")
    add("R-02", s.recon_ok and s.recon_age_min <= 30, BLOCK, f"reconciliation ok={s.recon_ok} age={s.recon_age_min:.0f}m")
    calls = p.calls or [(p.to, p.selector)]
    def _ent(to): return s.allow.get(to.lower()) if is_valid_address(to) else None
    ents = [(_ent(to), to, sel) for to, sel in calls]
    r3 = all(e is not None and (e.get("selectors") is None or sel in e["selectors"]) for e, _, sel in ents)
    add("R-03", r3, BLOCK, "all targets/selectors allowlisted" if r3 else "target or selector not allowlisted/malformed: " + ",".join(f"{to}:{sel}" for e, to, sel in ents if e is None or (e.get("selectors") is not None and sel not in e["selectors"])))
    r4 = all(bool(e and e.get("code_hash_ok")) for e, _, _ in ents)
    add("R-04", r4, BLOCK, "code hashes match pins" if r4 else "code hash unpinned/changed")
    cap = gas_cap_gwei(s)
    add("R-05", p.max_fee_gwei <= cap, BLOCK, f"max fee {p.max_fee_gwei} gwei vs cap {cap:.4f}")
    g = gas_cost_usd(p)
    add("R-06", p.notional_usd <= 0 or g <= GAS_PCT_OF_NOTIONAL * p.notional_usd or g < 0.01, BLOCK,
        f"gas ${g:.4f} vs {GAS_PCT_OF_NOTIONAL:.0%} of notional ${p.notional_usd:.2f}")
    cost = g + p.other_cost_usd
    if p.purpose == "canary":
        add("R-07", cost <= CANARY_MAX_COST_USD, BLOCK, f"canary cost ${cost:.4f} vs cap ${CANARY_MAX_COST_USD}")
    else:
        add("R-07", p.benefit_usd - cost > 0 and p.benefit_usd >= PAYBACK_MULT * cost, BLOCK,
            f"benefit ${p.benefit_usd:.4f} vs {PAYBACK_MULT}x cost ${cost:.4f}")
    add("R-08", p.sim_ok, BLOCK, "simulation succeeded" if p.sim_ok else "simulation failed")
    add("R-09", not p.recipient_outside_registry, BLOCK, "value leaves to non-registry address" if p.recipient_outside_registry else "recipients in registry")
    bad = [x for x in p.approvals if int(x["amount"]) >= UINT_MAX // 2 or not is_valid_address(x["spender"]) or x["spender"].lower() not in s.allow]
    add("R-10", not bad, BLOCK, "approval unlimited or spender malformed" if bad else "approvals exact")
    lim = min(PER_TX_USD, 0.25 * s.nav_usd) if s.nav_usd else PER_TX_USD
    if p.internal: lim = min(INTERNAL_PER_TX_USD, INTERNAL_NAV_FRACTION * s.nav_usd) if s.nav_usd else INTERNAL_PER_TX_USD
    add("R-11", p.notional_usd <= lim, BLOCK, f"notional ${p.notional_usd:.2f} vs per-tx limit ${lim:.2f}")
    dl = min(DAILY_USD, 0.5 * s.nav_usd) if s.nav_usd else DAILY_USD
    add("R-12", p.internal or s.spent_today_usd + p.notional_usd <= dl, BLOCK, f"daily ${s.spent_today_usd + p.notional_usd:.2f} vs ${dl:.2f}")
    add("R-15", s.price_age_min <= 5, BLOCK, f"price age {s.price_age_min:.0f}m")
    add("R-16", s.rpc_agree, BLOCK, "RPC providers agree" if s.rpc_agree else "RPC providers disagree")
    add("R-18", p.expires_block == 0 or s.head_block <= p.expires_block, BLOCK, "plan not expired")
    add("R-21", p.notional_usd <= AUTO_APPROVE_USD, HUMAN, f"auto-approve limit ${AUTO_APPROVE_USD}")
    blocked = [r for r in R if not r.ok and r.severity == BLOCK]
    human = [r for r in R if not r.ok and r.severity == HUMAN]
    decision = "REJECT" if blocked else ("NEEDS_HUMAN" if human else "ALLOW")
    return decision, R

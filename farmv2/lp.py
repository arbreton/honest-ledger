"""Concentrated-LP management for the Aerodrome Slipstream WETH/USDC position: exit and recenter plans.
Pure math + calldata. Safety comes from: fork simulation, an on-chain slippage floor on every swap/mint/decrease,
signer recipient rules (everything returns to the wallet), exact approvals revoked at the end, and a post-sim value probe."""
import time
from . import registry, nav
from .abi import call_data, word, words, u
from .planner import Call, Plan, approve_exact

SPACING = 50
MAX_U128 = (1 << 128) - 1
S_DECREASE = "decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))"
S_COLLECT = "collect((uint256,address,uint128,uint128))"
S_BURN = "burn(uint256)"
S_MINT = "mint((address,address,int24,int24,int24,uint256,uint256,uint256,uint256,address,uint256,uint160))"
S_SWAP = "exactInputSingle((address,address,int24,address,uint256,uint256,uint256,uint160))"

def align_down(t, s=SPACING): return (t // s) * s
def align_up(t, s=SPACING): return -((-t) // s) * s

def target_range(tick, width=800, spacing=SPACING):
    lo, hi = align_down(tick - width, spacing), align_up(tick + width, spacing)
    assert lo < tick < hi, (lo, tick, hi)
    return lo, hi

def px_from_sqrt(sq): return (sq / 2**96) ** 2 * 1e12     # USDC per WETH

def weth_value_fraction(sq, lo, hi):
    a0, a1 = nav.lp_amounts(10**20, sq, lo, hi)
    v0 = a0 / 1e18 * px_from_sqrt(sq)
    return v0 / (v0 + a1 / 1e6)

def liquidity_for(sq, lo, hi, d0, d1):
    sa, sb = int(1.0001 ** (lo / 2) * 2**96), int(1.0001 ** (hi / 2) * 2**96)
    l0 = d0 * sq * sb // ((sb - sq) * 2**96) if sq < sb else 0
    l1 = d1 * 2**96 // (sq - sa) if sq > sa else 0
    return min(x for x in (l0, l1) if x > 0)

def read_state(rpc, reg, token_id, block):
    """Everything the planner needs, from the chain at `block`."""
    npm, pool = registry.addr(reg, "aero-cl-npm"), registry.addr(reg, "aero-cl-weth-usdc")
    wallet = reg["wallet"]["address"]
    pos = nav.read_position(rpc, npm, token_id, block)
    sq, tick = nav._pool_state(rpc, pool, block)
    a0, a1 = nav.lp_amounts(pos["liq"], sq, pos["tick_lo"], pos["tick_hi"])
    f0, f1 = nav.uncollected_fees(rpc, pool, pos, tick, block)
    bal = lambda t: u(words(rpc.eth_call(t, call_data("balanceOf(address)", wallet), block))[0])
    return {"token_id": token_id, "pos": pos, "sq": sq, "tick": tick, "px": px_from_sqrt(sq), "a0": a0, "a1": a1, "f0": f0, "f1": f1,
            "w_weth": bal(registry.addr(reg, "weth")), "w_usdc": bal(registry.addr(reg, "usdc")), "tick_spacing": SPACING}

def _exit_calls(reg, st, deadline, slip):
    npm, wallet = registry.addr(reg, "aero-cl-npm"), reg["wallet"]["address"]
    tid, liq = st["token_id"], st["pos"]["liq"]
    mn0, mn1 = int(st["a0"] * (1 - 3 * slip)), int(st["a1"] * (1 - 3 * slip))      # floor against pool-price manipulation
    return [Call(npm, call_data(S_DECREASE, tid, liq, mn0, mn1, deadline), 0, S_DECREASE, "LP remove liquidity"),
            Call(npm, call_data(S_COLLECT, tid, wallet, MAX_U128, MAX_U128), 0, S_COLLECT, "LP collect"),
            Call(npm, call_data(S_BURN, tid), 0, S_BURN, "LP burn")]

def _value(w_weth, w_usdc, px): return w_weth / 1e18 * px + w_usdc / 1e6

def _probe_factory(reg, st, kind, rng=None, max_loss=0.012, extra_eth_wei=0):
    """Runs against the fork AFTER the calls: position state and total value must be what the plan promised."""
    npm, pool = registry.addr(reg, "aero-cl-npm"), registry.addr(reg, "aero-cl-weth-usdc")
    wallet, weth, usdc = reg["wallet"]["address"], registry.addr(reg, "weth"), registry.addr(reg, "usdc")
    before = _value(st["w_weth"] + st["a0"] + st["f0"] + extra_eth_wei, st["w_usdc"] + st["a1"] + st["f1"], st["px"])
    def probe(f, _wallet):
        n = u(words(f.eth_call(npm, call_data("balanceOf(address)", wallet), None))[0])
        bal = lambda t: u(words(f.eth_call(t, call_data("balanceOf(address)", wallet), None))[0])
        sq, tick = nav._pool_state(f, pool, None)
        w_weth, w_usdc = bal(weth), bal(usdc)
        pos_val = 0.0
        if kind == "exit":
            if n != 0: return False, f"old NFT still held (balance {n})"
        else:
            if n != 1: return False, f"expected exactly 1 LP NFT after recenter, found {n}"
            tid = u(words(f.eth_call(npm, call_data("tokenOfOwnerByIndex(address,uint256)", wallet, 0), None))[0])
            p = nav.read_position(f, npm, tid, None)
            if (p["tick_lo"], p["tick_hi"]) != rng: return False, f"new range {(p['tick_lo'], p['tick_hi'])} != planned {rng}"
            if p["liq"] <= 0: return False, "new position has no liquidity"
            a0, a1 = nav.lp_amounts(p["liq"], sq, p["tick_lo"], p["tick_hi"])
            pos_val = _value(a0, a1, px_from_sqrt(sq))
        after = _value(w_weth, w_usdc, px_from_sqrt(sq)) + pos_val
        loss = (before - after) / before
        if loss > max_loss: return False, f"value loss {loss:.2%} exceeds {max_loss:.1%} (before ${before:.2f}, after ${after:.2f})"
        return True, f"value preserved: ${before:.2f} -> ${after:.2f} ({-loss:+.2%})"
    return probe

def plan_exit(reg, st, deadline=None, slip=0.005):
    deadline = deadline or int(time.time()) + 1800
    npm = registry.addr(reg, "aero-cl-npm")
    p = Plan(_exit_calls(reg, st, deadline, slip), None, [], _value(st["a0"] + st["f0"], st["a1"] + st["f1"], st["px"]))
    p.probe = _probe_factory(reg, st, "exit"); p.internal = True; p.est_cost_usd = p.notional_usd * 0.0015
    return p

def plan_recenter(reg, st, width=800, slip=0.005, deadline=None, extra_eth_wei=0):
    deadline = deadline or int(time.time()) + 1800
    npm, router = registry.addr(reg, "aero-cl-npm"), registry.addr(reg, "aero-cl-swap-router")
    weth, usdc, wallet = registry.addr(reg, "weth"), registry.addr(reg, "usdc"), reg["wallet"]["address"]
    px, sq = st["px"], st["sq"]
    lo, hi = target_range(st["tick"], width)
    calls = ([Call(weth, call_data("deposit()"), int(extra_eth_wei), "deposit()", "wrap idle ETH")] if extra_eth_wei else []) + _exit_calls(reg, st, deadline, slip)
    W = st["w_weth"] + int(extra_eth_wei) + int((st["a0"] + st["f0"]) * (1 - 3 * slip))          # conservative estimates of what the wallet will hold
    U = st["w_usdc"] + int((st["a1"] + st["f1"]) * (1 - 3 * slip))
    f = weth_value_fraction(sq, lo, hi)
    V = _value(W, U, px)
    diff = W / 1e18 * px - f * V                                            # >0: too much ETH, sell some
    swap_cost = 0.0
    if abs(diff) > 0.25:
        if diff > 0:
            amt = int(diff / px * 1e18); out_min = int(amt / 1e18 * px * 1e6 * (1 - slip - 0.0005))
            calls += [approve_exact(weth, router, amt),
                      Call(router, call_data(S_SWAP, weth, usdc, SPACING, wallet, deadline, amt, out_min, 0), 0, S_SWAP, "swap WETH->USDC")]
            W -= amt; U += out_min
        else:
            amt = int(-diff * 1e6); out_min = int(amt / 1e6 / px * 1e18 * (1 - slip - 0.0005))
            calls += [approve_exact(usdc, router, amt),
                      Call(router, call_data(S_SWAP, usdc, weth, SPACING, wallet, deadline, amt, out_min, 0), 0, S_SWAP, "swap USDC->WETH")]
            U -= amt; W += out_min
        swap_cost = abs(diff) * (0.0005 + slip / 2)
    d0, d1 = int(W * 0.995), int(U * 0.995)
    L = liquidity_for(sq, lo, hi, d0, d1)
    e0, e1 = nav.lp_amounts(L, sq, lo, hi)
    m0, m1 = int(e0 * 0.97), int(e1 * 0.97)
    calls += [approve_exact(weth, npm, d0), approve_exact(usdc, npm, d1),
              Call(npm, call_data(S_MINT, weth, usdc, SPACING, lo, hi, d0, d1, m0, m1, wallet, deadline, 0), 0, S_MINT, f"LP mint [{lo},{hi}]"),
              approve_exact(weth, npm, 0), approve_exact(usdc, npm, 0)]            # revoke whatever the mint did not consume
    for c in calls:
        if c.sig == "approve(address,uint256)" and c.note.endswith(" 0"): c.note = "revoke"
    notional = _value(st["w_weth"] + st["a0"] + st["f0"] + int(extra_eth_wei), st["w_usdc"] + st["a1"] + st["f1"], px)
    p = Plan(calls, None, [(weth, router), (usdc, router), (weth, npm), (usdc, npm)], notional,
             [{"spender": npm, "amount": d0}, {"spender": npm, "amount": d1}] + ([{"spender": router, "amount": amt}] if abs(diff) > 0.25 else []))
    p.probe = _probe_factory(reg, st, "recenter", (lo, hi), extra_eth_wei=int(extra_eth_wei)); p.internal = True
    p.est_cost_usd = swap_cost + notional * 0.002
    p.range = (lo, hi)
    return p

def build(reg, rpc, action, params, block=None):
    block = block or rpc.block_number() - 2
    st = read_state(rpc, reg, int(params["token_id"]), block)
    if action == "lp_exit": return plan_exit(reg, st)
    if action == "lp_recenter": return plan_recenter(reg, st, int(params.get("width", 800)))
    if action == "lp_resize": return plan_recenter(reg, st, int(params.get("width", 800)), extra_eth_wei=int(params["extra_eth_wei"]))
    raise ValueError(action)

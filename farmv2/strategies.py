"""Strategies are deterministic: snapshot in, intents + 'considered' notes out. They never touch keys or the network (FR-S1).
At $66 most cycles correctly conclude 'do nothing': the 3x payback rule is the product."""
import json, time
from . import registry, airdrops, forecasts, notify
from .abi import call_data, words, u
from .ledger import now

GAS_UNITS_PARK = 520_000          # approve + vault deposit, measured on-chain in v1 (nonce 18-20)
MIN_PARK_USD, APY_HAIRCUT, APY_CAP, MIN_APY = 1.0, 0.7, 0.08, 0.02
GAS_RESERVE_USD = 3.0
LP_OOR_MIN_SECONDS, LP_COOLDOWN_S, LP_MIN_FEE_APR, LP_HORIZON_DAYS = 3600, 86400, 0.15, 14

def measure_vault_apy(rpc, reg, head, days=7):
    """Annualised share-price growth over the last `days` of REAL time (block timestamps, not block counts)."""
    from . import timeutil
    vault = registry.addr(reg, "morpho-gauntlet-usdc-prime")
    q = lambda b: u(words(rpc.eth_call(vault, call_data("convertToAssets(uint256)", 10**24), b))[0])
    try:
        b0 = timeutil.block_at_age(rpc, head, int(days * 86400))
        elapsed = timeutil.ts(rpc, head) - timeutil.ts(rpc, b0)
        p1, p0 = q(head), q(b0)
    except Exception:
        return None
    return (p1 / p0) ** (365 * 86400 / elapsed) - 1 if p0 and elapsed > 3600 else None

def lp_fee_rate_usd_day(rpc, reg, p, head, days=7):
    """Gross fee income per day from pool fee-growth accounting over real elapsed time (0 if it cannot be measured)."""
    from . import nav as navmod, timeutil
    try:
        npm, pool = registry.addr(reg, "aero-cl-npm"), registry.addr(reg, "aero-cl-weth-usdc")
        b0 = timeutil.block_at_age(rpc, head, int(days * 86400))
        el = (timeutil.ts(rpc, head) - timeutil.ts(rpc, b0)) / 86400
        def fees(b):
            pos = navmod.read_position(rpc, npm, p["id"], b); _, tick = navmod._pool_state(rpc, pool, b)
            return navmod.uncollected_fees(rpc, pool, pos, tick, b)
        (a0, a1), (c0, c1) = fees(b0), fees(head)
        return max(0.0, ((c0 - a0) / 1e18 * p_px(p, rpc, reg, head) + (c1 - a1) / 1e6) / el)
    except Exception:
        return 0.0

def p_px(p, rpc, reg, head):
    from . import prices
    return prices.chainlink_eth_usd(rpc, reg, head)

def snapshot(L, rpc, reg, head, nav_data, bf_p50):
    wallet = reg["wallet"]["address"]
    usdc = u(words(rpc.eth_call(registry.addr(reg, "usdc"), call_data("balanceOf(address)", wallet), head, quorum=True))[0])
    try:
        from . import yields
        llama = yields.llama_apy_for_held_vault(yields.fetch()["rows"])
    except Exception:
        llama = None
    for p in nav_data["lp"]:
        p["fee_rate_usd_day"] = lp_fee_rate_usd_day(rpc, reg, p, head)
    return {"llama_apy": llama, "head": head, "eth_usd": nav_data["eth_usd"], "nav": nav_data["nav_usd"], "usdc": usdc,
            "eth_wei": rpc.balance(wallet, head, quorum=True), "lp": nav_data["lp"], "bf_p50": bf_p50,
            "vault_apy": measure_vault_apy(rpc, reg, head, days=7)}

def _gas_usd(snap, units):
    return units * max(snap["bf_p50"], 0.006) * 1e-9 * snap["eth_usd"] + 0.01   # +L1 data fee allowance

def usdc_park(snap):
    apy, idle = snap["vault_apy"], snap["usdc"]
    idle_usd = idle / 1e6
    if idle_usd < MIN_PARK_USD:
        return None, ("usdc-park", "idle USDC below minimum", "none", f"idle ${idle_usd:.2f} < ${MIN_PARK_USD:.0f}")
    ll = snap.get("llama_apy")
    if apy is None or apy < MIN_APY:
        conflict = f"; DeFiLlama advertises {ll:.1%} for this vault: sources disagree, we trust the on-chain share price" if ll else ""
        return None, ("usdc-park", f"idle ${idle_usd:.2f}, on-chain vault yield {apy:.2%}/yr (30d)" if apy is not None else f"idle ${idle_usd:.2f}, yield unavailable", "none",
                      "on-chain yield below the 2% floor, not worth the move" + conflict)
    eff = min(apy * APY_HAIRCUT, APY_CAP)
    benefit, cost = idle_usd * eff, _gas_usd(snap, GAS_UNITS_PARK)
    if benefit < 3 * cost:
        return None, ("usdc-park", f"idle ${idle_usd:.2f}, APY {apy:.1%}", "none", f"benefit ${benefit:.3f}/yr < 3x cost ${cost:.3f}")
    return {"strategy": "usdc-park", "action": "vault_deposit", "params": {"vault": "morpho-gauntlet-usdc-prime", "assets": idle},
            "notional_usd": idle_usd, "benefit_usd": benefit, "horizon_days": 365}, \
           ("usdc-park", f"idle ${idle_usd:.2f}, APY {apy:.1%} (x{APY_HAIRCUT} haircut)", "vault_deposit", f"benefit ${benefit:.3f}/yr vs cost ${cost:.3f}")

def lp_manage(L, snap):
    """Trigger rules (operator-approved 2026-11-08): act only when the LP has been OUT of range for >= 60 min, at most once per 24h.
    Recenter if recent fee income still justifies it (>= 15% APR), otherwise exit. In range: do nothing."""
    notes, intent = [], None
    for p in snap["lp"]:
        value = sum(h for h in (p["weth"] * snap["eth_usd"] + p["usdc"],)) + p["fees_usd"]
        rate = p.get("fee_rate_usd_day", 0.0); apr = rate * 365 / value if value else 0
        key = f"lp_oor_{p['id']}"
        if p["in_range"]:
            L.kv_set(key, 0)
            notes.append(("lp-manage", f"LP #{p['id']} in range, {p['margin_ticks']} ticks (~{p['margin_ticks'] / 100:.1f}%) from the nearest edge, fees ${p['fees_usd']:.2f}, run-rate ${rate:.3f}/day ({apr:.0%} APR)",
                          "none", "in range: nothing to do. Acts only after 60 min out of range"))
            if p["margin_ticks"] < 200 and time.time() - float(L.kv_get(f"lp_alert_{p['id']}", 0)) > 86400:
                notify.send("INFO", f"LP #{p['id']} is within ~{p['margin_ticks'] / 100:.1f}% of leaving its range. If it stays out 60 min the strategy will {'recenter' if apr >= LP_MIN_FEE_APR else 'exit'} (pre-approved).")
                L.kv_set(f"lp_alert_{p['id']}", time.time())
            continue
        since = float(L.kv_get(key, 0)) or time.time()
        L.kv_set(key, since)
        waited = time.time() - since
        if waited < LP_OOR_MIN_SECONDS:
            notes.append(("lp-manage", f"LP #{p['id']} OUT of range for {waited / 60:.0f} min", "wait", f"hysteresis: acts after {LP_OOR_MIN_SECONDS // 60} min out of range")); continue
        if time.time() - float(L.kv_get("lp_last_action", 0)) < LP_COOLDOWN_S:
            notes.append(("lp-manage", f"LP #{p['id']} OUT of range {waited / 3600:.1f} h", "wait", "24h cooldown since the last LP action")); continue
        action = "lp_recenter" if apr >= LP_MIN_FEE_APR else "lp_exit"
        benefit = rate * LP_HORIZON_DAYS if action == "lp_recenter" else value * 0.055 * LP_HORIZON_DAYS / 365
        intent = {"strategy": "lp-manage", "action": action, "params": {"token_id": p["id"]}, "notional_usd": value, "benefit_usd": benefit, "horizon_days": LP_HORIZON_DAYS}
        notes.append(("lp-manage", f"LP #{p['id']} OUT of range {waited / 3600:.1f} h, fee run-rate {apr:.0%} APR", action, f"{'fees justify a recenter' if action == 'lp_recenter' else 'fees too low, exit to wallet (usdc-park then parks the USDC)'}: expected benefit ${benefit:.3f} over {LP_HORIZON_DAYS}d"))
    return intent, notes

def core_hold(L, snap):
    eth_usd = snap["eth_wei"] / 1e18 * snap["eth_usd"]
    if eth_usd < GAS_RESERVE_USD and time.time() - float(L.kv_get("gas_alert", 0)) > 86400:
        notify.send("INFO", f"ETH gas reserve is low (${eth_usd:.2f})."); L.kv_set("gas_alert", time.time())
    return [("core-hold", f"ETH ${eth_usd:.2f} (gas reserve floor ${GAS_RESERVE_USD:.0f})", "none", "buy-and-hold is the benchmark; no action")]

def airdrop_options(L):
    notes = []
    for p in airdrops.programs():
        ev = airdrops.marginal_ev(p)
        notes.append(("airdrop-options", f"{p['name']} [{p['evidence_class']}]", "none", f"marginal EV ${ev:.2f}: " + ("criteria published but no points data" if p["criteria_published"] else "no published criteria") + "; no new spend"))
    forecasts.create(L, "airdrop-options", "Base publishes official token/airdrop criteria by 2027-06-30", 0.15, "E1", "2027-06-30")
    return notes

def run(L, rpc, reg, ex, snap, dry=False):
    out, notes = [], []
    intent, note = usdc_park(snap)
    notes.append(note)
    if intent:
        forecasts.create(L, "usdc-park", "Morpho vault measured APY stays >= 3% over the next 30 days", 0.75, "E2", time.strftime("%Y-%m-%d", time.gmtime(time.time() + 30 * 86400)), "vault_apy_gte", {"threshold": 0.03})
        out.append(ex.submit(intent) if not dry else {"intent": intent, "state": "DRY-RUN"})
    lp_intent, lp_notes = lp_manage(L, snap)
    notes += lp_notes
    from . import executor as _ex
    if lp_intent and not dry and not _ex.allowlist_current():
        notes.append(("lp-manage", f"trigger fired ({lp_intent['action']}) but the signer allowlist for LP actions is not yet operator-approved", "blocked",
                      "run ops/approve-allowlist.sh --yes (widens what the signer may sign; needs the operator)"))
        if time.time() - float(L.kv_get("lp_allowlist_alert", 0)) > 6 * 3600:
            notify.send("INFO", "LP left its range and the strategy wants to " + lp_intent["action"] + ", but the signer allowlist is not approved for LP actions. Run: ops/approve-allowlist.sh --yes")
            L.kv_set("lp_allowlist_alert", time.time())
        lp_intent = None
    if lp_intent:
        res = ex.submit(lp_intent) if not dry else {"intent": lp_intent, "state": "DRY-RUN"}
        out.append(res)
        if res.get("state") in ("CONFIRMED", "REJECTED", "FAILED"): L.kv_set("lp_last_action", time.time())
        if res.get("state") in ("CONFIRMED", "FAILED"): notify.send("INFO", f"lp-manage {lp_intent['action']}: {res.get('state')} {res.get('reason', '')}")
    notes += core_hold(L, snap) + airdrop_options(L)
    for s, summary, action, reason in notes:
        last = L.db.execute("SELECT summary,reason,ts FROM considered WHERE strategy=? ORDER BY id DESC LIMIT 1", (s,)).fetchone()
        if not last or last["summary"] != summary or last["reason"] != reason:
            L.db.execute("INSERT INTO considered(ts,strategy,summary,action,reason) VALUES(?,?,?,?,?)", (now(), s, summary, action, reason))
    L.db.commit()
    return out, notes

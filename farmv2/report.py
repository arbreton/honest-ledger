"""Everything the dashboard shows is derived here from the ledger + chain. No hardcoded business values (ST-5)."""
import json, datetime, pathlib
from . import registry, nav as navmod, halt
from .chain import iso

def _tx_rows(L, reg):
    labels = {}
    from .keccak import selector
    for sig, name in [("approve(address,uint256)", "approve"), ("deposit()", "wrap ETH"), ("withdraw(uint256)", "unwrap ETH"),
                      ("deposit(uint256,address)", "vault deposit"), ("decreaseLiquidity((uint256,uint128,uint256,uint256,uint256))", "LP decrease"),
                      ("collect((uint256,address,uint128,uint128))", "LP collect"), ("burn(uint256)", "LP burn")]:
        labels[selector(sig)] = name
    ids = {c["address"].lower(): c["id"] for c in reg["contracts"]}
    rows = []
    for e in L.events("ChainTx"):
        t = json.loads(e["payload"])
        px = t["eth_usd"]
        fee_usd = t["fee_wei"] / 1e18 * px
        eff, base = t["eff_gas_price"] / 1e9, t["base_fee"] / 1e9
        over = max(0.0, (t["eff_gas_price"] - 2 * t["base_fee"])) * t["gas_used"] / 1e18 * px if t["base_fee"] else 0.0
        to = (t["to"] or "").lower()
        rows.append({"nonce": t["nonce"], "ts": iso(t["ts"]), "block": t["block"], "hash": t["tx_hash"][:10] + "…",
                     "what": labels.get(t["selector"], t["selector"]), "target": ids.get(to, to[:8] + "…"),
                     "status": "ok" if t["status"] else "reverted", "fee_usd": round(fee_usd, 5), "gwei": round(eff, 4),
                     "base_gwei": round(base, 4), "ratio": round(eff / base, 1) if base else None, "overpaid_usd": round(over, 5)})
    return rows

def _contributions(L):
    eth_in, usd_in, rows = 0, 0.0, []
    for e in L.events("ExternalIn"):
        p = json.loads(e["payload"])
        eth_in += p["amount"]
        usd_in += p["amount"] / 1e18 * p["eth_usd"]
        rows.append({"block": e["block_number"], "eth": p["amount"] / 1e18, "usd": p["amount"] / 1e18 * p["eth_usd"], "declared": not p.get("needs_declaration")})
    return eth_in, usd_in, rows

def ensure_history(L, rpc, reg):
    """NAV after every wallet tx (and at funding), from archive state, so the equity curve is real."""
    have = {r[0] for r in L.db.execute("SELECT block_number FROM nav_snapshots")}
    blocks = {e["block_number"] for e in L.events("ChainTx")} | {e["block_number"] for e in L.events("ExternalIn")}
    for b in sorted(blocks - have):
        navmod.snapshot(L, rpc, reg, b, quorum=False)

def _series(L, hold_eth):
    out = []
    contrib_events = [(e["block_number"], json.loads(e["payload"])) for e in L.events("ExternalIn")]
    for r in L.db.execute("SELECT block_number, ts, nav_usd, eth_usd FROM nav_snapshots ORDER BY block_number"):
        b = r["block_number"]
        eth_in = sum(p["amount"] for bb, p in contrib_events if bb <= b)
        usd_in = sum(p["amount"] / 1e18 * p["eth_usd"] for bb, p in contrib_events if bb <= b)
        px = float(r["eth_usd"])
        out.append({"block": b, "ts": r["ts"], "nav": float(r["nav_usd"]), "hold": eth_in / 1e18 * px, "contrib": usd_in})
    return out

def _lp_perf(L, reg, latest, px_now):
    npm = registry.addr(reg, "aero-cl-npm").lower()
    pool = registry.addr(reg, "aero-cl-weth-usdc").lower()
    for e in L.events("ChainTx"):
        t = json.loads(e["payload"])
        mint = [m for m in t["moves"] if m["asset"].startswith("erc721:" + npm) and m["amount"] == 1]
        if not mint:
            continue
        w_in = sum(-m["amount"] for m in t["moves"] if m["asset"] == "erc20:" + registry.addr(reg, "weth").lower() and m["amount"] < 0)
        u_in = sum(-m["amount"] for m in t["moves"] if m["asset"] == "erc20:" + registry.addr(reg, "usdc").lower() and m["amount"] < 0)
        if not (w_in or u_in):
            continue
        entry_usd = w_in / 1e18 * t["eth_usd"] + u_in / 1e6
        hold_now = w_in / 1e18 * px_now + u_in / 1e6
        lp_now = sum(h["usd"] for h in latest["holdings"] if h["name"].startswith("Aerodrome"))
        days = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromtimestamp(t["ts"], datetime.timezone.utc)).total_seconds() / 86400
        return {"entry_usd": entry_usd, "hold_now": hold_now, "lp_now": lp_now, "alpha_vs_hold": lp_now - hold_now,
                "days": days, "fees_usd": sum(x["fees_usd"] for x in latest["lp"]), "token_id": mint[0]["asset"].split("#")[1]}
    return None

def _vault_perf(L, reg, latest, rpc=None, head=None):
    vault = registry.addr(reg, "morpho-gauntlet-usdc-prime").lower()
    usdc = "erc20:" + registry.addr(reg, "usdc").lower()
    cost, first = 0, None
    for e in L.events("ChainTx"):
        t = json.loads(e["payload"])
        out = [-m["amount"] for m in t["moves"] if m["asset"] == usdc and m["amount"] < 0 and m["cp"].lower() == vault]
        if out:
            cost += sum(out)
            first = first or t["ts"]
    now_v = next((h["usd"] for h in latest["holdings"] if h["name"].startswith("Morpho")), 0.0)
    if not cost:
        return None
    days = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromtimestamp(first, datetime.timezone.utc)).total_seconds() / 86400
    gain = now_v - cost / 1e6
    apy = llama = None
    try:
        from . import strategies, yields
        apy = strategies.measure_vault_apy(rpc, reg, head, days=7)
        llama = yields.llama_apy_for_held_vault(yields.fetch()["rows"])
    except Exception:
        pass
    return {"cost": cost / 1e6, "now": now_v, "gain": gain, "days": days, "apy_onchain": apy, "apy_llama": llama}

def _pipeline(L, rpc, reg):
    from . import executor, forecasts, yields
    sg = executor.SignerClient().status()
    rows = lambda q, n=10: [dict(r) for r in L.db.execute(q, (n,))]
    cands = []
    try:
        cands = [r for r in yields.fetch()["rows"] if r["tvl_usd"] >= 20_000_000][:8]
    except Exception:
        pass
    brier, nres = forecasts.brier(L)
    try: standing = json.loads((pathlib.Path(__file__).resolve().parents[1] / "registry-data" / "standing_approvals.json").read_text())["approvals"]
    except Exception: standing = []
    return {"standing": standing, "allowlist_ok": executor.allowlist_current(), "signer": "not running" if sg is None else ("locked" if sg.get("locked") else "unlocked"),
            "intents": rows("SELECT substr(created_at,1,16) ts, strategy, action, state, reason FROM intents ORDER BY created_at DESC LIMIT ?", 8),
            "considered": rows("SELECT substr(ts,1,16) ts, strategy, summary, reason FROM considered ORDER BY id DESC LIMIT ?", 12),
            "forecasts": forecasts.open_list(L), "brier": brier, "resolved": nres,
            "pending_approvals": L.db.execute("SELECT count(*) FROM approvals WHERE status='PENDING'").fetchone()[0],
            "candidates": cands, "sent_txs": L.db.execute("SELECT count(*) FROM sent_txs").fetchone()[0]}

def _lab():
    try: r = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data" / "lab_report.json").read_text())
    except Exception: return None
    sw = r.get("sweep") or {}
    keep = lambda v: {"name": v["name"], "tag": v["tag"], "valid": v["valid"], "select": v["select"], "dsr": v["dsr"], "gates": v["gates"], "holdout_beats": v.get("holdout_beats")}
    return {"generated": r["generated"], "verdict": r["verdict"], "rules": r["rules"], "n_trials": sw.get("n_trials"), "n_ml": sw.get("n_ml"), "n_survivors": sw.get("n_survivors"),
            "rc_p": sw.get("reality_check_p"), "benchmark": sw.get("benchmark"), "frac": sw.get("frac_beating_bh"), "liquidations": sw.get("liquidations"),
            "families": sw.get("family_median_excess_sharpe_valid"), "survivors": [keep(v) for v in (sw.get("survivors") or [])[:6]],
            "best_failed": [keep(v) for v in (sw.get("best_failed") or [])[:6]], "paper": (r.get("paper") or {}).get("champions", []),
            "eth_price": (r.get("paper") or {}).get("price"), "newpools": r.get("newpools"), "seasonality": r.get("seasonality"), "cycles": r.get("cycles"), "families": r.get("families"), "ml_quality": r.get("ml_quality"), "sweep_generated": sw.get("generated")}

def _opps():
    try:
        from pipeline import bot
        c = bot.db(); runs = c.execute("SELECT ts, summary FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return {"counts": bot.counts(c), "top": bot.top_open(c, 8), "last_run": runs["ts"] if runs else None,
                "leads": c.execute("SELECT count(*) FROM leads").fetchone()[0], "interval_h": bot.cfg()["interval_hours"]}
    except Exception:
        return None

def build(L, rpc, reg, audit=None, canaries=None):
    head = rpc.block_number() - 3
    latest = json.loads(L.db.execute("SELECT breakdown FROM nav_snapshots ORDER BY block_number DESC LIMIT 1").fetchone()[0])
    px = latest["eth_usd"]
    eth_in, usd_in, contrib = _contributions(L)
    hold_value = eth_in / 1e18 * px
    nav_usd = latest["nav_usd"]
    txs = _tx_rows(L, reg)
    gas_total = sum(r["fee_usd"] for r in txs)
    rec = [dict(r) for r in L.db.execute("SELECT ts, block_number, status FROM reconciliations ORDER BY id DESC LIMIT 500")]
    ok_n = sum(1 for r in rec if r["status"] == "OK")
    last_ok = next((r for r in rec if r["status"] == "OK"), None)
    chain_ok, n_events, _ = L.verify_chain()
    h = halt.reason()
    stage = "S0 Seed" if nav_usd < 1000 else ("S1 Build" if nav_usd < 10000 else ("S2 Scale" if nav_usd < 50000 else "S3 Preserve"))
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "wallet_short": reg["wallet"]["address"][:6] + "…" + reg["wallet"]["address"][-4:],
        "block": latest["block"], "head": head, "eth_usd": px, "price_source": latest["price_source"],
        "nav_usd": nav_usd, "nav_eth": latest["nav_eth"], "stage": stage, "goal_usd": 100000,
        "contributions_usd": usd_in, "contributions": contrib, "hold_value_usd": hold_value,
        "pnl_usd": nav_usd - usd_in, "vs_hold_usd": nav_usd - hold_value,
        "price_effect_usd": hold_value - usd_in, "strategy_effect_usd": nav_usd - hold_value,
        "gas_total_usd": gas_total, "gas_overpaid_usd": sum(r["overpaid_usd"] for r in txs),
        "reverted_txs": sum(1 for r in txs if r["status"] == "reverted"),
        "holdings": latest["holdings"], "buckets": latest["buckets"], "lp": latest["lp"],
        "series": _series(L, eth_in), "txs": txs,
        "lp_perf": _lp_perf(L, reg, latest, px), "vault_perf": _vault_perf(L, reg, latest, rpc, head), "pipeline": _pipeline(L, rpc, reg), "lab": _lab(), "opps": _opps(),
        "slo": {"recon_ok_pct": 100.0 * ok_n / len(rec) if rec else None, "recon_n": len(rec),
                "last_ok_block": last_ok["block_number"] if last_ok else None, "last_ok_ts": last_ok["ts"] if last_ok else None,
                "hash_chain_ok": chain_ok, "events": n_events, "halted": h, "audit": audit, "canaries": canaries},
    }

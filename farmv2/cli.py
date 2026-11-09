"""farmv2 command line. `tick` is the scheduled entry point (systemd timer)."""
import argparse, json, pathlib, sys, time, traceback, datetime
from . import registry, chain, nav, reconcile, report, site, halt, notify, strategies, forecasts, executor, policy
from .rpc import Rpc
from .ledger import Ledger, now

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "ledger.db"
DEPLOY_EVERY_S = 3 * 3600

def _incident(L, sev, kind, detail):
    L.db.execute("INSERT INTO incidents(severity,kind,detail,opened_at) VALUES(?,?,?,?)", (sev, kind, detail, now()))
    L.db.commit()

def _halt(L, by, why, kind="halt"):
    already = halt.is_halted()
    halt.set_halt(by, why)
    _incident(L, "Sev-1", kind, why)
    if not already:
        notify.send("HALT", f"HALTED by {by}: {why}")

def _handlers(L, reg, rpc):
    def status():
        nv = L.db.execute("SELECT nav_usd,block_number FROM nav_snapshots ORDER BY block_number DESC LIMIT 1").fetchone()
        rc = L.db.execute("SELECT status,ts FROM reconciliations ORDER BY id DESC LIMIT 1").fetchone()
        sg = executor.SignerClient().status()
        return (f"NAV ${float(nv['nav_usd']):.2f} (block {nv['block_number']}) | reconcile {rc['status']} {rc['ts'][11:16]}Z | "
                f"{'HALTED: ' + json.dumps(halt.reason()) if halt.is_halted() else 'running'} | signer {'down' if sg is None else ('locked' if sg.get('locked') else 'unlocked')}")
    return {"status": status, "halt": lambda why: (_halt(L, "operator-telegram", why), "halted. Resume only from the local terminal.")[1],
            "approve": lambda i, c: executor.approve(L, i, c), "deny": lambda i: executor.deny(L, i)}

def _resolve_forecasts(L, rpc, reg, head):
    for f in forecasts.due(L):
        if f["check_kind"] == "vault_apy_gte":
            apy = strategies.measure_vault_apy(rpc, reg, head, days=30)   # real elapsed time via block timestamps
            if apy is not None:
                forecasts.resolve(L, f["forecast_id"], apy >= json.loads(f["check_args"])["threshold"], f"measured 30d APY {apy:.2%}")
        elif not L.kv_get(f"fc_due_{f['forecast_id']}"):
            notify.send("INFO", f"Forecast due for manual resolution: {f['question']} (id {f['forecast_id']}). Run: python3 -m farmv2 resolve {f['forecast_id']} yes|no")
            L.kv_set(f"fc_due_{f['forecast_id']}", 1)

def _weekly(L, data):
    wk = datetime.date.today().isocalendar()
    key = f"{wk[0]}-W{wk[1]}"
    if datetime.date.today().weekday() == 6 and L.kv_get("weekly_sent") != key:
        brier, n = forecasts.brier(L)
        notify.send("INFO", f"WEEKLY {key}: NAV ${data['nav_usd']:.2f} | vs holding ETH {data['vs_hold_usd']:+.2f} | gas to date ${data['gas_total_usd']:.2f} | "
                            f"LP fees ${sum(x['fees_usd'] for x in data['lp']):.2f} | forecasts resolved {n}" + (f" (Brier {brier:.3f})" if brier is not None else "") +
                            f" | reconciliation {data['slo']['recon_ok_pct']:.0f}% over {data['slo']['recon_n']} checks")
        L.kv_set("weekly_sent", key)

def _lab(L):
    """Research lab (paper only, isolated venv, no keys): hourly paper tick; weekly sweep in the background at low priority."""
    import subprocess
    py = ROOT / "lab" / ".venv" / "bin" / "python"
    if not py.exists(): return
    now_ = time.time()
    if now_ - float(L.kv_get("lab_paper_ts", 0)) > 3300:
        try:
            subprocess.run([str(py), "-m", "lab.cli", "paper-tick"], cwd=str(ROOT), timeout=600, capture_output=True)
            L.kv_set("lab_paper_ts", now_)
        except Exception: pass
    res = ROOT / "lab" / "results" / "latest.json"
    running = subprocess.run(["pgrep", "-f", "lab.sweep|lab.cli sweep"], capture_output=True).returncode == 0
    if (not res.exists() or now_ - res.stat().st_mtime > 7 * 86400) and not running:
        log_ = open(ROOT / "lab" / "logs" / "sweep.log", "ab")
        subprocess.Popen(["nice", "-n", "15", str(py), "-m", "lab.cli", "sweep"], cwd=str(ROOT), stdout=log_, stderr=subprocess.STDOUT, start_new_session=True)

def _opps():
    try:
        from pipeline import bot
        return bot.run(notify=notify.send)
    except Exception as e:
        return {"errors": [str(e)[:80]]}

def pipeline_cmd(args):
    from pipeline import bot
    a = args[0] if args else "list"
    c = bot.db()
    if a == "run": print(bot.run(notify=notify.send, force=True))
    elif a == "list":
        for o in bot.top_open(c, 15): print(f"{o['id']:<16}{o['status']:<12}${o['score']:<6}/h  ${o['reward_usd']:>8,.0f}  subs {str(o['competition']):>4}  due {o['deadline'] or 'rolling':<10} {o['title'][:60]}")
        print("counts:", bot.counts(c))
    elif a == "show": r = c.execute("SELECT * FROM opps WHERE id LIKE ?", (args[1] + "%",)).fetchone(); print(open(r["draft"]).read() if r and r["draft"] else (dict(r) if r else "not found"))
    elif a in ("skip", "submitted", "won", "lost"): print(bot.mark(args[1], {"skip": "SKIPPED", "submitted": "SUBMITTED", "won": "WON", "lost": "LOST"}[a], " ".join(args[2:])))
    elif a == "lead-add": print(bot.add_lead(args[1], args[2] if len(args) > 2 else "", " ".join(args[3:])))
    elif a == "lead-contacted": print(bot.lead_contacted(int(args[1])))
    elif a == "leads":
        for r in c.execute("SELECT * FROM leads ORDER BY id"): print(dict(r))
    elif a == "digest": print(bot.DIGEST.read_text() if bot.DIGEST.exists() else "no digest yet")
    else: print("pipeline: run | list | show ID | skip ID | submitted ID [note] | won ID [note] | lost ID | lead-add NAME [URL] [pitch] | lead-contacted N | leads | digest")
    return 0

def tick(deploy=False, force_deploy=False, quiet=False):
    L, reg, rpc = Ledger(DB), registry.load(), Rpc()
    t0 = now()
    run_id = L.db.execute("INSERT INTO job_runs(job,started_at) VALUES('tick',?)", (t0,)).lastrowid
    log = (lambda *a: None) if quiet else print
    outcome, detail = "OK", ""
    try:
        head = rpc.block_number() - 3
        notify.poll(L, _handlers(L, reg, rpc))
        new_tx = chain.sync_wallet_txs(L, rpc, reg, head)
        gap_in, gap_out = chain.sync_tail_eth(L, rpc, reg, head)
        found, out_flags = chain.scan_external_tokens(L, rpc, reg, head)
        # one-time: everything before v2 went live is declared as v1 history (so SS-1 can tell it from anything new)
        if not L.kv_get("cutover_block"):
            L.kv_set("cutover_block", head)
            for e in L.events("ChainTx"):
                L.db.execute("INSERT OR IGNORE INTO declarations VALUES(?,?,?,?)", (e["tx_hash"], "v1-legacy", "sent by the v1 bot before cutover", now()))
            L.db.commit()
        unattrib = L.db.execute("SELECT tx_hash FROM events e WHERE type='ChainTx' AND tx_hash NOT IN (SELECT tx_hash FROM sent_txs) AND tx_hash NOT IN (SELECT tx_hash FROM declarations)").fetchall()
        if gap_out or out_flags or unattrib:
            _halt(L, "indexer", f"UNATTRIBUTED activity: eth_out_wei={gap_out} token_out={len(out_flags)} txs_not_from_v2={[r[0][:12] for r in unattrib]}", "unattributed")
        status, diffs = reconcile.reconcile(L, rpc, reg, head)
        if status != "OK":
            _halt(L, "reconciler", json.dumps(diffs), "reconciliation-breach")
        if time.time() - float(L.kv_get("pin_check_ts", 0)) > 3600:
            bad = registry.verify_pins(rpc)
            L.kv_set("pin_check_ts", time.time())
            L.kv_set("pins_ok", json.dumps({c["id"]: c["id"] not in {b[0] for b in bad} for c in reg["contracts"]}))
            if bad:
                _halt(L, "registry", f"code hash changed: {bad}", "code-hash-change")
        n = nav.snapshot(L, rpc, reg, head, quorum=True)
        report.ensure_history(L, rpc, reg)
        _resolve_forecasts(L, rpc, reg, head)
        # ---- strategies -> the single money path (executor). Acts only with an unlocked signer, within gate + caps.
        ex = executor.Executor(L, rpc, reg)
        if not halt.is_halted(): ex.signer.ensure_running()   # no-op unless the operator opted into unattended unlock
        acted = []
        if not halt.is_halted():
            snap = strategies.snapshot(L, rpc, reg, head, n, executor.base_fee_p50_gwei(rpc))
            out, _ = strategies.run(L, rpc, reg, ex, snap)
            acted = out + ex.resume()
        if any(a.get("state") == "CONFIRMED" for a in acted):
            chain.sync_wallet_txs(L, rpc, reg); chain.sync_tail_eth(L, rpc, reg, rpc.block_number() - 3)
            head = rpc.block_number() - 3
            status, diffs = reconcile.reconcile(L, rpc, reg, head)
            if status != "OK": _halt(L, "reconciler", json.dumps(diffs), "reconciliation-breach")
            n = nav.snapshot(L, rpc, reg, head, quorum=True)
        # ---- independent auditor + canaries through the real gate
        from auditor import audit as A, canaries as C
        tokens = {"USDC": (registry.addr(reg, "usdc"), 6), "WETH": (registry.addr(reg, "weth"), 18)}
        findings, ok, ablock = A.run(str(DB), reg["wallet"]["address"], tokens)
        audit = {"ok": ok, "block": ablock, "ts": now(), "findings": [[a, bool(b), c] for a, b, c in findings]}
        L.kv_set("audit", json.dumps(audit))
        if not ok:
            _halt(L, "auditor", json.dumps([f for f in audit["findings"] if not f[1]]), "audit-failed")
        can = C.run()
        L.kv_set("canaries", json.dumps(can))
        if not all(c[3] for c in can):
            _halt(L, "auditor", "a canary passed the Risk Gate", "canary-allowed")
        _lab(L)
        opps_run = _opps()
        data = report.build(L, rpc, reg, audit=audit, canaries=can)
        site.render(data)
        _weekly(L, data)
        detail = f"block {head} new_tx={new_tx} ext_tok={found} recon={status} nav=${n['nav_usd']:.2f} audit={'ok' if ok else 'FAIL'} acted={[(a.get('state')) for a in acted]}"
        log(detail)
        due = time.time() - float(L.kv_get("last_deploy_ts", 0)) > DEPLOY_EVERY_S
        changed = new_tx or gap_in or found or acted or halt.is_halted() != (L.kv_get("last_deploy_halted") == "1")
        if deploy and (force_deploy or due or changed):
            sys.path.insert(0, str(ROOT / "ops"))
            import deploy_netlify
            st = deploy_netlify.deploy(ROOT / "site")
            L.kv_set("last_deploy_ts", time.time()); L.kv_set("last_deploy_halted", "1" if halt.is_halted() else "0")
            log("deployed:", st)
    except Exception as e:
        outcome, detail = "ERROR", f"{type(e).__name__}: {e}"
        log(traceback.format_exc())
        if int(L.kv_get("err_streak", 0)) >= 3: notify.send("INFO", f"tick failing repeatedly: {detail[:200]}")
        L.kv_set("err_streak", int(L.kv_get("err_streak", 0)) + 1)
    else:
        L.kv_set("err_streak", 0)
    finally:
        L.db.execute("UPDATE job_runs SET ended_at=?, outcome=?, detail=? WHERE id=?", (now(), outcome, detail[:500], run_id)); L.db.commit()
    return 0 if outcome == "OK" else 1

def canary_live():
    """Operator-run, ONE time: prove the whole pipeline on mainnet with the cheapest possible real transactions
    (wrap then unwrap ~$0.50 of ETH). Cost-capped by rule R-07 (canary purpose), allowed by the signer's allowlist."""
    L, reg, rpc = Ledger(DB), registry.load(), Rpc()
    ex = executor.Executor(L, rpc, reg)
    wei = int(0.00025 * 1e18)
    outs = []
    for action, key in (("weth_wrap", "wrap"), ("weth_unwrap", "unwrap")):
        r = ex.submit({"strategy": "pipeline-canary", "action": action, "params": {"wei": wei}, "notional_usd": 0.5,
                       "benefit_usd": 0.0, "horizon_days": 0, "purpose": "canary"}, retry_rejected=True)
        print(key, r); outs.append(r)
        if r["state"] != "CONFIRMED": break
    chain.sync_wallet_txs(L, rpc, reg)
    head = rpc.block_number() - 3
    print("reconcile:", reconcile.reconcile(L, rpc, reg, head)[0])
    return 0 if all(o["state"] == "CONFIRMED" for o in outs) else 1

def lp_resize(eth, yes):
    """Operator-run: wrap idle ETH and re-mint the LP at a +/-8% range around spot with the bigger balance. Dry-run unless --yes."""
    L, reg, rpc = Ledger(DB), registry.load(), Rpc()
    ex = executor.Executor(L, rpc, reg)
    head = rpc.block_number() - 2
    from . import lp as lpm, nav as navm
    npm = registry.addr(reg, "aero-cl-npm")
    ids = navm.lp_nft_ids(L, "wallet:" + reg["wallet"]["address"].lower(), npm)
    if not ids: print("no LP position found"); return 1
    wei = int(eth * 1e18)
    plan = lpm.build(reg, rpc, "lp_resize", {"token_id": ids[0], "extra_eth_wei": wei}, head)
    print(f"plan: {len(plan.calls)} txs, notional ${plan.notional_usd:.2f}, new range {plan.range}")
    if not yes: print("dry run. add --yes to execute"); return 0
    r = ex.submit({"strategy": "lp-resize", "action": "lp_resize", "params": {"token_id": ids[0], "extra_eth_wei": wei}, "notional_usd": plan.notional_usd,
                   "benefit_usd": 0.13 * 14, "horizon_days": 14}, retry_rejected=True, operator_approved=True)
    print(r); return 0 if r["state"] == "CONFIRMED" else 1

def main(argv=None):
    ap = argparse.ArgumentParser(prog="farmv2")
    sp = ap.add_subparsers(dest="cmd", required=True)
    t = sp.add_parser("tick"); t.add_argument("--deploy", action="store_true"); t.add_argument("--force-deploy", action="store_true"); t.add_argument("--quiet", action="store_true")
    for c in ("status", "canaries", "pin", "poll", "signer-status", "unlock", "export-allowlist", "canary-live", "deploy", "forecasts", "considered"): sp.add_parser(c)
    h = sp.add_parser("halt"); h.add_argument("reason", nargs="?", default="operator")
    r = sp.add_parser("resume"); r.add_argument("--yes", action="store_true")
    for c in ("approve",): x = sp.add_parser(c); x.add_argument("id"); x.add_argument("code")
    x = sp.add_parser("deny"); x.add_argument("id")
    x = sp.add_parser("pipeline"); x.add_argument("args", nargs="*")
    x = sp.add_parser("lp-resize"); x.add_argument("--eth", type=float, default=0.0095); x.add_argument("--yes", action="store_true")
    x = sp.add_parser("resolve"); x.add_argument("id"); x.add_argument("outcome", choices=["yes", "no"])
    a = ap.parse_args(argv)
    if a.cmd == "tick": return tick(a.deploy, a.force_deploy, a.quiet)
    if a.cmd == "canary-live": return canary_live()
    if a.cmd == "lp-resize": return lp_resize(a.eth, a.yes)
    if a.cmd == "pipeline": return pipeline_cmd(a.args)
    if a.cmd == "export-allowlist":
        print("allowlist sha256:", policy.export()); return 0
    if a.cmd == "signer-status": print(executor.SignerClient().status() or "signer not running"); return 0
    if a.cmd == "unlock": print("unlocked" if executor.SignerClient().ensure_running() else "could not unlock (no pass file, or keystore missing)"); return 0
    if a.cmd == "canaries":
        from auditor import canaries
        res = canaries.run(); [print(("PASS " if ok else "FAIL ") + n) for n, d, b, ok in res]; return 0 if all(r[3] for r in res) else 1
    if a.cmd == "pin": print("changed:", registry.pin_all(Rpc())); return 0
    if a.cmd == "halt": halt.set_halt("operator", a.reason); print("HALTED"); return 0
    if a.cmd == "resume": halt.clear(a.yes); print("resumed"); return 0
    if a.cmd == "deploy":
        sys.path.insert(0, str(ROOT / "ops")); import deploy_netlify; print(deploy_netlify.deploy(ROOT / "site")); return 0
    L = Ledger(DB)
    if a.cmd == "approve": print(executor.approve(L, a.id, a.code)); return 0
    if a.cmd == "deny": print(executor.deny(L, a.id)); return 0
    if a.cmd == "resolve": forecasts.resolve(L, a.id, a.outcome == "yes", "operator"); print("resolved"); return 0
    if a.cmd == "forecasts": [print(f) for f in forecasts.open_list(L)]; print("brier:", forecasts.brier(L)); return 0
    if a.cmd == "considered":
        for r in L.db.execute("SELECT ts,strategy,summary,reason FROM considered ORDER BY id DESC LIMIT 15"): print(r["ts"][5:16], r["strategy"], "|", r["summary"], "|", r["reason"])
        return 0
    if a.cmd == "poll":
        n = notify.poll(L, _handlers(L, registry.load(), Rpc())); print("commands handled:", n); return 0
    if a.cmd == "status":
        ok, n, _ = L.verify_chain()
        rec = L.db.execute("SELECT ts,block_number,status FROM reconciliations ORDER BY id DESC LIMIT 1").fetchone()
        nv = L.db.execute("SELECT block_number,nav_usd,eth_usd FROM nav_snapshots ORDER BY block_number DESC LIMIT 1").fetchone()
        sg = executor.SignerClient().status()
        print(json.dumps({"halted": halt.reason() if halt.is_halted() else False, "events": n, "hash_chain_ok": ok,
                          "last_reconcile": dict(rec) if rec else None, "nav": dict(nv) if nv else None,
                          "signer": "not running" if sg is None else ("locked" if sg.get("locked") else "unlocked"),
                          "audit": json.loads(L.kv_get("audit", "null"))}, indent=1)); return 0

if __name__ == "__main__":
    sys.exit(main())

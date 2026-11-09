"""The single money path (ADR-0004): intent -> plan -> fork simulation -> Risk Gate -> (human) -> receipt -> signer -> broadcast -> confirm.
Nothing else in v2 can cause a signature. States: PROPOSED REJECTED NEEDS_HUMAN READY_LOCKED CONFIRMED FAILED BLOCKED."""
import hashlib, json, pathlib, secrets, socket, time
from . import registry, planner, sim, rules, halt, notify, policy, prices, lp
from .abi import call_data, words, u
from .ledger import now
from signer import core as sc

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOCK = ROOT / "data" / "signer" / "signer.sock"
KEYFILE = ROOT / "data" / "signer" / "receipt.key"
TIP_GWEI = 0.001

class SignerClient:
    def __init__(self, sock=SOCK, keyfile=KEYFILE):
        self.sock, self.keyfile = sock, keyfile
    def _req(self, obj):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(40)
        s.connect(str(self.sock)); s.sendall(json.dumps(obj).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            c = s.recv(65536)
            if not c: break
            buf += c
        s.close(); return json.loads(buf)
    def status(self):
        try: return self._req({"op": "status"})
        except Exception: return None     # daemon not running
    def ensure_running(self):
        """Unattended unlock, ONLY if the operator chose it by creating data/secrets/signer.pass (ops/setup-signer-auto.sh).
        Copies the passphrase to RAM (/dev/shm) and starts the daemon if it is not up. Without that file, the signer stays locked."""
        import os, subprocess, sys, shutil
        passf = ROOT / "data" / "secrets" / "signer.pass"
        if self.status() is not None and not self.status().get("locked"): return True
        if not passf.exists() or not (ROOT / "data" / "signer" / "keystore" / "farmv2").exists(): return False
        ram = pathlib.Path(os.environ.get("FARMV2_SIGNER_PW", "/dev/shm/farmv2-signer.pw"))
        shutil.copyfile(passf, ram); os.chmod(ram, 0o600)
        if self.status() is None:
            subprocess.Popen([sys.executable, "-m", "signer"], cwd=str(ROOT), env=dict(os.environ, PYTHONPATH=str(ROOT)),
                             stdout=open(ROOT / "data" / "signer" / "signer.log", "ab"), stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(30):
                time.sleep(0.3)
                if self.status() is not None: break
        st = self.status()
        return bool(st) and not st.get("locked")
    def key(self): return bytes.fromhex(pathlib.Path(self.keyfile).read_text().strip())
    def sign(self, tx, receipt): return self._req({"op": "sign", "tx": tx, "receipt": receipt})

def base_fee_p50_gwei(rpc):
    h = rpc.call("eth_feeHistory", [100, "latest", []])
    fees = sorted(int(x, 16) for x in h["baseFeePerGas"])
    return fees[len(fees) // 2] / 1e9

def allowlist_current():
    """True only if the signer's operator-approved allowlist hash equals what today's registry+policy would export.
    LP actions need new signer permissions; until the operator approves them the strategy must not even try."""
    import hashlib
    try:
        want = json.dumps(policy.build(), indent=1, sort_keys=True)
        return hashlib.sha256(want.encode()).hexdigest() == (ROOT / "data" / "signer" / "allowlist.sha256").read_text().strip()
    except Exception:
        return False

def standing_approval(action, notional_usd, today=None):
    """A pre-approval the operator granted for exactly this action/size, if still valid. Returns the record or None."""
    try: recs = json.loads((ROOT / "registry-data" / "standing_approvals.json").read_text())["approvals"]
    except Exception: return None
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    for r in recs:
        if r["action"] == action and notional_usd <= r["max_notional_usd"] and today <= r["expires"]:
            return r
    return None

def next_base_fee_gwei(rpc):
    return int(rpc.call("eth_feeHistory", [1, "latest", []])["baseFeePerGas"][-1], 16) / 1e9

def build_state(L, rpc, reg, head, bf_p50):   # reg is passed to policy so tests can use a throwaway wallet
    pol = policy.build(reg)
    pins = json.loads(L.kv_get("pins_ok", "{}"))
    if not pins or time.time() - float(L.kv_get("pin_check_ts", 0)) > 3900:   # never trust a stale or missing check: recompute (fails closed on error)
        bad = {b[0] for b in registry.verify_pins(rpc)}
        pins = {c["id"]: c["id"] not in bad for c in reg["contracts"]}
        L.kv_set("pins_ok", json.dumps(pins)); L.kv_set("pin_check_ts", time.time())
    allow = {}
    for addr, t in pol["targets"].items():
        cid = t["id"]; allow[addr] = {"selectors": set(t["selectors"].keys()), "code_hash_ok": pins.get(cid, False)}
    rec = L.db.execute("SELECT ts,status FROM reconciliations ORDER BY id DESC LIMIT 1").fetchone()
    age = 9999.0
    if rec:
        import datetime
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(rec["ts"])).total_seconds() / 60
    today = time.strftime("%Y-%m-%d", time.gmtime())
    spent = sum(json.loads(r["payload"]).get("notional_usd", 0) for r in L.db.execute(
        "SELECT payload FROM intents WHERE state='CONFIRMED' AND substr(created_at,1,10)=?", (today,)))
    nav = L.db.execute("SELECT nav_usd FROM nav_snapshots ORDER BY block_number DESC LIMIT 1").fetchone()
    return rules.State(halted=halt.is_halted(), recon_ok=bool(rec and rec["status"] == "OK"), recon_age_min=age, allow=allow,
                       base_fee_p50_gwei=bf_p50, spent_today_usd=spent, price_age_min=0.0, rpc_agree=True, head_block=head,
                       nav_usd=float(nav["nav_usd"]) if nav else 0.0)

class Executor:
    def __init__(self, L, rpc, reg, signer=None, upstream=None, broadcast_urls=None, simulate=sim.simulate, quiet=False):
        self.L, self.rpc, self.reg = L, rpc, reg
        self.signer = signer or SignerClient()
        self.upstream = upstream or rpc.urls[0]
        self.broadcast_urls = broadcast_urls or rpc.urls
        self.simulate, self.quiet = simulate, quiet

    # ---- persistence helpers
    def _set(self, iid, state, reason=""):
        self.L.db.execute("UPDATE intents SET state=?, reason=?, updated_at=? WHERE intent_id=?", (state, reason[:500], now(), iid)); self.L.db.commit()

    def _row(self, iid):
        return self.L.db.execute("SELECT * FROM intents WHERE intent_id=?", (iid,)).fetchone()

    @staticmethod
    def intent_id(intent):
        key = f"{intent['strategy']}|{intent['action']}|{json.dumps(intent['params'], sort_keys=True)}|{time.strftime('%Y-%m-%d', time.gmtime())}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    # ---- main entry
    def submit(self, intent, retry_rejected=False, operator_approved=False):
        iid = self.intent_id(intent)
        row = self._row(iid)
        if row and row["state"] == "REJECTED" and retry_rejected:
            self._set(iid, "PROPOSED", "retry requested by operator"); row = self._row(iid)   # CONFIRMED/FAILED stay final: never double-send
        if row and row["state"] in ("CONFIRMED", "REJECTED", "FAILED"):
            return {"intent_id": iid, "state": row["state"], "reason": row["reason"], "repeat": True}
        if not row:
            self.L.db.execute("INSERT INTO intents VALUES(?,?,?,?,?,?,?,?)", (iid, intent["strategy"], intent["action"], json.dumps(intent), "PROPOSED", "", now(), now()))
            self.L.db.commit()
        if halt.is_halted():
            self._set(iid, "BLOCKED", "global halt"); return {"intent_id": iid, "state": "BLOCKED", "reason": "global halt"}
        head = self.rpc.block_number() - 2
        plan = lp.build(self.reg, self.rpc, intent["action"], intent["params"]) if intent["action"].startswith("lp_") else planner.build(self.reg, intent["action"], intent["params"])
        wallet = self.reg["wallet"]["address"]
        tracked = [registry.addr(self.reg, "usdc"), registry.addr(self.reg, "weth"), registry.addr(self.reg, "morpho-gauntlet-usdc-prime")]
        allowances = [(t, s) for t, s in plan.allowance_zero]
        s = self.simulate(self.upstream, wallet, plan.calls, tracked, allowances, probe=plan.probe)
        sim_ok, sim_msg = sim.check_expectations(s, plan)
        bf = base_fee_p50_gwei(self.rpc)
        st = build_state(self.L, self.rpc, self.reg, head, bf)
        px, _ = prices.eth_usd(self.rpc, self.reg, head, quorum=True)
        limits = [int(g * 1.3) + 5000 for g in s["gas_used"]] or [200000]
        max_fee_gwei = rules.gas_cap_gwei(st)
        rp = rules.Plan(to=plan.calls[-1].to, selector=plan.calls[-1].selector, notional_usd=intent.get("notional_usd", plan.notional_usd),
                        max_fee_gwei=max_fee_gwei, gas_limit=sum(limits), eth_usd=px, approvals=plan.approvals,
                        benefit_usd=float(intent.get("benefit_usd", 0)), other_cost_usd=max(0.001, plan.est_cost_usd), sim_ok=sim_ok, internal=plan.internal,
                        expected_fee_gwei=next_base_fee_gwei(self.rpc) + TIP_GWEI,
                        calls=[(c.to, c.selector) for c in plan.calls], purpose=intent.get("purpose", ""))
        decision, res = rules.evaluate(rp, st)
        if decision == "NEEDS_HUMAN" and operator_approved and all(r.rule == "R-21" for r in res if not r.ok):
            decision = "ALLOW"; res.append(rules.RuleResult("OPERATOR", True, "HUMAN", "operator-initiated run (explicit CLI command)"))
        if decision == "NEEDS_HUMAN":     # a bounded, time-limited pre-approval from the operator can stand in for the tap, never for BLOCK rules
            sa = standing_approval(intent["action"], rp.notional_usd)
            if sa and all(r.rule == "R-21" for r in res if not r.ok):
                decision = "ALLOW"; res.append(rules.RuleResult("STANDING", True, "HUMAN", f"standing approval: {sa['approved_by']}, <= ${sa['max_notional_usd']}, expires {sa['expires']}"))
        self.L.db.execute("INSERT INTO decisions(intent_id,decision,rules,ts) VALUES(?,?,?,?)",
                          (iid, decision, json.dumps([[r.rule, r.ok, r.msg] for r in res] + [["SIM", sim_ok, sim_msg]]), now()))
        self.L.db.commit()
        failed = "; ".join(f"{r.rule}: {r.msg}" for r in res if not r.ok)
        if decision == "REJECT":
            self._set(iid, "REJECTED", failed or sim_msg); return {"intent_id": iid, "state": "REJECTED", "reason": failed or sim_msg}
        if decision == "NEEDS_HUMAN":
            ap = self.L.db.execute("SELECT * FROM approvals WHERE intent_id=?", (iid,)).fetchone()
            if not ap:
                code = secrets.token_hex(3)
                exp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
                self.L.db.execute("INSERT INTO approvals VALUES(?,?,?,?,NULL)", (iid, code, "PENDING", exp)); self.L.db.commit()
                notify.send("INFO", f"APPROVAL NEEDED {iid}: {intent['action']} {json.dumps(intent['params'])} (${rp.notional_usd:.2f}, expected benefit ${rp.benefit_usd:.3f}). Reply /approve {iid} {code} or /deny {iid}. Expires 24h.")
            elif ap["status"] != "APPROVED":
                self._set(iid, "NEEDS_HUMAN", f"approval {ap['status']}"); return {"intent_id": iid, "state": "NEEDS_HUMAN", "reason": failed}
            else:
                pass   # approved: continue to execute
            if not ap or ap["status"] != "APPROVED":
                self._set(iid, "NEEDS_HUMAN", failed); return {"intent_id": iid, "state": "NEEDS_HUMAN", "reason": failed}
        return self._execute(iid, plan, limits, max_fee_gwei)

    # ---- signing + broadcast
    def _execute(self, iid, plan, limits, max_fee_gwei):
        sstat = self.signer.status()
        if sstat is None or sstat.get("locked"):
            self._set(iid, "READY_LOCKED", "signer not running or locked: operator must unlock")
            return {"intent_id": iid, "state": "READY_LOCKED", "reason": "signer locked"}
        wallet = self.reg["wallet"]["address"]
        key = self.signer.key()
        for step, call in enumerate(plan.calls):
            done = self.L.db.execute("SELECT status FROM sent_txs WHERE intent_id=? AND step=?", (iid, step)).fetchone()
            if done and done["status"] == "1": continue
            if halt.is_halted():
                self._set(iid, "BLOCKED", "halt during execution"); return {"intent_id": iid, "state": "BLOCKED", "reason": "halt"}
            latest = self.rpc.nonce(wallet, int(self.rpc.call("eth_blockNumber", []), 16), quorum=True)
            pending = int(self.rpc.call("eth_getTransactionCount", [wallet, "pending"]), 16)
            if pending != latest:
                self._set(iid, "FAILED", "a transaction is already pending for this wallet"); return {"intent_id": iid, "state": "FAILED", "reason": "pending tx"}
            tx = {"chain_id": 8453, "nonce": latest, "to": call.to.lower(), "data": call.data, "value": call.value, "gas": limits[step],
                  "max_fee_per_gas": int(max_fee_gwei * 1e9), "max_priority_fee_per_gas": int(min(TIP_GWEI, max_fee_gwei) * 1e9)}
            receipt = sc.make_receipt(key, tx, iid, 900, f"{iid}-{step}-{secrets.token_hex(3)}")
            resp = self.signer.sign(tx, receipt)
            if not resp.get("ok"):
                self._set(iid, "FAILED", f"signer refused: {resp.get('code')} {resp.get('detail', '')}")
                notify.send("SEV1", f"signer refused intent {iid}: {resp}")
                return {"intent_id": iid, "state": "FAILED", "reason": f"signer refused {resp.get('code')}"}
            txh = None
            for url in self.broadcast_urls:
                try: txh = self.rpc.call("eth_sendRawTransaction", [resp["raw"]], urls=[url]); break
                except Exception as e:
                    if "already known" in str(e): break
            if not txh:
                self._set(iid, "FAILED", "broadcast failed"); return {"intent_id": iid, "state": "FAILED", "reason": "broadcast failed"}
            self.L.db.execute("INSERT OR REPLACE INTO sent_txs VALUES(?,?,?,?,?,?)", (txh, iid, step, latest, "pending", now())); self.L.db.commit()
            rc = None
            for _ in range(60):
                try: rc = self.rpc.call("eth_getTransactionReceipt", [txh], urls=self.broadcast_urls)
                except Exception: rc = None          # transient provider error: keep polling
                if rc: break
                time.sleep(2 if self.broadcast_urls != self.rpc.urls or "127.0.0.1" not in self.broadcast_urls[0] else 0.5)
            ok = bool(rc) and int(rc["status"], 16) == 1
            self.L.db.execute("UPDATE sent_txs SET status=? WHERE tx_hash=?", ("1" if ok else "0", txh)); self.L.db.commit()
            if not ok:
                self._set(iid, "FAILED", f"tx {txh[:12]} {'reverted' if rc else 'not confirmed in 120s'}")
                notify.send("SEV1", f"intent {iid} step {step} {'reverted' if rc else 'unconfirmed'}: {txh}")
                return {"intent_id": iid, "state": "FAILED", "reason": "step failed", "tx": txh}
        self._set(iid, "CONFIRMED", "all steps confirmed")
        notify.send("INFO", f"executed {iid} ({len(plan.calls)} tx)")
        return {"intent_id": iid, "state": "CONFIRMED", "reason": "ok"}

    def resume(self):
        """Retry intents waiting for the signer, or approved by the operator."""
        out = []
        for r in self.L.db.execute("SELECT intent_id,payload FROM intents WHERE state IN ('READY_LOCKED','NEEDS_HUMAN') AND substr(created_at,1,10)=?", (time.strftime("%Y-%m-%d", time.gmtime()),)).fetchall():
            ap = self.L.db.execute("SELECT status FROM approvals WHERE intent_id=?", (r["intent_id"],)).fetchone()
            if r["intent_id"] and (ap is None or ap["status"] == "APPROVED"):
                out.append(self.submit(json.loads(r["payload"])))
        return out

def approve(L, prefix, code):
    r = L.db.execute("SELECT * FROM approvals WHERE intent_id LIKE ? AND status='PENDING'", (prefix + "%",)).fetchone()
    if not r: return "no pending approval with that id"
    if r["code"] != code: return "wrong code"
    if r["expires_at"] < time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()):
        L.db.execute("UPDATE approvals SET status='EXPIRED' WHERE intent_id=?", (r["intent_id"],)); L.db.commit(); return "approval expired"
    L.db.execute("UPDATE approvals SET status='APPROVED', decided_at=? WHERE intent_id=?", (now(), r["intent_id"])); L.db.commit()
    return f"approved {r['intent_id']}; it will run on the next cycle if the signer is unlocked"

def deny(L, prefix):
    r = L.db.execute("SELECT * FROM approvals WHERE intent_id LIKE ? AND status='PENDING'", (prefix + "%",)).fetchone()
    if not r: return "no pending approval with that id"
    L.db.execute("UPDATE approvals SET status='DENIED', decided_at=? WHERE intent_id=?", (now(), r["intent_id"]))
    L.db.execute("UPDATE intents SET state='REJECTED', reason='denied by operator', updated_at=? WHERE intent_id=?", (now(), r["intent_id"])); L.db.commit()
    return f"denied {r['intent_id']}"

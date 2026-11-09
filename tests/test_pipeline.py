"""End-to-end money path against a LOCAL FORK with a throwaway wallet. Needs network + anvil: FARMV2_LIVE=1."""
import json, os, sys, shutil, subprocess, tempfile, time, pathlib, unittest, copy
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LIVE = bool(os.environ.get("FARMV2_LIVE"))
CAST = str(pathlib.Path.home() / ".foundry" / "bin" / "cast")
TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
from farmv2 import registry as _reg
REAL = _reg.load()["wallet"]["address"]       # the operator's wallet from registry-data/local.json (placeholder in a fresh clone)

@unittest.skipUnless(LIVE, "set FARMV2_LIVE=1 (needs network + anvil)")
class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from farmv2 import registry, policy, halt, sim, executor
        from farmv2.rpc import Rpc
        from farmv2.ledger import Ledger, now
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="pipe-"))
        cls._env_backup = ["FARMV2_OUTBOX", "FARMV2_TELEGRAM_CFG", "FARMV2_SIGNER_DIR", "FARMV2_HALT_DIR", "FARMV2_SIGNER_PW"]
        os.environ.update(FARMV2_OUTBOX=str(cls.tmp / "outbox.log"), FARMV2_TELEGRAM_CFG=str(cls.tmp / "none.json"), FARMV2_SIGNER_DIR=str(cls.tmp / "signer"), FARMV2_HALT_DIR=str(cls.tmp / "halt"), FARMV2_SIGNER_PW=str(cls.tmp / "pw"))
        (cls.tmp / "signer" / "keystore").mkdir(parents=True)
        import importlib; from signer import core; from farmv2 import notify; importlib.reload(core); importlib.reload(halt); importlib.reload(notify); importlib.reload(executor)
        cls.core, cls.halt = core, halt
        cls.reg = copy.deepcopy(registry.load()); cls.reg["wallet"]["address"] = TEST_ADDR
        base = Rpc(); head = base.block_number() - 3
        cls.fork = sim.Fork(base.urls[0], head)
        cls.rpc = Rpc([cls.fork.url], timeout=60, quorum_need=1)
        # give the throwaway wallet 2.0 USDC on the FORK by impersonating a contract that holds millions (the WETH/USDC pool).
        # Never depend on the live wallet's balances: they change as the real strategies run.
        whale = [c for c in cls.reg["contracts"] if c["id"] == "aero-cl-weth-usdc"][0]["address"]
        cls.fork.rpc("anvil_impersonateAccount", [whale]); cls.fork.rpc("anvil_setBalance", [whale, hex(10**18)])
        data = "0xa9059cbb" + TEST_ADDR[2:].lower().rjust(64, "0") + format(2_000_000, "064x")
        cls.fork.rpc("eth_sendTransaction", [{"from": whale, "to": cls.reg["contracts"][0]["address"], "data": data, "gas": hex(200000)}])
        time.sleep(1.0)
        # signer: keystore, receipt key, exported allowlist (hash-approved), daemon
        sd = cls.tmp / "signer"
        subprocess.run([CAST, "wallet", "import", "farmv2", "--keystore-dir", str(sd / "keystore"), "--private-key", TEST_KEY, "--unsafe-password", "pw"], check=True, capture_output=True)
        (sd / "receipt.key").write_text("ab" * 32); os.chmod(sd / "receipt.key", 0o600)
        import hashlib
        policy.export(sd / "allowlist.json", cls.reg)
        (sd / "allowlist.sha256").write_text(hashlib.sha256((sd / "allowlist.json").read_text().encode()).hexdigest())
        env = dict(os.environ); env["PYTHONPATH"] = str(ROOT)
        cls.daemon = subprocess.Popen([sys.executable, "-m", "signer"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
        for _ in range(40):
            if (sd / "signer.sock").exists(): break
            time.sleep(0.25)
        cls.client = executor.SignerClient(sd / "signer.sock", sd / "receipt.key")
        cls.L = Ledger(cls.tmp / "l.db")
        cls.L.db.execute("INSERT INTO reconciliations(ts,block_number,status,detail) VALUES(?,?,?,?)", (now(), head, "OK", "{}"))
        cls.L.db.execute("INSERT INTO nav_snapshots VALUES(?,?,?,?,?,?,?)", (head, now(), "66", "0.03", "2150", "{}", "t")); cls.L.db.commit()
        cls.L.kv_set("pins_ok", json.dumps({c["id"]: True for c in cls.reg["contracts"]}))
        cls.ex = executor.Executor(cls.L, cls.rpc, cls.reg, cls.client, upstream=cls.fork.url, broadcast_urls=[cls.fork.url], simulate=sim.simulate_on(cls.fork))
    @classmethod
    def tearDownClass(cls):
        cls.daemon.terminate(); cls.fork.stop(); shutil.rmtree(cls.tmp, ignore_errors=True)
        for k in cls._env_backup: os.environ.pop(k, None)   # do not leak temp paths into later test modules
    def intent(self, **kw):
        i = {"strategy": "usdc-park", "action": "vault_deposit", "params": {"vault": "morpho-gauntlet-usdc-prime", "assets": 2_000_000},
             "notional_usd": 2.0, "benefit_usd": 0.10, "horizon_days": 365}
        i.update(kw); return i
    def bal(self, token):
        return int(self.rpc.call("eth_call", [{"to": token, "data": "0x70a08231" + TEST_ADDR[2:].lower().rjust(64, "0")}, "latest"]), 16)

    def test_1_locked_signer_waits_and_does_not_fail(self):
        r = self.ex.submit(self.intent(params={"vault": "morpho-gauntlet-usdc-prime", "assets": 1_000_000}, notional_usd=1.0, benefit_usd=0.04))
        self.assertEqual(r["state"], "READY_LOCKED", r)
    def test_2_unprofitable_intent_rejected_by_payback_rule(self):
        r = self.ex.submit(self.intent(strategy="usdc-park-unprofitable", benefit_usd=0.00001))
        self.assertEqual(r["state"], "REJECTED"); self.assertIn("R-07", r["reason"])
    def test_3_human_needed_above_auto_limit(self):
        r = self.ex.submit(self.intent(strategy="big", notional_usd=10.0, benefit_usd=1.0))
        self.assertEqual(r["state"], "NEEDS_HUMAN", r)
    def test_4_full_path_confirms_and_leaves_no_allowance(self):
        pw = pathlib.Path(os.environ["FARMV2_SIGNER_PW"]); pw.write_text("pw"); os.chmod(pw, 0o600)
        res = self.ex.resume()            # the READY_LOCKED intent from test 1 now runs
        self.assertTrue(any(x["state"] == "CONFIRMED" for x in res), res)
        usdc, vault = self.reg["contracts"][0]["address"], [c for c in self.reg["contracts"] if c["id"] == "morpho-gauntlet-usdc-prime"][0]["address"]
        self.assertEqual(self.bal(usdc), 1_000_000)               # 1.0 of the 2.0 USDC deposited, exactly
        self.assertGreater(self.bal(vault), 0)                    # shares received
        allow = int(self.rpc.call("eth_call", [{"to": usdc, "data": "0xdd62ed3e" + TEST_ADDR[2:].lower().rjust(64, "0") + vault[2:].lower().rjust(64, "0")}, "latest"]), 16)
        self.assertEqual(allow, 0)                                # exact approval fully consumed
        steps = self.L.db.execute("SELECT count(*) FROM sent_txs WHERE status='1'").fetchone()[0]; self.assertEqual(steps, 2)
    def test_5_same_intent_is_idempotent(self):
        before = self.L.db.execute("SELECT count(*) FROM sent_txs").fetchone()[0]
        r = self.ex.submit(self.intent(params={"vault": "morpho-gauntlet-usdc-prime", "assets": 1_000_000}, notional_usd=1.0, benefit_usd=0.04))
        self.assertTrue(r.get("repeat")); self.assertEqual(before, self.L.db.execute("SELECT count(*) FROM sent_txs").fetchone()[0])
    def test_6_halt_blocks_before_anything_is_simulated_or_signed(self):
        self.halt.set_halt("test", "x")
        try:
            r = self.ex.submit(self.intent(strategy="after-halt", params={"vault": "morpho-gauntlet-usdc-prime", "assets": 500_000}, notional_usd=0.5, benefit_usd=0.05))
            self.assertEqual(r["state"], "BLOCKED")
        finally: self.halt.clear(True)
    def test_7_signer_refuses_a_crafted_drain_even_with_a_valid_receipt(self):
        key = self.client.key(); core = self.core
        tx = {"chain_id": 8453, "nonce": 99, "to": self.reg["contracts"][0]["address"].lower(), "value": 0, "gas": 80000, "max_fee_per_gas": 16_000_000, "max_priority_fee_per_gas": 1_000_000,
              "data": "0xa9059cbb" + "11" * 20 .__class__(b"").hex().rjust(0) if False else "0xa9059cbb" + ("00" * 12 + "11" * 20) + format(2_000_000, "064x")}   # transfer(attacker, 2 USDC)
        resp = self.client.sign(tx, core.make_receipt(key, tx, "evil", 900, "evil-1"))
        self.assertFalse(resp["ok"]); self.assertEqual(resp["code"], "NOT_ALLOWLISTED")

if __name__ == "__main__":
    unittest.main()

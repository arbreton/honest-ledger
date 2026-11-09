"""LP recenter/exit through executor -> signer -> broadcast, on a LOCAL FORK, with a throwaway wallet that owns a copy of the real
LP NFT (transferred on the fork only). Also simulates both plans against the REAL wallet/position. Needs network + anvil: FARMV2_LIVE=1."""
import copy, hashlib, json, os, shutil, subprocess, sys, tempfile, time, pathlib, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LIVE = bool(os.environ.get("FARMV2_LIVE"))
CAST = str(pathlib.Path.home() / ".foundry" / "bin" / "cast")
TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
from farmv2 import registry as _reg
REAL = _reg.load()["wallet"]["address"]       # the operator's wallet from registry-data/local.json (placeholder in a fresh clone)

def current_token_id(rpc, npm, block=None):
    """The real wallet's LP NFT right now (it changes if the strategy ever recenters)."""
    from farmv2.abi import call_data, words, u
    return u(words(rpc.eth_call(npm, call_data("tokenOfOwnerByIndex(address,uint256)", REAL, 0), block or rpc.block_number() - 2))[0])

@unittest.skipUnless(LIVE, "set FARMV2_LIVE=1 (needs network + anvil)")
class RealPositionSimulation(unittest.TestCase):
    def test_both_plans_pass_on_the_real_position(self):
        from farmv2 import registry, lp, sim
        from farmv2.rpc import Rpc
        reg = registry.load(); rpc = Rpc(); head = rpc.block_number() - 2
        tracked = [registry.addr(reg, x) for x in ("usdc", "weth", "morpho-gauntlet-usdc-prime")]
        for action in ("lp_exit", "lp_recenter"):
            plan = lp.build(reg, rpc, action, {"token_id": current_token_id(rpc, registry.addr(reg, "aero-cl-npm"), head)}, head)
            s = sim.simulate(rpc.urls[0], reg["wallet"]["address"], plan.calls, tracked, plan.allowance_zero, probe=plan.probe)
            ok, msg = sim.check_expectations(s, plan)
            self.assertTrue(ok, f"{action}: {msg}")

@unittest.skipUnless(LIVE, "set FARMV2_LIVE=1 (needs network + anvil)")
class LpPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from farmv2 import registry, policy, halt, sim, executor, lp
        from farmv2.rpc import Rpc
        from farmv2.ledger import Ledger, now
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="lppipe-"))
        cls._env = ["FARMV2_OUTBOX", "FARMV2_TELEGRAM_CFG", "FARMV2_SIGNER_DIR", "FARMV2_HALT_DIR", "FARMV2_SIGNER_PW"]
        os.environ.update(FARMV2_OUTBOX=str(cls.tmp / "outbox.log"), FARMV2_TELEGRAM_CFG=str(cls.tmp / "none.json"), FARMV2_SIGNER_DIR=str(cls.tmp / "signer"),
                          FARMV2_HALT_DIR=str(cls.tmp / "halt"), FARMV2_SIGNER_PW=str(cls.tmp / "pw"))
        (cls.tmp / "signer" / "keystore").mkdir(parents=True)
        import importlib; from signer import core; from farmv2 import notify
        importlib.reload(core); importlib.reload(halt); importlib.reload(notify); importlib.reload(executor)
        cls.core, cls.halt, cls.executor, cls.lp = core, halt, executor, lp
        cls.reg = copy.deepcopy(registry.load()); cls.reg["wallet"]["address"] = TEST_ADDR
        base = Rpc(); head = base.block_number() - 3
        cls.fork = sim.Fork(base.urls[0], head, optimism=False)
        global TID
        TID = current_token_id(base, registry.addr(cls.reg, "aero-cl-npm"), head)
        cls.rpc = Rpc([cls.fork.url], timeout=60, quorum_need=1)
        npm = registry.addr(cls.reg, "aero-cl-npm")
        cls.fork.rpc("anvil_impersonateAccount", [REAL])
        data = "0x23b872dd" + REAL[2:].lower().rjust(64, "0") + TEST_ADDR[2:].lower().rjust(64, "0") + format(TID, "064x")   # transferFrom, on the fork only
        h = cls.fork.rpc("eth_sendTransaction", [{"from": REAL, "to": npm, "data": data, "gas": hex(300000)}])
        time.sleep(1.0)
        sd = cls.tmp / "signer"
        subprocess.run([CAST, "wallet", "import", "farmv2", "--keystore-dir", str(sd / "keystore"), "--private-key", TEST_KEY, "--unsafe-password", "pw"], check=True, capture_output=True)
        (sd / "receipt.key").write_text("ab" * 32); os.chmod(sd / "receipt.key", 0o600)
        policy.export(sd / "allowlist.json", cls.reg)
        (sd / "allowlist.sha256").write_text(hashlib.sha256((sd / "allowlist.json").read_text().encode()).hexdigest())
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        cls.daemon = subprocess.Popen([sys.executable, "-m", "signer"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
        for _ in range(40):
            if (sd / "signer.sock").exists(): break
            time.sleep(0.25)
        pw = pathlib.Path(os.environ["FARMV2_SIGNER_PW"]); pw.write_text("pw"); os.chmod(pw, 0o600)
        cls.client = executor.SignerClient(sd / "signer.sock", sd / "receipt.key")
        cls.L = Ledger(cls.tmp / "l.db")
        cls.L.db.execute("INSERT INTO reconciliations(ts,block_number,status,detail) VALUES(?,?,?,?)", (now(), head, "OK", "{}"))
        cls.L.db.execute("INSERT INTO nav_snapshots VALUES(?,?,?,?,?,?,?)", (head, now(), "66", "0.03", "2150", "{}", "t")); cls.L.db.commit()
        cls.ex = executor.Executor(cls.L, cls.rpc, cls.reg, cls.client, upstream=cls.fork.url, broadcast_urls=[cls.fork.url], simulate=sim.simulate_on(cls.fork))
        cls.npm = npm
    @classmethod
    def tearDownClass(cls):
        cls.daemon.terminate(); cls.fork.stop(); shutil.rmtree(cls.tmp, ignore_errors=True)
        for k in cls._env: os.environ.pop(k, None)
    def call(self, to, data): return self.rpc.call("eth_call", [{"to": to, "data": data}, "latest"])
    def bal(self, tok): return int(self.call(tok, "0x70a08231" + TEST_ADDR[2:].lower().rjust(64, "0")), 16)

    def test_1_throwaway_wallet_owns_the_position(self):
        self.assertEqual(self.bal(self.npm), 1)
    def test_2_recenter_runs_all_ten_steps_through_the_signer(self):
        from farmv2 import nav, registry, lp
        pool = registry.addr(self.reg, "aero-cl-weth-usdc"); weth, usdc = registry.addr(self.reg, "weth"), registry.addr(self.reg, "usdc")
        st0 = lp.read_state(self.rpc, self.reg, TID, None if False else self.rpc.block_number())
        before = lp._value(st0["w_weth"] + st0["a0"] + st0["f0"], st0["w_usdc"] + st0["a1"] + st0["f1"], st0["px"])
        r = self.ex.submit({"strategy": "lp-manage", "action": "lp_recenter", "params": {"token_id": TID}, "notional_usd": before, "benefit_usd": 0.67, "horizon_days": 14})
        self.assertEqual(r["state"], "CONFIRMED", r)
        d = self.L.db.execute("SELECT rules FROM decisions ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertIn("STANDING", d)                                         # needed the pre-approval, used it, and recorded it
        steps = self.L.db.execute("SELECT count(*) FROM sent_txs WHERE status='1'").fetchone()[0]; self.assertEqual(steps, 10)
        self.assertEqual(self.bal(self.npm), 1)                              # old NFT burned, exactly one new NFT
        new_id = int(self.call(self.npm, "0x2f745c59" + TEST_ADDR[2:].lower().rjust(64, "0") + format(0, "064x")), 16)
        self.assertNotEqual(new_id, TID)
        p = nav.read_position(self.rpc, self.npm, new_id, None if False else self.rpc.block_number())
        self.assertEqual((p["tick_lo"], p["tick_hi"]), lp.target_range(st0["tick"]))
        st1 = lp.read_state(self.rpc, self.reg, new_id, self.rpc.block_number())
        after = lp._value(st1["w_weth"] + st1["a0"], st1["w_usdc"] + st1["a1"], st1["px"])
        self.assertLess((before - after) / before, 0.012, f"value ${before:.2f} -> ${after:.2f}")
        for tok in (weth, usdc):
            for sp in (self.npm, registry.addr(self.reg, "aero-cl-swap-router")):
                a = int(self.call(tok, "0xdd62ed3e" + TEST_ADDR[2:].lower().rjust(64, "0") + sp[2:].lower().rjust(64, "0")), 16)
                self.assertEqual(a, 0, f"residual allowance {tok[-6:]}->{sp[-6:]}")
    def test_2b_resize_wraps_idle_eth_and_enlarges_the_position(self):
        from farmv2 import registry, lp
        npm = self.npm
        (self.tmp / "signer" / "state.json").unlink(missing_ok=True)      # new simulated day: reset the signer's own daily tx counter (20/day cap)
        tid = int(self.call(npm, "0x2f745c59" + TEST_ADDR[2:].lower().rjust(64, "0") + format(0, "064x")), 16)       # the recentered NFT from test 2
        st0 = lp.read_state(self.rpc, self.reg, tid, self.rpc.block_number())
        pos_before = lp._value(st0["a0"] + st0["f0"], st0["a1"] + st0["f1"], st0["px"])
        extra = int(0.0095 * 1e18)
        r = self.ex.submit({"strategy": "lp-resize", "action": "lp_resize", "params": {"token_id": tid, "extra_eth_wei": extra}, "notional_usd": pos_before + 20,
                            "benefit_usd": 1.8, "horizon_days": 14}, operator_approved=True)
        self.assertEqual(r["state"], "CONFIRMED", r)
        new_id = int(self.call(npm, "0x2f745c59" + TEST_ADDR[2:].lower().rjust(64, "0") + format(0, "064x")), 16)
        st1 = lp.read_state(self.rpc, self.reg, new_id, self.rpc.block_number())
        pos_after = lp._value(st1["a0"], st1["a1"], st1["px"])
        self.assertGreater(pos_after, pos_before + 15.0, f"position ${pos_before:.2f} -> ${pos_after:.2f}")      # ~$20 of idle ETH went in
        self.assertEqual(self.bal(npm), 1)
    def test_3_a_second_attempt_the_same_day_is_idempotent(self):
        r = self.ex.submit({"strategy": "lp-manage", "action": "lp_recenter", "params": {"token_id": TID}, "notional_usd": 32.0, "benefit_usd": 0.67, "horizon_days": 14})
        self.assertTrue(r.get("repeat"))

if __name__ == "__main__":
    unittest.main()

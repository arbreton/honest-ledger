import os, sys, json, sqlite3, tempfile, unittest, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from farmv2.keccak import keccak256, selector, topic, to_checksum, is_valid_address, is_checksummed
from farmv2.ledger import Ledger
from farmv2 import registry, nav, rules
from auditor import canaries

class Keccak(unittest.TestCase):
    def test_vectors(self):
        self.assertEqual(keccak256(b"").hex(), "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
        self.assertEqual(selector("transfer(address,uint256)"), "0xa9059cbb")
        self.assertEqual(topic("Transfer(address,address,uint256)")[:10], "0xddf252ad")
    def test_checksum(self):
        self.assertEqual(to_checksum("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"), "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
        self.assertTrue(is_checksummed("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"))
        self.assertFalse(is_valid_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02914"))   # bad checksum
    def test_v1_malformed_allowlist_entries_rejected(self):
        self.assertFalse(is_valid_address("0xebf418fe2512e7e6bd9b87a8f0f294a5cdc67e6b4"))   # 41 hex chars
        self.assertFalse(is_valid_address("0x940181a94a35a4569e4529a3cd9f4b74e38fd98631"))  # 42 hex chars

class LedgerInvariants(unittest.TestCase):
    def setUp(self):
        self.L = Ledger(tempfile.mktemp(suffix=".db"))
    def test_unbalanced_rejected(self):
        s = self.L.append("e1", "T", {}, "2026-01-01T00:00:00+00:00")
        with self.assertRaises(ValueError):
            self.L.post("j", s, [("a", "asset", "ETH", -5, "0"), ("b", "equity", "ETH", 4, "0")])
    def test_idempotent_and_balances(self):
        s = self.L.append("e1", "T", {}, "2026-01-01T00:00:00+00:00")
        self.assertIsNone(self.L.append("e1", "T", {}, "x"))
        self.assertTrue(self.L.post("j", s, [("wallet:x", "asset", "ETH", 5, "0"), ("cp", "equity", "ETH", -5, "0")]))
        self.assertFalse(self.L.post("j", s, [("wallet:x", "asset", "ETH", 5, "0"), ("cp", "equity", "ETH", -5, "0")]))
        self.assertEqual(self.L.balances()[("wallet:x", "ETH")], 5)
    def test_events_immutable(self):
        self.L.append("e1", "T", {"a": 1}, "2026-01-01T00:00:00+00:00")
        with self.assertRaises(sqlite3.DatabaseError):
            self.L.db.execute("UPDATE events SET payload='{}'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.L.db.execute("DELETE FROM events")
    def test_tamper_detected(self):
        self.L.append("e1", "T", {"a": 1}, "2026-01-01T00:00:00+00:00")
        self.L.append("e2", "T", {"a": 2}, "2026-01-01T00:00:01+00:00")
        self.assertTrue(self.L.verify_chain()[0])
        self.L.db.execute("DROP TRIGGER events_no_update")
        self.L.db.execute("UPDATE events SET payload='{\"a\":99}' WHERE event_id='e1'")
        ok, _, bad = self.L.verify_chain()
        self.assertFalse(ok); self.assertEqual(bad, 1)
    def test_balances_asof(self):
        s1 = self.L.append("e1", "T", {}, "t", block_number=10); s2 = self.L.append("e2", "T", {}, "t", block_number=20)
        self.L.post("j1", s1, [("wallet:x", "asset", "ETH", 5, "0"), ("cp", "equity", "ETH", -5, "0")])
        self.L.post("j2", s2, [("wallet:x", "asset", "ETH", 3, "0"), ("cp", "equity", "ETH", -3, "0")])
        self.assertEqual(self.L.balances_asof(15)[("wallet:x", "ETH")], 5)
        self.assertEqual(self.L.balances_asof(25)[("wallet:x", "ETH")], 8)

class Registry(unittest.TestCase):
    def test_shipped_registry_valid(self):
        reg = registry.load()
        self.assertEqual(len(reg["contracts"]), 10)
        for c in reg["contracts"]:
            self.assertTrue(is_checksummed(c["address"]), c["id"])
            self.assertTrue(c.get("code_hash", "").startswith("0x"), f"{c['id']} not pinned")
    def test_rejects_malformed_and_duplicates(self):
        d = {"wallet": {"address": "0x0000000000000000000000000000000000000001"}, "contracts": [{"id": "x", "address": "0xebf418fe2512e7e6bd9b87a8f0f294a5cdc67e6b4", "role": "t"}]}
        f = tempfile.mktemp(suffix=".json"); open(f, "w").write(json.dumps(d))
        with self.assertRaises(registry.RegistryError): registry.load(f)

class Rules(unittest.TestCase):
    def test_every_canary_is_blocked(self):
        for name, decision, by, ok in canaries.run():
            self.assertTrue(ok, f"{name}: {decision} {by}")
    def test_gas_cap_scales_with_base_fee(self):
        s = rules.State(base_fee_p50_gwei=0.005)
        self.assertAlmostEqual(rules.gas_cap_gwei(s), 0.016)
        self.assertEqual(rules.gas_cap_gwei(rules.State(base_fee_p50_gwei=5.0)), rules.ABS_MAX_FEE_GWEI)  # absolute cap wins
    def test_v1_8gwei_tx_rejected_by_gas_rules(self):
        p, s = canaries.CANARIES["v1-8gwei-swap (tx 0x130bdc9f)"]
        _, res = rules.evaluate(p, s)
        failed = {r.rule for r in res if not r.ok}
        self.assertTrue({"R-05", "R-06"} <= failed)
    def test_healthy_small_plan_not_rejected(self):
        d, _ = rules.evaluate(canaries.base_plan(), canaries.base_state())
        self.assertNotEqual(d, "REJECT")
    def test_halt_blocks_everything(self):
        d, res = rules.evaluate(canaries.base_plan(), canaries.base_state(halted=True))
        self.assertEqual(d, "REJECT"); self.assertFalse(next(r for r in res if r.rule == "R-01").ok)

class GasPricing(unittest.TestCase):
    def test_realistic_2usd_deposit_passes_cost_rules_at_expected_price(self):
        # real measured gas: approve 55k + deposit 422k, limits +30%. Cap 0.016 gwei, expected 0.006 gwei, ETH $2150.
        p = canaries.base_plan(gas_limit=int((55_437 + 422_104) * 1.3) + 10_000, max_fee_gwei=0.016, expected_fee_gwei=0.006, notional_usd=2.03, benefit_usd=0.078, other_cost_usd=0.001, eth_usd=2150.0)
        _, res = rules.evaluate(p, canaries.base_state())
        failed = {r.rule for r in res if not r.ok}
        self.assertFalse(failed & {"R-05", "R-06", "R-07"}, failed)
    def test_same_plan_priced_at_the_cap_would_have_failed_r06(self):
        p = canaries.base_plan(gas_limit=int((55_437 + 422_104) * 1.3) + 10_000, max_fee_gwei=0.016, notional_usd=2.03, benefit_usd=0.078, other_cost_usd=0.001, eth_usd=2150.0)
        _, res = rules.evaluate(p, canaries.base_state())
        self.assertIn("R-06", {r.rule for r in res if not r.ok})

class NavMath(unittest.TestCase):
    def test_lp_all_token0_below_range_and_all_token1_above(self):
        sq_lo = int(1.0001 ** (-200000 / 2) * 2**96); sq_hi = int(1.0001 ** (-197550 / 2) * 2**96)
        a0, a1 = nav.lp_amounts(10**12, sq_lo // 2, -200000, -197550); self.assertGreater(a0, 0); self.assertEqual(a1, 0)
        a0, a1 = nav.lp_amounts(10**12, sq_hi * 2, -200000, -197550); self.assertEqual(a0, 0); self.assertGreater(a1, 0)
    def test_lp_in_range_has_both_tokens(self):
        sq = int(1.0001 ** (-199000 / 2) * 2**96)
        a0, a1 = nav.lp_amounts(10**12, sq, -200000, -197550); self.assertGreater(a0, 0); self.assertGreater(a1, 0)
    def test_fee_growth_arithmetic_wraps_mod_2_256(self):
        # feeGrowth counters are uint256 and may wrap; (now - last) must be taken mod 2**256
        last, now_ = nav.M256 - 5, 10
        self.assertEqual((now_ - last) & nav.M256, 16)

class Live(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("FARMV2_LIVE"), "set FARMV2_LIVE=1 for network integration")
    def test_ledger_matches_chain(self):
        from farmv2.rpc import Rpc
        from farmv2 import reconcile
        L = Ledger(ROOT / "data" / "ledger.db"); rpc = Rpc(); reg = registry.load()
        st, diffs = reconcile.reconcile(L, rpc, reg, rpc.block_number() - 3)
        self.assertEqual(st, "OK", diffs)

if __name__ == "__main__":
    unittest.main()

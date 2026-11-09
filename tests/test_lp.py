import copy, os, sys, tempfile, time, unittest, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = pathlib.Path(tempfile.mkdtemp(prefix="lptest-"))
os.environ.setdefault("FARMV2_HALT_DIR", str(TMP / "halt")); os.environ.setdefault("FARMV2_SIGNER_PW", str(TMP / "pw"))
from farmv2 import lp, nav, registry, policy, strategies, rules, executor
from farmv2.ledger import Ledger
from signer import core

TEST_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
KEY = bytes.fromhex("11" * 32)

def synthetic_state(reg, tick=-199636, w_weth=640_401_107_379_140, w_usdc=2_028_135):
    sq = int(1.0001 ** (tick / 2) * 2**96)
    pos = {"tick_lo": -200000, "tick_hi": -197550, "liq": 5_566_156_014_153, "fg0": 0, "fg1": 0, "owed0": 0, "owed1": 0}
    a0, a1 = nav.lp_amounts(pos["liq"], sq, pos["tick_lo"], pos["tick_hi"])
    return {"token_id": 8905566, "pos": pos, "sq": sq, "tick": tick, "px": lp.px_from_sqrt(sq), "a0": a0, "a1": a1, "f0": 130_000_000_000_000, "f1": 290_000,
            "w_weth": w_weth, "w_usdc": w_usdc, "tick_spacing": 50}

class RangeMath(unittest.TestCase):
    def test_target_range_is_aligned_and_contains_the_price(self):
        for tick in (-199636, -200001, -198800, 12345, -1, 0, 1, 49, 50):
            lo, hi = lp.target_range(tick)
            self.assertTrue(lo < tick < hi); self.assertEqual(lo % 50, 0); self.assertEqual(hi % 50, 0)
            self.assertLessEqual((tick - lo) - (hi - tick), 100)          # roughly centred
    def test_centered_range_is_about_half_eth(self):
        lo, hi = lp.target_range(-199636); f = lp.weth_value_fraction(int(1.0001 ** (-199636 / 2) * 2**96), lo, hi)
        self.assertTrue(0.45 < f < 0.55, f)
    def test_liquidity_never_exceeds_either_token(self):
        sq = int(1.0001 ** (-199636 / 2) * 2**96); lo, hi = lp.target_range(-199636)
        L = lp.liquidity_for(sq, lo, hi, 10**16, 25_000_000); e0, e1 = nav.lp_amounts(L, sq, lo, hi)
        self.assertLessEqual(e0, 10**16 + 10); self.assertLessEqual(e1, 25_000_000 + 10)

class PlansAreAcceptedBySigner(unittest.TestCase):
    """The strongest offline check: every call the planner can emit must pass the signer's real allowlist, and nothing else."""
    @classmethod
    def setUpClass(cls):
        cls.reg = copy.deepcopy(registry.load()); cls.reg["wallet"]["address"] = TEST_ADDR
        cls.allow = policy.build(cls.reg)
    def check_all(self, plan):
        for i, c in enumerate(plan.calls):
            t = {"chain_id": 8453, "nonce": i, "to": c.to.lower(), "data": c.data, "value": c.value, "gas": 600_000, "max_fee_per_gas": 16_000_000, "max_priority_fee_per_gas": 1_000_000}
            r = core.make_receipt(KEY, t, "x", 900, f"r{i}")
            ok, code, detail = core.check(t, r, self.allow, KEY, {"count": 0, "value": 0}, set())
            self.assertTrue(ok, f"step {i} '{c.note}' refused by signer: {code} {detail}")
    def test_exit_plan(self): self.check_all(lp.plan_exit(self.reg, synthetic_state(self.reg)))
    def test_recenter_plan_both_swap_directions(self):
        for tick, w_weth, w_usdc in ((-199636, 640_401_107_379_140, 2_028_135), (-198000, 0, 0), (-201000, 10**16, 0), (-199636, 0, 30_000_000)):
            st = synthetic_state(self.reg, tick, w_weth, w_usdc); plan = lp.plan_recenter(self.reg, st)
            self.check_all(plan)
            ap = [c for c in plan.calls if c.sig == "approve(address,uint256)"]; self.assertTrue(ap[-1].note == "revoke" and ap[-2].note == "revoke")
            self.assertEqual(plan.calls[-3].sig, lp.S_MINT)
    def test_no_plan_call_is_a_transfer_or_unknown(self):
        plan = lp.plan_recenter(self.reg, synthetic_state(self.reg))
        for c in plan.calls: self.assertNotIn(c.data[:10], ("0xa9059cbb", "0x23b872dd", "0x42842e0e", "0xa22cb465"))
    def test_all_value_returns_to_wallet(self):
        plan = lp.plan_recenter(self.reg, synthetic_state(self.reg)); w = TEST_ADDR[2:].lower().rjust(64, "0")
        for c in plan.calls:
            if c.sig in (lp.S_COLLECT, lp.S_MINT, lp.S_SWAP): self.assertIn(w, c.data.lower(), c.note)

class Triggers(unittest.TestCase):
    def setUp(self): self.L = Ledger(tempfile.mktemp(suffix=".db"))
    def pos(self, in_range=True, rate=0.05):
        return {"id": 1, "in_range": in_range, "margin_ticks": 300 if in_range else -50, "weth": 0.012, "usdc": 5.0, "fees_usd": 0.6, "fee_rate_usd_day": rate}
    def run_(self, p): return strategies.lp_manage(self.L, {"eth_usd": 2150.0, "lp": [p]})[0]
    def test_in_range_does_nothing(self): self.assertIsNone(self.run_(self.pos()))
    def test_hysteresis_then_recenter_or_exit(self):
        self.assertIsNone(self.run_(self.pos(False)))                                          # just went out of range: wait
        self.L.kv_set("lp_oor_1", time.time() - 7200)
        self.assertEqual(self.run_(self.pos(False, 0.05))["action"], "lp_recenter")            # fees ~70% APR
        self.assertEqual(self.run_(self.pos(False, 0.003))["action"], "lp_exit")               # fees ~4% APR
    def test_cooldown(self):
        self.L.kv_set("lp_oor_1", time.time() - 7200); self.L.kv_set("lp_last_action", time.time())
        self.assertIsNone(self.run_(self.pos(False)))
    def test_returning_to_range_resets_the_clock(self):
        self.L.kv_set("lp_oor_1", time.time() - 7200); self.run_(self.pos(True))
        self.assertIsNone(self.run_(self.pos(False)))

class StandingApprovals(unittest.TestCase):
    def test_valid_within_limits(self): self.assertIsNotNone(executor.standing_approval("lp_recenter", 33.0, "2026-11-20"))
    def test_too_large_or_expired_or_other_action(self):
        self.assertIsNone(executor.standing_approval("lp_recenter", 80.0, "2026-11-20"))
        self.assertIsNone(executor.standing_approval("lp_recenter", 30.0, "2027-01-01"))
        self.assertIsNone(executor.standing_approval("vault_deposit", 3.0, "2026-11-20"))
    def test_standing_approval_cannot_override_a_block_rule(self):
        from auditor import canaries
        p = canaries.base_plan(notional_usd=30.0, internal=True, benefit_usd=5.0); s = canaries.base_state(halted=True)
        d, res = rules.evaluate(p, s); self.assertEqual(d, "REJECT")                               # halt still wins
    def test_internal_plans_get_bounded_limits(self):
        from auditor import canaries
        big = canaries.base_plan(notional_usd=33.0, internal=True, benefit_usd=5.0, max_fee_gwei=0.01, gas_limit=1_000_000)
        d, res = rules.evaluate(big, canaries.base_state(nav_usd=66.0))
        self.assertTrue(next(r for r in res if r.rule == "R-11").ok)
        huge = canaries.base_plan(notional_usd=70.0, internal=True, benefit_usd=9.0)
        self.assertFalse(next(r for r in rules.evaluate(huge, canaries.base_state(nav_usd=200.0))[1] if r.rule == "R-11").ok)   # >$60 even if internal
        ext = canaries.base_plan(notional_usd=33.0, internal=False, benefit_usd=5.0)
        self.assertFalse(next(r for r in rules.evaluate(ext, canaries.base_state(nav_usd=66.0))[1] if r.rule == "R-11").ok)     # external keeps the tight cap

if __name__ == "__main__":
    unittest.main()

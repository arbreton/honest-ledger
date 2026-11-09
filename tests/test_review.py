import sys, datetime, tempfile, pathlib, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from lab import review
def acct(name, ret, bh, dd, bhdd, liq=False, reg="2026-11-09T02:00:00+00:00", risk="low"):
    return {"name": name, "risk": risk, "days": 30.0, "ret": ret, "bh_ret": bh, "maxdd": dd, "bh_maxdd": bhdd, "liquidated": liq, "trades": 7, "registered_at": reg}
class Review(unittest.TestCase):
    def test_rules_exactly_as_preregistered(self):
        self.assertEqual(review.classify(acct("x", -0.9, 0.0, -0.9, -0.1, liq=True)), "LIQUIDATED: drop")
        self.assertEqual(review.classify(acct("x", -0.20, 0.0, -0.30, -0.10)), "CLEARLY LAGGING: drop")        # trails by 20pp AND deeper drop
        self.assertEqual(review.classify(acct("x", -0.20, 0.0, -0.05, -0.10)), "CONTINUE")                      # trails but shallower drop: kept
        self.assertEqual(review.classify(acct("x", -0.10, 0.0, -0.30, -0.10)), "CONTINUE")                      # deeper drop but trails <15pp: kept
        self.assertEqual(review.classify(acct("x", 0.40, 0.0, -0.01, -0.10)), "CONTINUE")                       # a great month is NOT promoted
    def test_not_written_before_day_30_and_written_once_after(self):
        res = [acct("a", 0.01, 0.0, -0.02, -0.05)]
        with tempfile.TemporaryDirectory() as d:
            review.REVIEWS = pathlib.Path(d) / "reviews"
            early = datetime.datetime(2026, 12, 8, 12, tzinfo=datetime.timezone.utc); late = datetime.datetime(2026, 12, 9, 12, tzinfo=datetime.timezone.utc)
            self.assertIsNone(review.maybe_write(res, "2026-12-08T00:00", 2000.0, now=early))
            import os; os.environ["X"] = "1"
            p = review.maybe_write(res, "2026-12-09T00:00", 2000.0, now=late)
            self.assertTrue(p and pathlib.Path(p).exists() and p.endswith("paper-day30-2026-12-09.md"))
            self.assertEqual(review.maybe_write(res, "2026-12-09T01:00", 2100.0, now=late), p)                  # idempotent
            txt = pathlib.Path(p).read_text(); self.assertIn("sanity screen", txt); self.assertIn("Nothing is promoted", txt)
    def tearDown(self):
        # the generator appends to the real outbox only when a review is written; remove any test line
        o = ROOT / "data" / "outbox.log"
        if o.exists():
            o.write_text("".join(l for l in o.read_text().splitlines(True) if "paper-day30-2026-12-09" not in l or "/tmp/" not in l))
if __name__ == "__main__": unittest.main()

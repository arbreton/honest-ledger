import sys, json, tempfile, pathlib, unittest, datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from pipeline import bot

def iso_in(days): return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
def opp(i, title, reward=500, subs=20, deadline=None, kind="bounty", source="superteam", **kw):
    return {"id": f"t-{i}", "source": source, "kind": kind, "title": title, "url": f"https://example.org/{i}", "reward_usd": reward, "deadline": deadline if deadline is not None else iso_in(10), "competition": subs, **kw}

class Bot(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="pipe-")); bot.DB = self.tmp / "p.db"; bot.DRAFTS = self.tmp / "drafts"; bot.DIGEST = self.tmp / "digest.md"
        self.msgs = []; self.notify = lambda lvl, txt: self.msgs.append(txt); self.pr = bot.profile()
    def run_(self, items, **k): return bot.run(fetchers={"x": lambda: items}, notify=self.notify, force=True, **k)

    def test_competition_lowers_expected_value_and_bad_fit_is_penalised(self):
        few = bot.estimate(opp(1, "Build a Python monitoring bot", subs=5), self.pr); many = bot.estimate(opp(2, "Build a Python monitoring bot", subs=600), self.pr)
        bad = bot.estimate(opp(3, "Make a meme video", subs=5), self.pr)
        self.assertGreater(few["ev_usd"], many["ev_usd"] * 5); self.assertLess(bad["ev_usd"], few["ev_usd"])
    def test_link_slug_and_trading_competitions_count_against_fit(self):
        plain = bot.estimate(opp(7, "Show us how you use Acme", subs=28), self.pr)
        slug = bot.estimate(dict(opp(8, "Show us how you use Acme", subs=28), url="https://x.org/listing/acme-video-chile-colombia"), self.pr)
        trade = bot.estimate(opp(9, "Panta x NectarFi Trading Competition Bounty", subs=53), self.pr)
        self.assertLess(slug["ev_usd"], plain["ev_usd"] / 2); self.assertLess(trade["ev_usd"], plain["ev_usd"])
    def test_wrong_kind_of_work_never_reaches_drafts(self):
        self.run_([opp(1, "Make a video about our x402 Feature", reward=500, subs=48), opp(2, "Build a Solana growth product", reward=5000, subs=71)])
        st = {r["id"]: r["status"] for r in bot.db().execute("SELECT id,status FROM opps")}
        self.assertNotEqual(st["t-1"], "DRAFTED")
    def test_description_can_demote_a_title_that_looked_good(self):
        base = bot.estimate(opp(1, "Build and Route Challenge", reward=5000, subs=4), self.pr)["score"]
        stub = lambda o: {"text": "build a useful solana product with an api and bring real users with marketing", "region": "Global"}
        bot.run(fetchers={"x": lambda: [opp(1, "Build and Route Challenge", reward=5000, subs=4)]}, notify=self.notify, force=True, details_fn=stub)
        r = bot.db().execute("SELECT score,note FROM opps WHERE id='t-1'").fetchone()
        self.assertIn("outside the proven EVM stack", r["note"]); self.assertLess(r["score"], base * 0.2)      # firm: a technical-sounding word cannot rescue it
    def test_description_can_confirm_a_real_match(self):
        items = [opp(2, "Build a Python agent dashboard for Base", reward=1500, subs=4)]
        stub = lambda o: {"text": "we need a python api and analytics dashboard to monitor onchain activity on base", "region": "Global"}
        bot.run(fetchers={"x": lambda: items}, notify=self.notify, force=True, details_fn=stub)
        self.assertEqual(bot.db().execute("SELECT status FROM opps WHERE id='t-2'").fetchone()[0], "DRAFTED")
    def test_security_bounties_are_valued_as_long_shots(self):
        e = bot.estimate(opp(4, "Immunefi: X (up to $100,000)", reward=100000, kind="security", source="immunefi", subs=None, open_source=True, assets=2), self.pr)
        self.assertLess(e["ev_usd"], 100); self.assertGreaterEqual(e["effort_h"], 20)
        huge = bot.estimate(opp(5, "Immunefi: Y (up to $3,500,000)", reward=3_500_000, kind="security", source="immunefi", subs=None, open_source=True, assets=2), self.pr)
        self.assertLess(huge["score"], 2.0)                                                   # never outranks ordinary work on $/hour
        self.assertLessEqual(huge["ev_usd"], e["ev_usd"] * 3)                                 # EV must NOT scale with the headline cap
        decent = bot.estimate(opp(6, "Build a Python agent dashboard for Base", reward=1500, subs=4), self.pr)
        self.assertGreater(decent["score"], huge["score"] * 10)
    def test_lifecycle_new_to_drafted_and_the_bot_never_submits(self):
        s = self.run_([opp(1, "Build a Python agent dashboard for Base", reward=1500, subs=4), opp(2, "Make a meme video", reward=500, subs=300)])
        c = bot.db(); st = {r["id"]: r["status"] for r in c.execute("SELECT id,status FROM opps")}
        self.assertEqual(st["t-1"], "DRAFTED"); self.assertEqual(st["t-2"], "NEW"); self.assertEqual(s["drafted"], 1)
        self.assertFalse(any(v in ("SUBMITTED", "WON", "LOST") for v in st.values()))
        self.assertTrue((bot.DRAFTS / "t-1.md").exists())
    def test_draft_only_cites_profile_facts_and_lists_what_not_to_claim(self):
        self.run_([opp(1, "Build a Python agent dashboard for Base", reward=1500, subs=4)])
        txt = (bot.DRAFTS / "t-1.md").read_text()
        self.assertIn("Do NOT claim", txt); self.assertIn("no professional Solidity audit history", txt); self.assertIn(self.pr["facts"][0], txt); self.assertIn("never connect the trading wallet", txt.lower())
    def test_expired_items_are_closed_and_deadlines_alert_once(self):
        self.run_([opp(1, "Build a Python bot", reward=900, subs=3, deadline=iso_in(2))]); self.assertTrue(any("DEADLINE" in m for m in self.msgs))
        n = len(self.msgs); self.run_([opp(1, "Build a Python bot", reward=900, subs=3, deadline=iso_in(2))]); self.assertEqual(len([m for m in self.msgs if "DEADLINE" in m]), 1)   # no repeat spam
        c = bot.db(); c.execute("UPDATE opps SET deadline=? WHERE id='t-1'", (iso_in(-1),)); c.commit(); self.run_([])
        self.assertEqual(bot.db().execute("SELECT status FROM opps WHERE id='t-1'").fetchone()[0], "EXPIRED")
    def test_human_commands_and_digest(self):
        self.run_([opp(1, "Build a Python agent dashboard for Base", reward=1500, subs=4)])
        self.assertIn("SUBMITTED", bot.mark("t-1", "SUBMITTED", "sent by me")); self.assertIn("WON", bot.mark("t-1", "WON", "paid $400"))
        self.assertIn("no opportunity", bot.mark("zzz", "SKIPPED")); self.assertIn("Opportunity pipeline digest", bot.DIGEST.read_text())
    def test_lead_followups_come_due(self):
        bot.add_lead("Acme DAO", "https://example.org"); bot.lead_contacted(1)
        c = bot.db(); c.execute("UPDATE leads SET next_followup=? WHERE id=1", (iso_in(-1),)); c.commit()
        self.run_([]); self.assertTrue(any("follow up with lead 'Acme DAO'" in m for m in self.msgs))
    def test_interval_gating(self):
        self.assertIsNotNone(self.run_([])); self.assertIsNone(bot.run(fetchers={"x": lambda: []}, notify=self.notify))     # second call inside 6h is a no-op
    def test_a_failing_source_does_not_stop_the_run(self):
        def boom(): raise RuntimeError("503")
        s = bot.run(fetchers={"bad": boom, "ok": lambda: [opp(1, "Build a Python bot", subs=2)]}, notify=self.notify, force=True)
        self.assertEqual(s["new"], 1); self.assertTrue(s["errors"])
if __name__ == "__main__": unittest.main()

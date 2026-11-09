"""Pre-registered day-30 review (see docs/12-forward-test-plan.md). Stdlib only so it can be unit-tested without the lab venv."""
import datetime, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
REVIEWS = ROOT / "docs" / "reviews"

def classify(c):
    """Day-30 rules, exactly as pre-registered. No promotion happens at day 30."""
    if c.get("liquidated"): return "LIQUIDATED: drop"
    lag = c["bh_ret"] - c["ret"]
    if lag > 0.15 and c["maxdd"] < c["bh_maxdd"]: return "CLEARLY LAGGING: drop"
    return "CONTINUE"

def render(results, asof, price):
    rows = sorted(results, key=lambda c: -(c["ret"] - c["bh_ret"]))
    first = min(c["registered_at"] for c in rows)
    L = [f"# Forward paper trading: day-30 review", "",
         f"Generated {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC from data up to {asof[:16]} UTC. ETH = ${price:,.0f}. First cohort registered {first[:16]} UTC.", "",
         "**This is a sanity screen, not evidence of an edge.** With about 30 daily observations only an annualised Sharpe above ~5.8 could be told apart from luck, and with "
         f"{len(rows)} accounts one or two will look good by chance. Nothing is promoted at day 30 (see `docs/12-forward-test-plan.md`).", "",
         "| Strategy | Risk | Days | Return | Hold ETH | Excess | Worst drop | Hold worst drop | Trades | Verdict |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for c in rows:
        L.append(f"| {c['name']} | {c['risk']} | {c['days']:.1f} | {c['ret']:+.1%} | {c['bh_ret']:+.1%} | {c['ret'] - c['bh_ret']:+.1%} | {c['maxdd']:.1%} | {c['bh_maxdd']:.1%} | {c.get('trades', 0)} | {classify(c)} |")
    cont = [c for c in rows if classify(c) == "CONTINUE"]
    L += ["", f"**Continue:** {len(cont)} of {len(rows)}. **Dropped:** {len(rows) - len(cont)}.", "",
          "## Next", "* Day 90 (about 2027-02-07): candidate rules in the plan (return >= hold, worst drop <= 75% of hold's, no liquidation).",
          "* Day 180 (about 2027-05-08): the earliest a capped $5 spot canary can be considered, and only if the 180 days include both a +20% and a -20% ETH swing.",
          "* If the market was one-directional for these 30 days, treat the table above as even less informative."]
    return "\n".join(L) + "\n"

def maybe_write(results, asof, price, now=None):
    """Write the review once, when the FIRST cohort has >= 30 days. Returns the path or None."""
    if not results: return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    first = min(datetime.datetime.fromisoformat(c["registered_at"]) for c in results)
    if first.tzinfo is None: first = first.replace(tzinfo=datetime.timezone.utc)
    if (now - first).days < 30: return None
    REVIEWS.mkdir(parents=True, exist_ok=True)
    path = REVIEWS / f"paper-day30-{first.date() + datetime.timedelta(days=30)}.md"
    if path.exists(): return str(path)
    path.write_text(render(results, asof, price))
    outbox = ROOT / "data" / "outbox.log"
    with open(outbox, "a") as f: f.write(f"{now:%Y-%m-%dT%H:%M:%S}+00:00 [INFO] PAPER-TRADING DAY-30 REVIEW READY: {path}\n")
    return str(path)

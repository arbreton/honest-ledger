"""Opportunity pipeline bot. Discovers, scores, drafts, tracks and nudges. It NEVER submits an application or contacts anyone:
a human does that, then records it with `pipeline submitted <id>`. Stdlib only; runs inside the existing 15-minute tick."""
import hashlib, json, pathlib, re, sqlite3, time, urllib.request, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "pipeline.db"
DRAFTS = ROOT / "data" / "pipeline" / "drafts"
DIGEST = ROOT / "data" / "pipeline_digest.md"
UA = {"User-Agent": "honest-ledger-pipeline/0.1 (+https://github.com/arbreton/honest-ledger)"}
STATUSES = ("NEW", "SHORTLISTED", "DRAFTED", "SUBMITTED", "WON", "LOST", "EXPIRED", "SKIPPED")

def cfg(): return json.loads((pathlib.Path(__file__).parent / "config.json").read_text())
def profile(): return json.loads((pathlib.Path(__file__).parent / "profile.json").read_text())
def now_iso(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=60); c.row_factory = sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS opps(id TEXT PRIMARY KEY, source TEXT, kind TEXT, title TEXT, url TEXT, reward_usd REAL, deadline TEXT, competition INTEGER,
        effort_h REAL, ev_usd REAL, score REAL, fit TEXT, status TEXT, first_seen TEXT, last_seen TEXT, draft TEXT, note TEXT, alerted TEXT);
      CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY, name TEXT, url TEXT, pitch TEXT, status TEXT, created TEXT, last_contact TEXT, next_followup TEXT, note TEXT);
      CREATE TABLE IF NOT EXISTS watch(url TEXT PRIMARY KEY, sha TEXT, changed_at TEXT);
      CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, ts TEXT, summary TEXT);""")
    return c

def _get(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

# ---------- sources (public endpoints only) ----------
def fetch_superteam():
    out = []
    for l in json.loads(_get("https://earn.superteam.fun/api/listings?take=100")):
        if l.get("status") != "OPEN" or l.get("type") not in ("bounty", "project", "hackathon"): continue
        usd = float(l.get("rewardAmount") or 0) if str(l.get("token", "")).upper() in ("USDC", "USDT", "USDG", "USD", "PYUSD") else 0.0
        out.append({"id": "st-" + l["id"][:8], "source": "superteam", "kind": l["type"], "title": l["title"], "url": f"https://earn.superteam.fun/listing/{l['slug']}",
                    "reward_usd": usd, "reward_note": f"{l.get('rewardAmount')} {l.get('token')}", "deadline": (l.get("deadline") or "")[:10],
                    "competition": (l.get("_count") or {}).get("Submission"), "agent_ok": l.get("agentAccess"), "sponsor": (l.get("sponsor") or {}).get("name")})
    return out

def fetch_immunefi(c):
    out = []; ic = c["immunefi"]
    for p in json.loads(_get("https://immunefi.com/public-api/bounties.json")):
        if p.get("isPaused") or p.get("inviteOnly") or (p.get("maxBounty") or 0) < ic["min_max_bounty"]: continue
        if not set(p.get("language") or []) & set(ic["languages"]): continue
        if not set(p.get("ecosystem") or []) & set(ic["ecosystems"]): continue
        out.append({"id": "im-" + str(p["slug"])[:24], "source": "immunefi", "kind": "security", "title": f"Immunefi: {p['project']} (up to ${p['maxBounty']:,})", "url": f"https://immunefi.com/bug-bounty/{p['slug']}/",
                    "reward_usd": float(p["maxBounty"]), "deadline": "", "competition": None, "kyc": p.get("kyc"), "assets": len(p.get("assets") or []), "open_source": bool(p.get("githubUrl")),
                    "updated": str(p.get("updatedDate"))[:10]})
    out.sort(key=lambda o: (not o["open_source"], o["assets"], -o["reward_usd"]))
    return out[:ic["max_results"]]

def fetch_superteam_details(o):
    """Full listing text + region, for the few items about to be drafted. Public endpoint; failures just mean 'not refined'."""
    slug = o["url"].rsplit("/", 1)[-1]
    d = json.loads(_get(f"https://earn.superteam.fun/api/listings/details/{slug}"))
    import re
    return {"text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", d.get("description") or "")).lower(), "region": d.get("region"), "agent": d.get("agentAccess")}

def refine(o, d, pr):
    """Adjust fit using the real description. Returns (multiplier, reasons)."""
    t, m, why = d.get("text", ""), 1.0, []
    off_stack = any(k in t for k in ("solana", "anchor", "rust program")) and not any(k in t for k in ("ethereum", "evm", "base chain", "on base"))
    if d.get("region") not in (None, "Global"): m *= 0.2; why.append(f"region-limited ({d.get('region')})")
    if off_stack: m *= 0.2; why.append("outside the proven EVM stack (firm demotion, no bonus applies)")
    if any(k in t for k in ("marketing", "grow your", "bring users", "real users", "community growth", "make money while you sleep")): m *= 0.6; why.append("growth/marketing heavy")
    if not off_stack and any(k in t for k in ("python", "typescript", "api", "indexer", "analytics", "dashboard", "monitor", "reconcil")): m *= 1.25; why.append("technical match")
    return m, why

# ---------- scoring ----------
HARD_NO = {"video", "logo", "design", "translation", "translate", "meme", "animation", "illustration", "tiktok", "instagram", "podcast", "trading competition", "trading contest", "giveaway"}

def fit_hits(title, pr, url=""):
    t = (title + " " + url.rsplit("/", 1)[-1].replace("-", " ")).lower()      # the link slug often reveals what the title hides ("...-video-chile-colombia")
    return [k for k in pr["keywords_positive"] if k in t], [k for k in pr["keywords_negative"] if k in t]

def estimate(o, pr):
    """Expected $ and hours. Deliberately crude and conservative; shown so the human can overrule it."""
    pos, neg = fit_hits(o["title"], pr, o.get("url", ""))
    if o["source"] == "immunefi":
        # A first finding is usually a medium/low bug paying a few thousand dollars, never a % of the headline cap, and the biggest,
        # most-audited programs are the LEAST likely to yield one. Odds are small and unproven, so EV is capped and never scales with maxBounty.
        effort = 25.0
        p = 0.002 + (0.002 if o.get("open_source") else 0) + (0.002 if o.get("assets", 99) <= 5 else 0) - (0.002 if o["reward_usd"] >= 1_000_000 else 0)
        typical = min(5000.0, 0.02 * o["reward_usd"])
        ev = max(0.0, p) * typical
        fit = 0.5
    else:
        fit = max(0.15, min(1.5, 0.7 + 0.25 * len(pos) - 0.6 * len(neg)))
        if any(k in neg for k in HARD_NO): fit *= 0.1                                        # wrong kind of work entirely (video, design, trading contests...)
        if any(k in (o["title"] + " " + o.get("url", "")).lower() for k in ("solana", "sui ", "aptos", "ton ")) and not any(k in pos for k in ("base", "ethereum", "onchain")): fit *= 0.4   # outside the proven stack (EVM)
        subs = o.get("competition"); winners = 3 if o["reward_usd"] >= 500 else 1
        p = min(0.6, winners / ((subs if subs is not None else 30) + winners))
        ev = o["reward_usd"] * p * fit
        effort = 8.0 if o["kind"] in ("project", "hackathon") or any(k in o["title"].lower() for k in ("build", "develop", "integrat", "bot", "tool")) else 2.5
    return {"ev_usd": round(ev, 2), "effort_h": effort, "score": round(ev / effort, 2), "fit": f"+{pos[:5]} -{neg[:3]}"}

# ---------- persistence + state machine ----------
def upsert(c, o, pr):
    est = estimate(o, pr); t = now_iso()
    row = c.execute("SELECT status FROM opps WHERE id=?", (o["id"],)).fetchone()
    if row:
        c.execute("UPDATE opps SET last_seen=?, reward_usd=?, deadline=?, competition=?, ev_usd=?, score=?, effort_h=?, fit=? WHERE id=?",
                  (t, o["reward_usd"], o["deadline"], o["competition"], est["ev_usd"], est["score"], est["effort_h"], est["fit"], o["id"])); return False
    c.execute("INSERT INTO opps VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (o["id"], o["source"], o["kind"], o["title"], o["url"], o["reward_usd"], o["deadline"], o["competition"],
              est["effort_h"], est["ev_usd"], est["score"], est["fit"], "NEW", t, t, None, "", None)); return True

def hours_to(deadline):
    try: return (datetime.datetime.fromisoformat(deadline + "T23:59:00+00:00") - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600
    except Exception: return None

def draft_packet(o, pr):
    facts = "\n".join(f"- {f}" for f in pr["facts"][:5])
    kind = o["kind"]
    ask = {"security": "Review scope and known issues, read the in-scope contracts, and write findings only if a concrete, reproducible issue exists. No finding = no submission.",
           "bounty": "Deliver exactly what the listing asks, with one concrete, checkable detail drawn from the repo (a real number, a real transaction, a real test).",
           "project": "Propose a small, scoped deliverable with a price and a date; point at the repo as proof of working style.",
           "hackathon": "Pick one narrow, demoable idea; reuse the ledger/gate/signer components rather than starting from scratch."}.get(kind, "Read the listing carefully.")
    return f"""---
id: {o['id']}
status: DRAFTED
needs_polish: true   # a human (or the assistant, when asked) should tailor this before anything is sent
---
# {o['title']}
* Link: {o['url']}
* Reward: {o['reward_usd']:,.0f} USD-equivalent | Deadline: {o['deadline'] or 'rolling'} | Competition: {o['competition'] if o['competition'] is not None else 'unknown'}
* Expected value (crude): ${o['ev_usd']} for about {o['effort_h']} hours, i.e. ${o['score']}/hour

## Approach
{ask}

## True, checkable things to cite (from pipeline/profile.json)
{facts}

## Do NOT claim
{'; '.join(pr['not_claimed'])}

## Draft opening (edit before use)
Hi, I'm {pr['handle']}. {pr['headline']}. Relevant proof you can verify yourself: {pr['repo']}. For this I would [one sentence on the exact deliverable], and I can deliver by [date]. I'm happy to start with a small paid trial.

## Before submitting
- [ ] Re-read the listing and rules; confirm eligibility, payout token and any KYC
- [ ] Never connect the trading wallet to any site; use a fresh address for payouts
- [ ] Record it: `python3 -m farmv2 pipeline submitted {o['id']}`
"""

def watch_pages(c, urls):
    changed = []
    for u in urls:
        try: body = _get(u)
        except Exception: continue
        sha = hashlib.sha256(body).hexdigest(); r = c.execute("SELECT sha FROM watch WHERE url=?", (u,)).fetchone()
        if not r: c.execute("INSERT INTO watch VALUES(?,?,?)", (u, sha, now_iso()))
        elif r["sha"] != sha: c.execute("UPDATE watch SET sha=?, changed_at=? WHERE url=?", (sha, now_iso(), u)); changed.append(u)
    return changed

def run(fetchers=None, notify=None, force=False, details_fn=None):
    """One pass. `fetchers` lets tests inject data; `notify(level, text)` receives alerts."""
    C, pr = cfg(), profile(); c = db(); notify = notify or (lambda *a: None)
    last = c.execute("SELECT ts FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if last and not force and (time.time() - datetime.datetime.fromisoformat(last["ts"]).timestamp()) < C["interval_hours"] * 3600 - 300: return None
    stats = {"new": 0, "drafted": 0, "expired": 0, "alerts": 0, "errors": []}
    fs = fetchers or {"superteam": fetch_superteam, "immunefi": lambda: fetch_immunefi(C)}
    for name, fn in fs.items():
        try:
            for o in fn(): stats["new"] += upsert(c, o, pr)
        except Exception as e: stats["errors"].append(f"{name}: {str(e)[:80]}")
    for u in (watch_pages(c, C["watch_pages"]) if fetchers is None else []):
        notify("INFO", f"Funding page changed, worth a look: {u}"); stats["alerts"] += 1
    for r in c.execute("SELECT * FROM opps WHERE status IN ('NEW','SHORTLISTED','DRAFTED')").fetchall():
        h = hours_to(r["deadline"]) if r["deadline"] else None
        if h is not None and h < 0: c.execute("UPDATE opps SET status='EXPIRED' WHERE id=?", (r["id"],)); stats["expired"] += 1; continue
        if r["status"] == "NEW" and r["score"] >= C["shortlist_min_score"] and (h is None or h > 24): c.execute("UPDATE opps SET status='SHORTLISTED' WHERE id=?", (r["id"],))
    details_fn = details_fn if details_fn is not None else (fetch_superteam_details if fetchers is None else None)
    if details_fn:                                       # read the full text of the few items about to be drafted, then re-rank
        for r in c.execute("SELECT * FROM opps WHERE status='SHORTLISTED' AND source='superteam' AND (note IS NULL OR note NOT LIKE 'refined:%') ORDER BY score DESC LIMIT 6").fetchall():
            try:
                m, why = refine(dict(r), details_fn(dict(r)), pr); sc = round(r["score"] * m, 2)
                c.execute("UPDATE opps SET score=?, ev_usd=?, note=?, status=? WHERE id=?", (sc, round(r["ev_usd"] * m, 2), "refined: " + ("; ".join(why) or "no change"), "SHORTLISTED" if sc >= C["shortlist_min_score"] else "NEW", r["id"]))
            except Exception: pass
    DRAFTS.mkdir(parents=True, exist_ok=True)
    for r in c.execute("SELECT * FROM opps WHERE status='SHORTLISTED' ORDER BY score DESC LIMIT ?", (C["max_new_drafts_per_run"],)).fetchall():
        o = dict(r); path = DRAFTS / f"{r['id']}.md"; path.write_text(draft_packet(o, pr) + (f"\n## Why the bot ranked it this way\n{r['note']}\n" if r["note"] else ""))
        c.execute("UPDATE opps SET status='DRAFTED', draft=? WHERE id=?", (str(path), r["id"])); stats["drafted"] += 1
        notify("INFO", f"Pipeline: draft ready for '{r['title'][:60]}' (${r['reward_usd']:,.0f}, ~${r['score']}/h expected). {path.name}")
    for r in c.execute("SELECT * FROM opps WHERE status='DRAFTED' AND deadline!='' AND (alerted IS NULL)").fetchall():
        h = hours_to(r["deadline"])
        if h is not None and 0 < h < C["deadline_alert_hours"]:
            notify("INFO", f"Pipeline DEADLINE in {h:.0f}h: {r['title'][:60]} - draft {pathlib.Path(r['draft']).name}"); c.execute("UPDATE opps SET alerted=? WHERE id=?", (now_iso(), r["id"])); stats["alerts"] += 1
    for r in c.execute("SELECT * FROM leads WHERE status IN ('CONTACTED','FOLLOWUP') AND next_followup IS NOT NULL AND next_followup<=?", (now_iso()[:10],)).fetchall():
        notify("INFO", f"Pipeline: follow up with lead '{r['name']}' (last contact {r['last_contact']})"); stats["alerts"] += 1
    c.execute("INSERT INTO runs(ts,summary) VALUES(?,?)", (now_iso(), json.dumps(stats))); c.commit()
    write_digest(c); return stats

def counts(c): return {r["status"]: r["n"] for r in c.execute("SELECT status, count(*) n FROM opps GROUP BY status")}

def top_open(c, n=8):
    return [dict(r) for r in c.execute("SELECT id,source,kind,title,url,reward_usd,deadline,competition,ev_usd,effort_h,score,status FROM opps WHERE status IN ('NEW','SHORTLISTED','DRAFTED') ORDER BY score DESC LIMIT ?", (n,))]

def write_digest(c):
    cn = counts(c); L = [f"# Opportunity pipeline digest ({now_iso()[:16]} UTC)", "", "Status: " + ", ".join(f"{k} {v}" for k, v in sorted(cn.items())), "", "## Next actions for you (the bot never submits or contacts anyone)"]
    dr = c.execute("SELECT * FROM opps WHERE status='DRAFTED' ORDER BY score DESC LIMIT 5").fetchall()
    for r in dr: L.append(f"* Review + send: **{r['title'][:70]}** (${r['reward_usd']:,.0f}, {r['competition'] if r['competition'] is not None else '?'} submissions, deadline {r['deadline'] or 'rolling'}) -> `{r['draft']}`")
    if not dr: L.append("* Nothing drafted yet.")
    for r in c.execute("SELECT * FROM leads WHERE status IN ('CONTACTED','FOLLOWUP') AND next_followup<=? ORDER BY next_followup", (now_iso()[:10],)): L.append(f"* Follow up with lead **{r['name']}** (due {r['next_followup']})")
    L += ["", "## Highest expected value still open"] + [f"* ${o['score']}/h  ${o['reward_usd']:,.0f}  {o['title'][:70]}  [{o['status']}]  {o['url']}" for o in top_open(c, 8)]
    DIGEST.parent.mkdir(parents=True, exist_ok=True); DIGEST.write_text("\n".join(L) + "\n")

# ---------- human-in-the-loop commands ----------
def mark(oid, status, note=""):
    c = db(); r = c.execute("SELECT id FROM opps WHERE id LIKE ?", (oid + "%",)).fetchone()
    if not r: return f"no opportunity matches {oid}"
    c.execute("UPDATE opps SET status=?, note=? WHERE id=?", (status, note, r["id"])); c.commit(); write_digest(c); return f"{r['id']} -> {status}"

def add_lead(name, url, pitch=""):
    c = db(); c.execute("INSERT INTO leads(name,url,pitch,status,created) VALUES(?,?,?,?,?)", (name, url, pitch, "NEW", now_iso())); c.commit(); return "lead added"

def lead_contacted(lead_id):
    C = cfg(); c = db(); nxt = (datetime.date.today() + datetime.timedelta(days=C["lead_followup_days"][0])).isoformat()
    c.execute("UPDATE leads SET status='CONTACTED', last_contact=?, next_followup=? WHERE id=?", (now_iso()[:10], nxt, lead_id)); c.commit(); return f"lead {lead_id} contacted; follow-up on {nxt}"

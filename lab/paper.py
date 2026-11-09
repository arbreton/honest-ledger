"""Forward paper trading. Strategies are REGISTERED (frozen, timestamped) before they trade; results use only bars after registration.
Paper accounts use the same cost/funding/liquidation model as the backtests. No keys, no network except public candles."""
import json, pathlib, sqlite3, datetime
import numpy as np, pandas as pd
from . import data, strategies as S, backtest as B, stats

ROOT = pathlib.Path(__file__).resolve().parent
DB = ROOT.parent / "data" / "lab.db"
MIN_DAYS_FOR_REVIEW = 30

BASELINES = [   # pre-registered; chosen to answer the operator's questions, NOT tuned on results
    ("hold ETH (benchmark)", {"family": "hold", "params": {}, "lev": 1.0, "perp": False}, "benchmark", "low"),
    ("trend: price>SMA720, long/flat", {"family": "price_sma", "params": {"n": 720}, "lev": 1.0, "perp": False}, "classic trend filter", "low"),
    ("trend + vol-target", {"family": "trend_vt", "params": {"n": 500, "tv": 0.5}, "lev": 1.0, "perp": False}, "trend with risk scaling", "low"),
    ("vol-managed hold (target 50%)", {"family": "vol_managed", "params": {"tv": 0.5}, "lev": 1.0, "perp": False}, "always long, size down when volatile", "low"),
    ("buy the dip (-8%/72h, hold 72h)", {"family": "dip_buy", "params": {"n": 72, "drop": 0.08, "hold": 72}, "lev": 1.0, "perp": False}, "retail instinct", "medium"),
    ("momentum 30d, long/flat", {"family": "mom", "params": {"n": 720}, "lev": 1.0, "perp": False}, "rally thesis: ride strength", "low"),
    ("long/short trend SMA720 (perp 1x)", {"family": "price_sma", "params": {"n": 720, "ls": True}, "lev": 1.0, "perp": True}, "short the downtrends too", "medium"),
    ("3x long trend SMA720 (perp, fixed margin)", {"family": "price_sma", "params": {"n": 720}, "lev": 3.0, "perp": True}, "the 'real risk' case", "HIGH"),
]

def _db():
    DB.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB, timeout=60); c.row_factory = sqlite3.Row
    c.executescript("""CREATE TABLE IF NOT EXISTS champions(name TEXT PRIMARY KEY, config TEXT NOT NULL, registered_at TEXT NOT NULL, note TEXT, risk TEXT);
                       CREATE TABLE IF NOT EXISTS paper_results(name TEXT, asof TEXT, payload TEXT NOT NULL, PRIMARY KEY(name, asof));""")
    return c

def register(name, cfg, note="", risk="low", at=None):
    c = _db()
    c.execute("INSERT OR IGNORE INTO champions VALUES(?,?,?,?,?)", (name, json.dumps(cfg), at or pd.Timestamp.now(tz="UTC").floor("h").isoformat(), note, risk)); c.commit()

def ensure_baselines():
    for n, cfg, note, risk in BASELINES: register(n, cfg, note, risk)

def evaluate(eth, fund, name, cfg, start):
    pos = S.position(eth, cfg)
    pre = eth.index[eth.index <= start]
    if len(pre) == 0: return None
    s0 = pre[-1]
    sl = eth.loc[s0:]; ps = pos.loc[s0:]
    if len(sl) < 3:
        return {"name": name, "days": 0.0, "equity": 1.0, "ret": 0.0, "bh_ret": 0.0, "maxdd": 0.0, "bh_maxdd": 0.0, "liquidated": False,
                "exposure_now": float(pos.iloc[-1]), "daily_obs": 0, "trades": 0}
    eq, info = B.run(sl, ps, lev=cfg["lev"], perp=cfg["perp"], fund=fund)
    bh, _ = B.run(sl, S.position(sl, {"family": "hold", "params": {}}))
    days = (sl.index[-1] - sl.index[0]).total_seconds() / 86400
    d = stats.daily(eq)
    return {"name": name, "days": round(days, 2), "equity": float(eq.iloc[-1]), "ret": float(eq.iloc[-1] - 1), "bh_ret": float(bh.iloc[-1] - 1),
            "maxdd": float((eq / eq.cummax() - 1).min()), "bh_maxdd": float((bh / bh.cummax() - 1).min()), "liquidated": bool(info["liquidated"]),
            "exposure_now": float(ps.iloc[-1]), "daily_obs": int(len(d)),
            "trades": int((ps.diff().abs() > 1e-9).sum())}

def tick():
    ensure_baselines()
    eth, fund = data.load("ETHUSDT", "1h"), data.funding("ETHUSDT")
    data.load("BTCUSDT", "1h")
    c = _db(); out = []
    for r in c.execute("SELECT * FROM champions ORDER BY registered_at, name").fetchall():
        res = evaluate(eth, fund, r["name"], json.loads(r["config"]), pd.Timestamp(r["registered_at"]))
        if not res: continue
        res.update(registered_at=r["registered_at"], risk=r["risk"], note=r["note"])
        res["status"] = ("LIQUIDATED" if res.get("liquidated") else
                         "too early" if res["days"] < MIN_DAYS_FOR_REVIEW else
                         "review: beat buy&hold" if res["ret"] > res["bh_ret"] and res["maxdd"] >= res["bh_maxdd"] * 0.9 else "review: did not beat buy&hold")
        out.append(res)
    asof = eth.index[-1].isoformat()
    c.execute("INSERT OR REPLACE INTO paper_results VALUES(?,?,?)", ("ALL", asof, json.dumps(out))); c.commit()
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "paper.json").write_text(json.dumps({"asof": asof, "price": float(eth.close.iloc[-1]), "champions": out}, indent=1))
    try:
        from . import review
        rv = review.maybe_write(out, asof, float(eth.close.iloc[-1]))
        if rv: (ROOT / "results" / "review.json").write_text(json.dumps({"path": rv}))
    except Exception: pass
    return out

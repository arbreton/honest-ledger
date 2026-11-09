"""Cycle study: find the real tops and bottoms (zigzag on daily closes), measure what each cycle did, and place today in it.
Descriptive, NOT a forecast: with ~2-3 completed cycles there is no statistical power to validate a cycle model."""
import json, pathlib, numpy as np, pandas as pd
from . import data

OUT = pathlib.Path(__file__).resolve().parent / "results" / "cycles.json"

def zigzag(close, thr=0.40):
    """Pivots where price reverses by >= thr from the running extreme. Causal only in the sense that the LAST pivot is provisional."""
    idx, c = close.index, close.to_numpy(); piv = []; hi_i = lo_i = 0; mode = 0
    for i in range(1, len(c)):
        if c[i] > c[hi_i]: hi_i = i
        if c[i] < c[lo_i]: lo_i = i
        if mode >= 0 and c[i] <= c[hi_i] * (1 - thr):          # fell thr from the high: that high was a TOP
            piv.append((idx[hi_i], c[hi_i], "top")); mode = -1; lo_i = i; hi_i = i
        elif mode <= 0 and c[i] >= c[lo_i] * (1 + thr):        # rose thr from the low: that low was a BOTTOM
            piv.append((idx[lo_i], c[lo_i], "bottom")); mode = 1; hi_i = i; lo_i = i
    # the current leg's extreme is provisional
    if mode == 1: piv.append((idx[hi_i], c[hi_i], "top?"))
    elif mode == -1: piv.append((idx[lo_i], c[lo_i], "bottom?"))
    return piv

def run(symbol="ETHUSDT", thr=0.40):
    d = data.daily_long(symbol); c = d.close
    sma200 = c.rolling(200).mean(); mayer = c / sma200; ath = c.cummax(); dd = c / ath - 1
    piv = zigzag(c, thr); rows = []
    for k, (t, p, typ) in enumerate(piv):
        prev = piv[k - 1] if k else None
        rows.append({"date": str(t.date()), "price": float(p), "type": typ, "move_from_prev": (float(p / prev[1] - 1) if prev else None), "days_from_prev": (int((t - prev[0]).days) if prev else None),
                     "drawdown_from_ath": float(dd.loc[t]), "mayer": (float(mayer.loc[t]) if np.isfinite(mayer.loc[t]) else None)})
    tops = [r for r in rows if r["type"].startswith("top")]; bots = [r for r in rows if r["type"].startswith("bottom")]
    cyc = []
    for i, b in enumerate(rows):
        if b["type"].startswith("bottom") and i + 1 < len(rows) and rows[i + 1]["type"].startswith("top"):
            cyc.append({"bottom": b["date"], "bottom_price": b["price"], "top": rows[i + 1]["date"], "top_price": rows[i + 1]["price"], "multiple": rows[i + 1]["price"] / b["price"],
                        "days_up": rows[i + 1]["days_from_prev"], "provisional": rows[i + 1]["type"].endswith("?")})
    last = float(c.iloc[-1]); ath_p = float(ath.iloc[-1]); ath_d = str(c.idxmax().date())
    # forward returns from similar conditions (few independent episodes: shown to be honest about how thin it is)
    fwd = c.shift(-365) / c - 1
    cond = (dd <= -0.50) & (dd >= -0.70) & (mayer < 1.0)
    ep = []
    in_ep = False
    for t, v in cond.items():
        if v and not in_ep: ep.append([t, t]); in_ep = True
        elif v and in_ep: ep[-1][1] = t
        elif not v: in_ep = False
    episodes = [{"from": str(a.date()), "to": str(b.date()), "days": int((b - a).days) + 1, "fwd_365d_from_start": (float(fwd.loc[a]) if np.isfinite(fwd.loc[a]) else None),
                 "fwd_365d_median_in_episode": (float(fwd.loc[a:b].median()) if fwd.loc[a:b].notna().any() else None)} for a, b in ep if (b - a).days >= 10]
    need8 = last * 8
    out = {"symbol": symbol, "from": str(c.index[0].date()), "to": str(c.index[-1].date()), "threshold": thr, "pivots": rows, "cycles": cyc,
           "now": {"price": last, "ath": ath_p, "ath_date": ath_d, "drawdown_from_ath": float(dd.iloc[-1]), "mayer": float(mayer.iloc[-1]), "above_200d": bool(last > sma200.iloc[-1]),
                   "days_since_ath": int((c.index[-1] - c.idxmax()).days), "x_to_reclaim_ath": ath_p / last, "price_for_8x": need8, "eight_x_vs_ath": need8 / ath_p},
           "similar_conditions": {"definition": "drawdown from ATH between -50% and -70% AND below the 200-day average", "episodes": episodes},
           "mayer_at_tops": [r["mayer"] for r in tops if r["mayer"]], "mayer_at_bottoms": [r["mayer"] for r in bots if r["mayer"]]}
    OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps(out, indent=1, default=str)); return out

if __name__ == "__main__": run()

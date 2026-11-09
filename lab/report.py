"""Merge sweep + paper results into one JSON the dashboard can show, plus an honest plain-language verdict."""
import json, pathlib, pandas as pd
ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT.parent / "data" / "lab_report.json"

def verdict(sw):
    if not sw: return "No sweep has finished yet."
    n, s, p = sw["n_trials"], sw["n_survivors"], sw["reality_check_p"]
    f = sw["frac_beating_bh"]
    base = (f"{n} strategies tested ({sw['n_ml']} ML) on identical windows with realistic costs, funding and liquidation. "
            f"{s} passed every gate. Reality-check p = {p:.2f} (below 0.05 would mean the best result is unlikely to be luck). "
            f"Only {f['select']:.0%} beat buy-and-hold in the 2023-24 bull, {f['valid']:.0%} in 2025 and {f['holdout']:.0%} in 2026: "
            f"most 'wins' are strategies that were simply out of a falling market, not an edge.")
    if s == 0: return base + " Verdict: no formula found yet. Nothing is promoted; the lab keeps testing and forward-paper-trading."
    ok = [x for x in sw["survivors"] if x.get("holdout_beats")]
    return base + f" {len(ok)} of the survivors also beat buy-and-hold on the untouched 2026 holdout; they enter forward paper trading before any capital."

def _families():
    """Per-family scoreboard from the full sweep, so every idea the operator asked about is visible with its result."""
    try: rows = json.loads((ROOT / "results" / "all_rows.json").read_text()); sw = json.loads((ROOT / "results" / "latest.json").read_text())
    except Exception: return None
    bh = sw["benchmark"]; ok = lambda m: m and m.get("ok")
    def beat(r, w): return bool(ok(r[w]) and r[w]["sharpe"] > bh[w]["sharpe"] and (r[w]["cagr"] > bh[w]["cagr"] or r[w]["maxdd"] > bh[w]["maxdd"] * 0.75) and r[w].get("min_equity", 1) > 0.5)
    names = {"fib": "Fibonacci retracements", "weekly_sma": "Weekly SMA trend", "weekly_break": "Weekly breakout", "week_open_bias": "Above/below weekly open", "prev_week": "Previous-week direction",
             "session": "Session hours (Asia/Europe/US)", "weekday": "Day of week", "runner": "Runner when weekly/monthly is red", "cycle": "Cycle runner (drawdown + Mayer)", "ml": "Machine learning (144 models)",
             "price_sma": "Price vs SMA", "sma_cross": "SMA crossover", "ema_cross": "EMA crossover", "rsi_rev": "RSI", "bb_rev": "Bollinger reversion", "bb_break": "Bollinger breakout",
             "macd": "MACD", "donchian": "Donchian breakout", "mom": "Momentum", "dip_buy": "Buy the dip", "trend_vt": "Trend + vol target", "vol_managed": "Vol-managed"}
    fam = {}
    for r in rows:
        if r["family"] != "hold": fam.setdefault(r["family"], []).append(r)
    out = []
    for f, rs in fam.items():
        live = [r for r in rs if not r["liquidated"]] or rs
        best = lambda w: max((r[w]["sharpe"] for r in live if ok(r[w])), default=None)
        out.append({"family": names.get(f, f), "n": len(rs), "best_select": best("select"), "best_valid": best("valid"), "best_holdout": best("holdout"),
                    "beat": [sum(beat(r, w) for r in rs) for w in ("select", "valid", "holdout")], "passed": sum(r["passes"] for r in rs)})
    out.sort(key=lambda x: -(sum(x["beat"])) / max(1, x["n"]))
    return out

def build():
    try: sw = json.loads((ROOT / "results" / "latest.json").read_text())
    except Exception: sw = None
    try: pp = json.loads((ROOT / "results" / "paper.json").read_text())
    except Exception: pp = None
    def j(name):
        try: return json.loads((ROOT / "results" / name).read_text())
        except Exception: return None
    se, cy = j("seasonality.json"), j("cycles.json")
    rep = {"seasonality": ({"asia": se["asia_open_0_2"], "weekly": se["weekly"], "significant_hours": se["summary"]["hours_significant_after_bonferroni"],
                            "significant_days": se["summary"]["days_significant_after_bonferroni"], "busy_hours": sorted(se["volume_by_hour_pct_of_avg"].items(), key=lambda kv: -kv[1])[:3]} if se else None),
           "cycles": ({"now": cy["now"], "cycles": cy["cycles"], "similar": cy["similar_conditions"]["episodes"], "mayer_tops": cy["mayer_at_tops"], "mayer_bottoms": cy["mayer_at_bottoms"]} if cy else None),
           "families": _families(), "ml_quality": (sw or {}).get("ml_signal_quality"), "generated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "sweep": sw, "paper": pp, "verdict": verdict(sw),
           "rules": ["Strategies are judged on 2023-24 (select) and 2025 (validate); 2026 is a holdout looked at once, only for survivors.",
                     "A strategy must beat buy-and-hold risk-adjusted in BOTH windows, survive without liquidation, stay good when its parameters are nudged, and clear a deflated-Sharpe test that charges for how many strategies were tried.",
                     "Passing is not live trading: survivors must also win 30+ days of forward paper trading before a capped canary, and perps/leverage need a venue integration that does not exist yet."]}
    OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps(rep, default=str)); return rep

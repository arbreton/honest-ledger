"""The research sweep: every config is evaluated on identical windows; selection uses only SELECT + VALIDATE; HOLDOUT is looked at once, for survivors only.
Gates (all must pass): beats buy&hold risk-adjusted in BOTH windows, no blow-up, deflated Sharpe vs ALL trials, parameter plateau, sane turnover."""
import json, time, pathlib, sys
import numpy as np, pandas as pd
from . import data, strategies as S, backtest as B, stats, ml

ROOT = pathlib.Path(__file__).resolve().parent
W = {"select": ("2023-01-01", "2024-12-31"), "valid": ("2025-01-01", "2025-12-31"), "holdout": ("2026-01-01", None)}

def _wm(eq, w):
    a, b = W[w]; s = B.window(eq, a, b)
    m = B.metrics(s); m["min_equity"] = float(s.min()) if len(s) else 0.0; return m, stats.daily(s)

def beats(m, bh):
    """Risk-adjusted win over buy&hold: higher Sharpe AND (higher CAGR OR a >=25% shallower drawdown), without blowing up."""
    if not m.get("ok"): return False
    return m["sharpe"] > bh["sharpe"] and (m["cagr"] > bh["cagr"] or m["maxdd"] > bh["maxdd"] * 0.75) and m["min_equity"] > 0.5

def _h(v): return tuple(v) if isinstance(v, list) else v

CATEG = {"ls", "fs", "model", "mode", "direction", "days", "smooth"}      # categorical: must match exactly, never "adjacent"

def neighbours(cfg, cfgs):
    """Configs that differ from `cfg` in exactly ONE numeric parameter, by one grid step (used for the plateau test)."""
    cat = lambda c: tuple(sorted((k, _h(v)) for k, v in c["params"].items() if k in CATEG))
    key = lambda c: (c["family"], c["lev"], c["perp"], cat(c))
    same = [c for c in cfgs if key(c) == key(cfg) and c is not cfg]
    ks = [k for k in cfg["params"] if k not in CATEG]
    out = []
    for c in same:
        diff = [k for k in ks if _h(c["params"].get(k)) != _h(cfg["params"].get(k))]
        if len(diff) == 1:
            vals = sorted({_h(x["params"][diff[0]]) for x in same + [cfg] if diff[0] in x["params"]})
            i, j = vals.index(_h(cfg["params"][diff[0]])), vals.index(_h(c["params"][diff[0]]))
            if abs(i - j) == 1: out.append(c)
    return out

def run(quick=False, log=print):
    t0 = time.time()
    eth, btc, fund = data.load("ETHUSDT", "1h"), data.load("BTCUSDT", "1h"), data.funding("ETHUSDT")
    bh_eq, _ = B.run(eth, S.position(eth, {"family": "hold", "params": {}}))
    BH = {w: _wm(bh_eq, w) for w in W}
    cfgs = S.rule_configs()
    log(f"[{time.time()-t0:4.0f}s] rule-based configs: {len(cfgs)}")
    eqs = {}
    for c in cfgs:
        eq, info = B.run(eth, S.position(eth, c), lev=c["lev"], perp=c["perp"], fund=fund)
        eqs[id(c)] = (eq, info)
    mlc = [] if quick else ml.ml_configs() + ml.ml_configs_v2()
    ic = {}
    if mlc:
        FS = {"v1": ml.features(eth, btc, fund), "v2": ml.features_v2(eth, btc, fund)}; probs = {}
        fwd = {H: (eth.close.shift(-H) / eth.close - 1) for H in (24, 72)}
        for fs in ("v1", "v2"):
            for model in ml.MODELS:
                for H in (24, 72):
                    cf = ROOT / "results" / f"probs_{fs}_{model}_H{H}_{eth.index[-1].strftime('%Y%m%d%H')}.pkl"
                    if cf.exists(): pr = pd.read_pickle(cf)
                    else:
                        pr = ml.walk_forward(FS[fs], eth.close, model, H); pr.to_pickle(cf)
                    probs[(fs, model, H)] = pr
                    ok = pd.concat([pr, fwd[H]], axis=1).dropna()
                    ic[f"{fs}/{model}/H{H}"] = {"rank_ic": float(ok.corr(method="spearman").iloc[0, 1]), "n": int(len(ok)),
                                                "accuracy": float(((ok.iloc[:, 0] > 0.5) == (ok.iloc[:, 1] > 0)).mean()), "majority": float(max((ok.iloc[:, 1] > 0).mean(), (ok.iloc[:, 1] <= 0).mean()))}
                    log(f"[{time.time()-t0:4.0f}s] walk-forward {fs} {model} H={H}: rank IC {ic[f'{fs}/{model}/H{H}']['rank_ic']:+.3f}")
        for c in mlc:
            p = c["params"]; pos = ml.positions_from_prob(probs[(p.get("fs", "v1"), p["model"], p["H"])], p["thr"], p["smooth"], p["ls"])
            eqs[id(c)] = B.run(eth, pos, perp=p["ls"], fund=fund)
        cfgs = cfgs + mlc
    N = len(cfgs); log(f"[{time.time()-t0:4.0f}s] total trials N={N}")
    rows = []
    for c in cfgs:
        eq, info = eqs[id(c)]
        r = {"name": S.name(c) if c["family"] != "ml" else "ML " + "/".join(f"{k}={v}" for k, v in c["params"].items()),
             "family": c["family"], "tag": c.get("tag", "spot long-only"), "lev": c["lev"], "info": info, "cfg": c}
        for w in W:
            r[w], r[w + "_d"] = _wm(eq, w)
        rows.append(r)
    # trial-level Sharpe dispersion, for deflation
    sel_val = lambda r: pd.concat([r["select_d"], r["valid_d"]])
    sr_all = np.array([stats.sharpe_d(sel_val(r)) for r in rows]); sr_var = float(np.var(sr_all))
    bh_sv = pd.concat([BH["select"][1], BH["valid"][1]])
    for r in rows:
        r["beats_select"], r["beats_valid"] = beats(r["select"], BH["select"][0]), beats(r["valid"], BH["valid"][0])
        r["dsr"] = stats.dsr(sel_val(r), N, sr_var); r["psr"] = stats.psr(sel_val(r), stats.sharpe_d(bh_sv))
    byname = {id(r["cfg"]): r for r in rows}
    for r in rows:
        nb = neighbours(r["cfg"], cfgs)
        r["plateau"] = (np.mean([byname[id(n)]["beats_valid"] for n in nb]) if nb else 0.0) if r["family"] not in ("hold",) else 0.0
        r["gates"] = {"beats_select": r["beats_select"], "beats_valid": r["beats_valid"], "no_liquidation": not r["info"]["liquidated"],
                      "dsr>=0.90": r["dsr"] >= 0.90, "plateau>=60%": r["plateau"] >= 0.6 and len(nb) > 0, "turnover<=250/yr": r["info"]["turnover_per_year"] <= 250}
        r["passes"] = all(r["gates"].values()) and r["family"] != "hold"
    surv = [r for r in rows if r["passes"]]
    # reality check across ALL trials (are we just seeing the best of many random strategies?)
    ex = pd.DataFrame({i: (sel_val(r) - bh_sv.reindex(sel_val(r).index)).fillna(0) for i, r in enumerate(rows) if r["family"] != "hold"})
    rc_p = stats.reality_check(ex)
    # holdout is evaluated ONLY now, for survivors
    for r in surv: r["holdout_beats"] = beats(r["holdout"], BH["holdout"][0])
    fam = {}
    for r in rows:
        if r["family"] == "hold": continue
        fam.setdefault(r["tag"] if r["family"] != "ml" else r["name"].split(" ")[0] + " " + r["tag"], []).append(r["valid"]["sharpe"] - BH["valid"][0]["sharpe"] if r["valid"].get("ok") else np.nan)
    clean = lambda m: {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in m.items() if k != "n"}
    def view(r, with_hold):
        return {"name": r["name"], "tag": r["tag"], "family": r["family"], "gates": r["gates"], "dsr": round(r["dsr"], 3), "plateau": round(r["plateau"], 2),
                "turnover_per_year": round(r["info"]["turnover_per_year"], 1), "exposure": round(r["info"]["exposure"], 2),
                "select": clean(r["select"]), "valid": clean(r["valid"]), **({"holdout": clean(r["holdout"]), "holdout_beats": r.get("holdout_beats")} if with_hold else {})}
    ranked = sorted([r for r in rows if r["family"] != "hold"], key=lambda r: -(r["valid"].get("sharpe", -9) + r["select"].get("sharpe", -9)))
    out = {"generated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "data_end": str(eth.index[-1]), "n_trials": N, "n_ml": len(mlc),
           "windows": W, "benchmark": {w: clean(BH[w][0]) for w in W}, "reality_check_p": rc_p, "n_survivors": len(surv),
           "survivors": [view(r, True) for r in surv][:15],
           "best_failed": [view(r, False) for r in ranked if not r["passes"]][:12],
           "family_median_excess_sharpe_valid": {k: round(float(np.nanmedian(v)), 2) for k, v in fam.items()},
           "frac_beating_bh": {w: round(float(np.mean([beats(r[w], BH[w][0]) for r in rows if r["family"] != "hold"])), 3) for w in W},
           "liquidations": int(sum(r["info"]["liquidated"] for r in rows)), "ml_signal_quality": ic, "elapsed_s": round(time.time() - t0)}
    compact = [{"name": r["name"], "family": r["family"], "tag": r["tag"], "lev": r["lev"], "dsr": round(float(r["dsr"]), 4), "plateau": round(float(r["plateau"]), 2),
                "liquidated": r["info"]["liquidated"], "turnover": round(r["info"]["turnover_per_year"], 1), "exposure": round(r["info"]["exposure"], 3),
                "gates": r["gates"], "passes": r["passes"], **{w: clean(r[w]) for w in W}} for r in rows]
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "all_rows.json").write_text(json.dumps(compact, default=str))
    (ROOT / "results" / "latest.json").write_text(json.dumps(out, indent=1, default=str))
    log(f"[{time.time()-t0:4.0f}s] done: {len(surv)} survivors of {N}; reality-check p={rc_p:.3f}")
    return out

if __name__ == "__main__":
    run(quick="--quick" in sys.argv)

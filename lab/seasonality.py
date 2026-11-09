"""Raw pattern tests (no strategy, no costs): is there a time-of-day / weekday / weekly effect in ETH returns that survives multiple-comparison correction
and repeats year after year? Tests the operator's hypotheses: 'sells when the Asia session starts', 'jumps on the weekly'."""
import json, pathlib, numpy as np, pandas as pd
from scipy import stats as st
from . import data

OUT = pathlib.Path(__file__).resolve().parent / "results" / "seasonality.json"
SESSIONS = {"Asia (00-08 UTC)": range(0, 8), "Europe (08-13)": range(8, 13), "US (13-21)": range(13, 21), "Late US/Asia pre-open (21-24)": range(21, 24)}

def _t(x):
    if len(x) < 30 or x.std() == 0: return 0.0, 1.0
    t, p = st.ttest_1samp(x, 0.0); return float(t), float(p)

def run(symbol="ETHUSDT"):
    df = data.load(symbol, "1h"); r = np.log(df.close / df.close.shift(1)).dropna() * 1e4       # bps per hour
    idx = r.index; yrs = sorted(set(idx.year)); out = {"symbol": symbol, "bars": int(len(r)), "from": str(idx[0].date()), "to": str(idx[-1].date())}
    avg = r.mean()
    # --- hour of day (24 tests)
    hours = []
    for h in range(24):
        x = r[idx.hour == h]; t, p = _t(x)
        by = [float(np.sign(r[(idx.hour == h) & (idx.year == y)].mean())) for y in yrs]
        hours.append({"hour": h, "mean_bps": float(x.mean()), "t": t, "p": p, "pct_negative": float((x < 0).mean()), "p_bonf": min(1.0, p * 24),
                      "years_same_sign_as_overall": int(sum(1 for s in by if s == np.sign(x.mean()))), "years": len(yrs)})
    out["hours"] = hours; out["overall_mean_bps_per_hour"] = float(avg)
    # --- the Asia-open hypothesis: first hours after 00:00 UTC (Tokyo 09:00)
    a = r[idx.hour.isin([0, 1])]; rest = r[~idx.hour.isin([0, 1])]; t, p = st.ttest_ind(a, rest, equal_var=False)
    out["asia_open_0_2"] = {"mean_bps_per_2h": float(a.groupby([a.index.date]).sum().mean()), "rest_mean_bps_per_2h": float(rest.mean() * 2), "welch_t": float(t), "p": float(p),
                            "pct_days_negative": float((a.groupby(a.index.date).sum() < 0).mean()),
                            "by_year": {int(y): float(a[a.index.year == y].groupby(a[a.index.year == y].index.date).sum().mean()) for y in yrs}}
    # --- sessions
    out["sessions"] = {k: {"mean_bps_per_hour": float(r[idx.hour.isin(list(v))].mean()), "t": _t(r[idx.hour.isin(list(v))])[0],
                           "mean_bps_per_session": float(r[idx.hour.isin(list(v))].groupby(r[idx.hour.isin(list(v))].index.date).sum().mean())} for k, v in SESSIONS.items()}
    # --- day of week (7 tests), daily returns
    d = df.close.resample("1D").last().pipe(lambda s: np.log(s / s.shift(1))).dropna() * 1e4
    dows = []
    for k, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        x = d[d.index.day_of_week == k]; t, p = _t(x)
        by = [float(np.sign(d[(d.index.day_of_week == k) & (d.index.year == y)].mean())) for y in yrs]
        dows.append({"day": name, "mean_bps": float(x.mean()), "t": t, "p": p, "p_bonf": min(1.0, p * 7), "pct_up": float((x > 0).mean()),
                     "years_same_sign": int(sum(1 for s in by if s == np.sign(x.mean()))), "years": len(yrs)})
    out["dow"] = dows
    # --- weekly: week = Monday 00:00 UTC to next Monday 00:00 UTC
    dn = df.copy(); dn.index = dn.index.tz_localize(None)                 # tz-naive UTC: pandas only honours `origin` on naive indexes
    ORG = pd.Timestamp("2022-01-03")                                       # a Monday 00:00 UTC
    w = dn.resample("7D", origin=ORG, label="left", closed="left").agg({"open": "first", "close": "last"}).dropna()
    wr = np.log(w.close / w.open) * 1e4
    prev = wr.shift(1)
    ac = pd.concat([prev, wr], axis=1).dropna().corr(method="spearman").iloc[0, 1]
    wk_t = _t(wr)
    # does the first day of the week predict the rest of the week?
    first = dn.close.groupby(pd.Grouper(freq="7D", origin=ORG)).apply(lambda s: np.log(s.iloc[23] / s.iloc[0]) if len(s) > 24 else np.nan) * 1e4
    rest_w = dn.close.groupby(pd.Grouper(freq="7D", origin=ORG)).apply(lambda s: np.log(s.iloc[-1] / s.iloc[24]) if len(s) > 25 else np.nan) * 1e4
    mon = pd.concat([first, rest_w], axis=1).dropna().corr(method="spearman").iloc[0, 1]
    out["weekly"] = {"weeks": int(len(wr)), "mean_week_bps": float(wr.mean()), "pct_up_weeks": float((wr > 0).mean()), "t_vs_zero": wk_t[0], "p": wk_t[1],
                     "week_to_next_week_rank_corr": float(ac), "monday_return_to_rest_of_week_rank_corr": float(mon),
                     "pct_up_after_up_week": float((wr[prev > 0] > 0).mean()), "pct_up_after_down_week": float((wr[prev < 0] > 0).mean())}
    # --- volume / volatility seasonality (matters for LP fee income, not for direction)
    vol = df.volume.groupby(df.index.hour).mean(); vv = (r.abs()).groupby(idx.hour).mean()
    out["volume_by_hour_pct_of_avg"] = {int(h): float(v / vol.mean() * 100) for h, v in vol.items()}
    out["abs_move_bps_by_hour"] = {int(h): float(v) for h, v in vv.items()}
    sig = [h for h in hours if h["p_bonf"] < 0.05]
    out["summary"] = {"hours_significant_after_bonferroni": [h["hour"] for h in sig], "days_significant_after_bonferroni": [x["day"] for x in dows if x["p_bonf"] < 0.05]}
    OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps(out, indent=1)); return out

if __name__ == "__main__": run()

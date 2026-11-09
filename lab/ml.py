"""ML signals with strict walk-forward training: a model predicting bar t is fitted only on rows whose label horizon ended before the
cutoff (embargo = horizon). Refit monthly on an expanding window. No future data, no shuffling, costs applied downstream."""
import numpy as np, pandas as pd, warnings
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from . import ta
warnings.filterwarnings("ignore")

def features(eth, btc, fund=None):
    c, F = eth.close, pd.DataFrame(index=eth.index)
    for n in (1, 4, 12, 24, 72, 168): F[f"r{n}"] = ta.logret(c, n)
    F["rsi14"], F["rsi72"] = ta.rsi(c, 14), ta.rsi(c, 72)
    m, s, h = ta.macd(c); F["macd_h"] = h / c
    mid, up, dn = ta.bollinger(c, 72, 2.0); F["bb_z"] = (c - mid) / (up - mid)
    F["atr24"] = ta.atr(eth, 24) / c
    F["rv24"], F["rv168"] = ta.realized_vol(c, 24), ta.realized_vol(c, 168)
    F["vol_z"] = ta.zscore(eth.volume, 168)
    F["dist200"], F["dist1000"] = c / ta.sma(c, 200) - 1, c / ta.sma(c, 1000) - 1
    F["adx"] = ta.adx(eth, 24)
    ratio = (c / btc.close.reindex(eth.index)); F["ethbtc24"], F["ethbtc168"] = ta.logret(ratio, 24), ta.logret(ratio, 168)
    F["btc_r24"] = ta.logret(btc.close.reindex(eth.index), 24)
    hr = eth.index.hour; F["h_sin"], F["h_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    F["dow"] = eth.index.dayofweek
    if fund is not None: F["funding"] = fund["rate"].reindex(eth.index, method="ffill")
    return F.replace([np.inf, -np.inf], np.nan)

MODELS = {
    "logit": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.05, max_iter=300)),
    "hgb": lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=120, learning_rate=0.05, l2_regularization=5.0, min_samples_leaf=200, random_state=7),
    "rf": lambda: RandomForestClassifier(n_estimators=120, max_depth=5, min_samples_leaf=200, n_jobs=2, random_state=7),
}

def walk_forward(F, close, model, horizon, first_pred="2023-01-01", step_days=30):
    """Out-of-sample P(up over `horizon` bars) for every bar from first_pred on."""
    y = (close.shift(-horizon) / close - 1 > 0).astype(float).where(close.shift(-horizon).notna())
    X = F.copy(); ok = X.notna().all(axis=1)
    prob = pd.Series(np.nan, index=close.index)
    cut = pd.Timestamp(first_pred, tz="UTC"); end = close.index[-1]
    while cut <= end:
        nxt = cut + pd.Timedelta(days=step_days)
        tr = (X.index < cut - pd.Timedelta(hours=horizon)) & ok & y.notna()          # embargo: label window must finish before cutoff
        te = (X.index >= cut) & (X.index < nxt) & ok
        if tr.sum() > 5000 and te.sum() > 0:
            mdl = MODELS[model](); mdl.fit(X[tr], y[tr]); prob[te] = mdl.predict_proba(X[te])[:, 1]
        cut = nxt
    return prob

def positions_from_prob(prob, thr, smooth, ls):
    p = prob.rolling(smooth, min_periods=1).mean() if smooth > 1 else prob
    long_ = (p > thr).astype(float)
    if not ls: return long_.where(p.notna(), 0.0)
    short = (p < 1 - thr).astype(float)
    return (long_ - short).where(p.notna(), 0.0)

def ml_configs():
    out = []
    for model in MODELS:
        for H in (24, 72):
            for thr in (0.52, 0.55, 0.58):
                for sm in (1, 12):
                    for ls in (False, True):
                        out.append({"family": "ml", "params": {"model": model, "H": H, "thr": thr, "smooth": sm, "ls": ls, "fs": "v1"}, "lev": 1.0, "perp": ls,
                                    "tag": "ML long/short perp" if ls else "ML long/flat"})
    return out


def features_v2(eth, btc, fund=None):
    """v1 + Fibonacci/swing, weekly-level, and session features. Everything uses information available at bar t only."""
    from . import strategies as S
    F = features(eth, btc, fund); c = eth.close
    ph, pl = S._pivots(eth, 24); n = len(eth); hi, lo = eth.high.to_numpy(), eth.low.to_numpy(); cl = c.to_numpy()
    H = L = np.nan; last = 0; d_fib = np.full(n, np.nan); swing = np.full(n, np.nan); age = np.full(n, np.nan); a_i = 0
    for i in range(n):
        if ph[i]: H, last, a_i = hi[i - 24], 1, i
        if pl[i]: L, last, a_i = lo[i - 24], -1, i
        if not (np.isnan(H) or np.isnan(L)) and H > L:
            lvl = H - 0.618 * (H - L) if last == 1 else L + 0.618 * (H - L)
            d_fib[i] = (cl[i] - lvl) / (H - L); swing[i] = last; age[i] = i - a_i
    F["fib618_dist"], F["swing_dir"], F["bars_since_pivot"] = d_fib, swing, age
    w = S._weekly(eth); wc = w.close
    def to_h(series): 
        s = series.shift(1); s.index = s.index.tz_localize("UTC"); return s.reindex(eth.index, method="ffill")
    F["wk_sma10_dist"] = to_h(wc / wc.rolling(10).mean() - 1); F["wk_prev_ret"] = to_h(wc / w.open - 1)
    F["wk_rsi14"] = to_h(ta.rsi(wc, 14)); wo = w.open.copy(); wo.index = wo.index.tz_localize("UTC"); F["vs_week_open"] = c / wo.reindex(eth.index, method="ffill") - 1
    how = eth.index.dayofweek * 24 + eth.index.hour; F["how_sin"], F["how_cos"] = np.sin(2 * np.pi * how / 168), np.cos(2 * np.pi * how / 168)
    h = eth.index.hour; F["asia"], F["europe"], F["us"] = ((h < 8)).astype(int), ((h >= 8) & (h < 13)).astype(int), ((h >= 13) & (h < 21)).astype(int)
    return F.replace([np.inf, -np.inf], np.nan)

def ml_configs_v2():
    out = []
    for c in ml_configs():
        c = {**c, "params": {**c["params"], "fs": "v2"}, "tag": c["tag"] + " (+fib/weekly/session features)"}
        out.append(c)
    return out

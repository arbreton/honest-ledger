"""Strategy zoo. Each returns a target exposure series decided at bar close (the backtester adds the one-bar delay)."""
import itertools, numpy as np, pandas as pd
from . import ta

def _state(enter, exit_):
    """Long when `enter` fires, flat when `exit_` fires, otherwise keep the previous state."""
    e, x = enter.to_numpy(bool), exit_.to_numpy(bool); out = np.zeros(len(e)); s = 0.0
    for i in range(len(e)):
        if e[i]: s = 1.0
        elif x[i]: s = 0.0
        out[i] = s
    return pd.Series(out, enter.index)

def f_hold(df, **k): return pd.Series(1.0, df.index)
def f_sma_cross(df, fast, slow, ls=False, **k):
    sig = ta.sma(df.close, fast) > ta.sma(df.close, slow); v = sig.astype(float)
    return v * 2 - 1 if ls else v
def f_ema_cross(df, fast, slow, ls=False, **k):
    sig = ta.ema(df.close, fast) > ta.ema(df.close, slow); v = sig.astype(float)
    return v * 2 - 1 if ls else v
def f_price_sma(df, n, ls=False, **k):
    v = (df.close > ta.sma(df.close, n)).astype(float)
    return v * 2 - 1 if ls else v
def f_donchian(df, n, ls=False, **k):
    hi, lo = ta.donchian(df, n); xl = df.close.rolling(max(2, n // 2)).min().shift(1)
    long_ = _state(df.close > hi, df.close < xl)
    if not ls: return long_
    xs = df.close.rolling(max(2, n // 2)).max().shift(1)
    short = _state(df.close < lo, df.close > xs)
    return long_ - short
def f_macd(df, f, s, sig, ls=False, **k):
    _, _, h = ta.macd(df.close, f, s, sig); v = (h > 0).astype(float)
    return v * 2 - 1 if ls else v
def f_mom(df, n, ls=False, **k):
    v = (ta.roc(df.close, n) > 0).astype(float)
    return v * 2 - 1 if ls else v
def f_rsi_rev(df, n, lo, hi, **k): r = ta.rsi(df.close, n); return _state(r < lo, r > hi)
def f_bb_rev(df, n, k_, **k):
    mid, up, dn = ta.bollinger(df.close, n, k_); return _state(df.close < dn, df.close > mid)
def f_bb_break(df, n, k_, **k):
    mid, up, dn = ta.bollinger(df.close, n, k_); return _state(df.close > up, df.close < mid)
def f_trend_vt(df, n, tv, **k):
    rv = ta.realized_vol(df.close, 168); scale = (tv / rv).clip(upper=1.0).fillna(0.0)
    return (df.close > ta.sma(df.close, n)).astype(float) * scale
def f_vol_managed(df, tv, **k):
    rv = ta.realized_vol(df.close, 168); return (tv / rv).clip(upper=1.0).fillna(0.0)
def f_dip_buy(df, n, drop, hold, **k):
    dd = df.close / df.close.rolling(n).max() - 1; trig = (dd <= -drop).to_numpy(); out = np.zeros(len(df)); left = 0
    for i in range(len(df)):
        if trig[i] and left == 0: left = hold
        out[i] = 1.0 if left > 0 else 0.0; left = max(0, left - 1)
    return pd.Series(out, df.index)

# ---------- Fibonacci retracements (causal swing pivots: a pivot at t-k is only used from bar t on) ----------
def _pivots(df, k):
    ph = (df.high.shift(k) == df.high.rolling(2 * k + 1).max()).fillna(False)
    pl = (df.low.shift(k) == df.low.rolling(2 * k + 1).min()).fillna(False)
    return ph.to_numpy(bool), pl.to_numpy(bool)

def f_fib(df, k, f, ls=False, min_move=0.03, **kw):
    """After an up-swing (pivot low then pivot high) buy the retracement to H - f*(H-L); take profit at H, stop below L.
    With ls: after a down-swing, short the bounce to L + f*(H-L); take profit at L, stop above H."""
    ph, pl = _pivots(df, k); hi, lo, c = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    n = len(df); out = np.zeros(n); H = L = None; last = None; st = 0
    for i in range(n):
        if ph[i] and i - k >= 0: H, last = hi[i - k], "H"
        if pl[i] and i - k >= 0: L, last = lo[i - k], "L"
        if H is not None and L is not None and H > L and (H - L) / L >= min_move:
            if last == "H":                                            # L then H: up-swing
                lvl = H - f * (H - L)
                if st == 0 and L < c[i] <= lvl: st = 1
                elif st == 1 and (c[i] >= H or c[i] < L): st = 0
            elif ls and last == "L":                                   # H then L: down-swing
                lvl = L + f * (H - L)
                if st == 0 and lvl <= c[i] < H: st = -1
                elif st == -1 and (c[i] <= L or c[i] > H): st = 0
        if st == 1 and (H is None or c[i] < (L or 0) or c[i] >= (H or 1e18)): st = 0
        out[i] = st
    return pd.Series(out, df.index)

# ---------- Weekly bars (Monday 00:00 UTC); only COMPLETED weeks are used ----------
def _weekly(df):
    dn = df.copy(); dn.index = dn.index.tz_localize(None)
    return dn.resample("7D", origin=pd.Timestamp("2022-01-03"), label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

def _wk_to_hourly(df, series):
    """A signal computed from week w's close is usable from the start of week w+1."""
    s = series.shift(1); s.index = s.index.tz_localize("UTC")
    return s.reindex(df.index, method="ffill").fillna(0.0)

def f_weekly_sma(df, n, ls=False, **k):
    w = _weekly(df); v = (w.close > w.close.rolling(n).mean()).astype(float)
    return _wk_to_hourly(df, v * 2 - 1 if ls else v)
def f_weekly_break(df, n, **k):
    w = _weekly(df); hh = w.high.rolling(n).max().shift(1); ll = w.low.rolling(max(2, n // 2)).min().shift(1)
    return _wk_to_hourly(df, _state(w.close > hh, w.close < ll))
def f_week_open_bias(df, ls=False, **k):
    w = _weekly(df); wo = w.open.copy(); wo.index = wo.index.tz_localize("UTC")
    wo = wo.reindex(df.index, method="ffill"); v = (df.close > wo).astype(float)
    return v * 2 - 1 if ls else v
def f_prev_week(df, mode, ls=False, **k):
    w = _weekly(df); r = w.close / w.open - 1
    v = (r > 0).astype(float) if mode == "mom" else (r < 0).astype(float)
    return _wk_to_hourly(df, v * 2 - 1 if ls else v)

# ---------- Session / calendar hypotheses (position is set one bar ahead so it is HELD during the window) ----------
def f_session(df, start, length, direction, **k):
    nh = (df.index.hour + 1) % 24                                      # hour of the bar we will be holding through
    inwin = ((nh - start) % 24) < length
    return pd.Series(np.where(inwin, float(direction), 0.0), df.index)
def f_weekday(df, days, direction, **k):
    nxt = df.index + pd.Timedelta(hours=1)
    return pd.Series(np.where(np.isin(nxt.day_of_week, days), float(direction), 0.0), df.index)

# ---------- Runner: stay mostly long; when the weekly/monthly trend is RED keep only a small runner instead of going flat ----------
def _monthly(df):
    dn = df.copy(); dn.index = dn.index.tz_localize(None)
    return dn.resample("MS", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

def _red_hourly(df, mode):
    """1.0 while the chosen higher-timeframe trend is red, using only COMPLETED weekly/monthly candles."""
    def wk(kind):
        w = _weekly(df); red = (w.close < w.open) if kind == "candle" else (w.close < w.close.rolling(int(kind)).mean())
        return _wk_to_hourly(df, red.astype(float))
    def mo(kind):
        m = _monthly(df); red = (m.close < m.open) if kind == "candle" else (m.close < m.close.rolling(int(kind)).mean())
        sr = red.astype(float).shift(1); sr.index = sr.index.tz_localize("UTC"); return sr.reindex(df.index, method="ffill").fillna(0.0)
    if mode == "w_candle": return wk("candle")
    if mode.startswith("w_sma"): return wk(mode[5:])
    if mode == "m_candle": return mo("candle")
    if mode.startswith("m_sma"): return mo(mode[5:])
    a, b = wk("20"), mo("6")
    return (a + b) / 2 if mode == "either" else ((a + b) == 2).astype(float) * 1.0   # 'either': half-red counts half; 'both': only when both are red

def f_runner(df, mode, r, **k):
    red = _red_hourly(df, mode)
    return 1.0 - (1.0 - r) * red

# ---------- Cycle runner: deep drawdown = full position; euphoria (Mayer multiple high) or a bear below the 200d average = runner ----------
_DAILY = {}
def f_cycle(df, acc_dd, trim, r, **k):
    from . import data as _d
    if "d" not in _DAILY: _DAILY["d"] = _d.daily_long("ETHUSDT")
    c = _DAILY["d"].close; ath = c.cummax().shift(1); dd = c / ath - 1; mayer = c / c.rolling(200).mean()
    exp = pd.Series(np.where(dd <= acc_dd, 1.0, np.where(mayer >= trim, r, np.where(mayer >= 1.0, 1.0, r))), c.index)
    exp = exp.where(mayer.notna(), 1.0).shift(1)                         # decided on yesterday's close, used from today
    return exp.reindex(df.index, method="ffill").fillna(1.0)

FAMILIES = {"runner": f_runner, "cycle": f_cycle, "fib": f_fib, "weekly_sma": f_weekly_sma, "weekly_break": f_weekly_break, "week_open_bias": f_week_open_bias, "prev_week": f_prev_week,
            "session": f_session, "weekday": f_weekday, "hold": f_hold, "sma_cross": f_sma_cross, "ema_cross": f_ema_cross, "price_sma": f_price_sma, "donchian": f_donchian, "macd": f_macd,
            "mom": f_mom, "rsi_rev": f_rsi_rev, "bb_rev": f_bb_rev, "bb_break": f_bb_break, "trend_vt": f_trend_vt, "vol_managed": f_vol_managed, "dip_buy": f_dip_buy}

def _g(**kw):
    keys = list(kw); return [dict(zip(keys, v)) for v in itertools.product(*kw.values())]

def rule_configs():
    C = []
    add = lambda fam, params, **x: C.append({"family": fam, "params": params, "lev": 1.0, "perp": False, **x})
    add("hold", {})
    for p in _g(fast=[12, 24, 48, 72, 120, 168], slow=[168, 336, 504, 720, 1000, 1440, 2000]):
        if p["fast"] < p["slow"]: add("sma_cross", p); add("ema_cross", p)
    for n in (48, 100, 200, 336, 500, 720, 1000, 1440, 2000): add("price_sma", {"n": n})
    for n in (48, 100, 168, 336, 500, 720): add("donchian", {"n": n})
    for f, s, g in ((12, 26, 9), (24, 52, 18), (48, 104, 36), (72, 156, 54)): add("macd", {"f": f, "s": s, "sig": g})
    for n in (24, 72, 168, 336, 720, 1440): add("mom", {"n": n})
    for p in _g(n=[14, 48, 72], lo=[25, 30, 35], hi=[55, 65, 75]): add("rsi_rev", p)
    for p in _g(n=[24, 72, 168], k_=[1.5, 2.0, 2.5]): add("bb_rev", p)
    for p in _g(n=[24, 72, 168, 336], k_=[1.5, 2.0, 2.5]): add("bb_break", p)
    for p in _g(n=[200, 500, 1000], tv=[0.3, 0.5, 0.8]): add("trend_vt", p)
    for tv in (0.3, 0.5, 0.8, 1.0): add("vol_managed", {"tv": tv})
    for p in _g(n=[24, 72], drop=[0.05, 0.08, 0.12], hold=[24, 72, 168]): add("dip_buy", p)
    # long/short on a perp (funding paid, 1x)
    base = [c for c in C if c["family"] in ("sma_cross", "price_sma", "donchian", "mom", "macd") and (c["family"] != "sma_cross" or c["params"]["slow"] >= 504)]
    LS = [{**c, "params": {**c["params"], "ls": True}, "perp": True, "tag": "long/short perp"} for c in base]
    # leveraged variants of the trend families (2x, 3x, 5x), long-only and long/short: the "risky" end of the spectrum
    LEV = []
    for c in [c for c in LS + [c for c in base if c["family"] in ("price_sma", "donchian", "sma_cross")]]:
        for lv in (2.0, 3.0, 5.0):
            LEV.append({**c, "lev": lv, "perp": True, "tag": f"{lv:g}x leveraged" + (" long/short" if c["params"].get("ls") else " long")})
    # --- added 2026-11-09 after the operator asked: Fibonacci, weekly-level trends, and session/calendar hypotheses ---
    X = []
    xadd = lambda fam, params, **x: X.append({"family": fam, "params": params, "lev": 1.0, "perp": False, **x})
    for p in _g(k=[12, 24, 48, 96], f=[0.382, 0.5, 0.618]):
        xadd("fib", p, tag="fibonacci long-only"); xadd("fib", {**p, "ls": True}, perp=True, tag="fibonacci long/short perp")
    for n in (4, 8, 10, 20, 40):
        xadd("weekly_sma", {"n": n}, tag="weekly trend"); xadd("weekly_sma", {"n": n, "ls": True}, perp=True, tag="weekly trend long/short perp")
    for n in (2, 4, 8, 13): xadd("weekly_break", {"n": n}, tag="weekly trend")
    xadd("week_open_bias", {}, tag="weekly trend"); xadd("week_open_bias", {"ls": True}, perp=True, tag="weekly trend long/short perp")
    for m in ("mom", "rev"):
        xadd("prev_week", {"mode": m}, tag="weekly trend"); xadd("prev_week", {"mode": m, "ls": True}, perp=True, tag="weekly trend long/short perp")
    for st, ln in ((0, 2), (0, 8), (8, 5), (13, 3), (13, 8), (21, 3)):                     # Asia open, Asia, Europe, US open, US, pre-Asia
        xadd("session", {"start": st, "length": ln, "direction": 1}, tag="session long")
        xadd("session", {"start": st, "length": ln, "direction": -1}, perp=True, tag="session short perp")
    xadd("weekday", {"days": [0, 1, 2, 3, 4], "direction": 1}, tag="calendar long"); xadd("weekday", {"days": [5, 6], "direction": 1}, tag="calendar long")
    xadd("weekday", {"days": [0], "direction": 1}, tag="calendar long"); xadd("weekday", {"days": [3], "direction": -1}, perp=True, tag="calendar short perp")
    # --- added after the operator's runner / top-bottom-cycle ideas ---
    for mode in ("w_candle", "w_sma10", "w_sma20", "m_candle", "m_sma3", "m_sma6", "m_sma10", "either", "both"):
        for r in (0.0, 0.1, 0.25, 0.5): xadd("runner", {"mode": mode, "r": r}, tag="runner (keep r when weekly/monthly trend is red)")
    for p in _g(acc_dd=[-0.5, -0.6], trim=[1.8, 2.2], r=[0.25, 0.5]): xadd("cycle", p, tag="cycle runner (drawdown + Mayer)")
    return C + LS + LEV + X

def name(c):
    p = ",".join(f"{k}={v}" for k, v in c["params"].items() if k != "ls")
    tag = ("LS " if c["params"].get("ls") else "") + (f"{c['lev']:g}x " if c["lev"] > 1 else "")
    return f"{tag}{c['family']}({p})"

def position(df, c): return FAMILIES[c["family"]](df, **c["params"]).astype(float)

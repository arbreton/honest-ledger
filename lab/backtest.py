"""Honest vectorised backtester. Signal at close of bar t-1 -> position held through bar t (one-bar delay, no lookahead).
Costs on every unit of turnover; perp funding paid by the position; leveraged accounts are LIQUIDATED using intrabar lows/highs."""
import numpy as np, pandas as pd

PPY = 8760
SPOT_COST_BPS = 10.0      # per side: DEX/CEX fee + slippage for a ~$50 trade on Base/Binance (conservative)
PERP_COST_BPS = 6.0       # per side taker + slippage; funding is charged separately
MAINT = 0.05              # maintenance margin as a fraction of notional

def _run_perp(df, pos, lev, fund, cost):
    """Perp ACCOUNT model: on every position change the notional is reset to lev x equity x pos and then stays FIXED (no auto-rebalance,
    no margin top-up) until the signal changes. Funding is paid every bar. Liquidated if intrabar equity < MAINT x notional -> ruin (equity 0 forever)."""
    close, low, high = df["close"].to_numpy(), df["low"].to_numpy(), df["high"].to_numpy()
    held = pos.reindex(df.index).fillna(0.0).clip(-1, 1).shift(1).fillna(0.0).to_numpy()
    fr = (fund["rate"].reindex(df.index, method="ffill").fillna(0.0).to_numpy() / 8.0) if fund is not None else np.zeros(len(df))
    n = len(df); eq = np.ones(n); E = 1.0; units = 0.0; cur = 0.0; liq = 0; turn_sum = 0.0
    for i in range(1, n):
        if E <= 0: eq[i] = 0.0; continue
        h = held[i]
        if abs(h - cur) > 1e-9:                                   # re-size at the previous close
            new_units = lev * E * h / close[i - 1]
            traded = abs(new_units - units) * close[i - 1]
            E -= traded * cost; turn_sum += traded / max(E, 1e-9) / lev
            units, cur = new_units, h
            if E <= 0: eq[i] = 0.0; E = 0.0; continue
        if units != 0.0:
            worst = low[i] if units > 0 else high[i]
            e_low = E + units * (worst - close[i - 1])
            if e_low <= MAINT * abs(units) * worst:               # liquidated intrabar
                E = 0.0; liq = 1; eq[i] = 0.0; continue
            E += units * (close[i] - close[i - 1]) - units * close[i - 1] * fr[i]
        eq[i] = max(E, 0.0)
    expo = float(np.mean(np.abs(held)))
    return pd.Series(eq, df.index), {"liquidated": liq, "turnover_per_year": float(turn_sum / (n / PPY)), "exposure": expo}

def run(df, pos, lev=1.0, perp=False, fund=None, cost_bps=None):
    """pos: target exposure in [-1,1] decided at each bar's close. Returns (equity Series, info dict)."""
    if perp or lev > 1.0:
        return _run_perp(df, pos, lev, fund, (cost_bps if cost_bps is not None else PERP_COST_BPS) / 1e4)
    cost = (cost_bps if cost_bps is not None else (PERP_COST_BPS if perp else SPOT_COST_BPS)) / 1e4
    p = pos.reindex(df.index).fillna(0.0).clip(-1, 1)
    held = p.shift(1).fillna(0.0)                                   # position actually carried through bar t
    ret = df["close"].pct_change().fillna(0.0)
    turn = held.diff().abs().fillna(held.abs())
    r = lev * held * ret - lev * turn * cost
    if perp and fund is not None:
        fr = fund["rate"].reindex(df.index, method="ffill").fillna(0.0) / 8.0   # 8h rate spread over hourly bars (approx.)
        r = r - lev * held * fr
    liq = 0
    if lev > 1.0:
        worst = np.where(held > 0, df["low"] / df["close"].shift(1) - 1, np.where(held < 0, -(df["high"] / df["close"].shift(1) - 1), 0.0))
        dead = (lev * worst <= -(1.0 - MAINT)).to_numpy() if hasattr(worst, "to_numpy") else (lev * worst <= -(1.0 - MAINT))
        rv = r.to_numpy().copy(); eq_alive = True; liq_idx = None
        for i in np.flatnonzero(dead):
            liq_idx = i; break
        # walk: after first liquidation the account is empty (a fresh account would be a new decision, not part of this strategy)
        if liq_idx is not None:
            rv[liq_idx] = -1.0; rv[liq_idx + 1:] = 0.0; liq = 1
        r = pd.Series(rv, index=r.index)
    r = r.clip(lower=-1.0)
    eq = (1 + r).cumprod()
    return eq, {"liquidated": liq, "turnover_per_year": float(turn.sum() / (len(df) / PPY)), "exposure": float(held.abs().mean())}

def metrics(eq, ppy=PPY, bh=None):
    """Daily-return based statistics (hourly returns are too autocorrelated for honest Sharpe)."""
    d = eq.resample("1D").last().dropna()
    r = d.pct_change().dropna()
    if len(r) < 20 or d.iloc[0] <= 0: return {"n": len(r), "ok": False}
    yrs = (d.index[-1] - d.index[0]).days / 365.25
    total = d.iloc[-1] / d.iloc[0]
    sd = r.std()
    dn = r[r < 0].std()
    mdd = (d / d.cummax() - 1).min()
    cagr = total ** (1 / yrs) - 1 if total > 0 and yrs > 0.05 else (-1.0 if total <= 0 else total - 1)
    out = {"ok": True, "n": int(len(r)), "years": round(yrs, 2), "total": float(total), "cagr": float(cagr), "vol": float(sd * np.sqrt(365)),
           "sharpe": float(r.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0, "sortino": float(r.mean() / dn * np.sqrt(365)) if dn and dn > 0 else 0.0,
           "maxdd": float(mdd), "calmar": float(cagr / abs(mdd)) if mdd < 0 else 0.0}
    return out

def window(eq, start, end=None):
    """Re-base an equity curve to 1.0 at the start of a window."""
    s = eq.loc[start:end] if end else eq.loc[start:]
    return s / s.iloc[0] if len(s) else s

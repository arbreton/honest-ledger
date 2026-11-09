"""Technical-analysis library (vectorised pandas/numpy). Every function uses only data up to and including bar t."""
import numpy as np, pandas as pd

def sma(s, n): return s.rolling(n, min_periods=n).mean()
def ema(s, n): return s.ewm(span=n, adjust=False, min_periods=n).mean()
def roc(s, n): return s / s.shift(n) - 1
def logret(s, n=1): return np.log(s / s.shift(n))
def rsi(s, n=14):
    d = s.diff(); up, dn = d.clip(lower=0), (-d).clip(lower=0)
    rs = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + rs)
def macd(s, f=12, sl=26, sig=9):
    m = ema(s, f) - ema(s, sl); sg = ema(m, sig); return m, sg, m - sg
def bollinger(s, n=20, k=2.0):
    mid, sd = sma(s, n), s.rolling(n, min_periods=n).std()
    return mid, mid + k * sd, mid - k * sd
def true_range(df):
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
def atr(df, n=14): return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
def donchian(df, n): return df["high"].rolling(n, min_periods=n).max().shift(1), df["low"].rolling(n, min_periods=n).min().shift(1)
def stoch(df, n=14):
    lo, hi = df["low"].rolling(n).min(), df["high"].rolling(n).max()
    return 100 * (df["close"] - lo) / (hi - lo)
def adx(df, n=14):
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0); minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(plus, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=1 / n, adjust=False).mean()
def realized_vol(s, n=24, ppy=8760): return logret(s).rolling(n, min_periods=n).std() * np.sqrt(ppy)
def zscore(s, n): return (s - sma(s, n)) / s.rolling(n, min_periods=n).std()
def obv(df): return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()

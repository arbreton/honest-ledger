"""Anti-self-deception statistics: probabilistic/deflated Sharpe, stationary-bootstrap reality check, daily-return helpers."""
import numpy as np, pandas as pd
from scipy import stats as st

EG = 0.5772156649

def daily(eq): return eq.resample("1D").last().dropna().pct_change().dropna()

def sharpe_d(r): return float(r.mean() / r.std()) if len(r) > 2 and r.std() > 0 else 0.0    # per-day (not annualised)

def psr(r, sr_ref=0.0):
    """Probabilistic Sharpe Ratio: P(true Sharpe > sr_ref) given skew/kurtosis and sample length."""
    T, sr = len(r), sharpe_d(r)
    if T < 30: return 0.0
    g3, g4 = float(st.skew(r)), float(st.kurtosis(r, fisher=False))
    den = np.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(st.norm.cdf((sr - sr_ref) * np.sqrt(T - 1) / den))

def dsr(r, n_trials, sr_var):
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado): PSR against the Sharpe you'd expect from the BEST of n_trials pure-noise strategies."""
    if n_trials <= 1: return psr(r)
    sr0 = np.sqrt(max(sr_var, 1e-12)) * ((1 - EG) * st.norm.ppf(1 - 1 / n_trials) + EG * st.norm.ppf(1 - 1 / (n_trials * np.e)))
    return psr(r, sr0)

def reality_check(excess, n_boot=2000, block=10, seed=7):
    """White's Reality Check via stationary bootstrap. excess: DataFrame (days x strategies) of daily excess return vs benchmark.
    Returns p-value for H0: no strategy has positive expected excess return (accounts for picking the best of many)."""
    X = excess.dropna().to_numpy(); T, K = X.shape
    if T < 60 or K == 0: return 1.0
    mu = X.mean(axis=0); stat = np.sqrt(T) * mu.max()
    rng = np.random.default_rng(seed); Xc = X - mu; cnt = 0
    for _ in range(n_boot):
        idx = np.empty(T, dtype=int); i = 0
        while i < T:
            start = rng.integers(0, T); L = min(T - i, rng.geometric(1 / block))
            idx[i:i + L] = (start + np.arange(L)) % T; i += L
        cnt += np.sqrt(T) * Xc[idx].mean(axis=0).max() >= stat
    return float((cnt + 1) / (n_boot + 1))

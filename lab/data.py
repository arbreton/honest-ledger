"""Public market data (no keys). Incremental CSV cache. Plain User-Agent; falls back across public mirrors."""
import json, pathlib, time, urllib.request
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parent / "data"
UA = {"User-Agent": "farmv2-lab/0.1"}
SPOT_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com", "https://api.binance.us"]
IV_MS = {"1h": 3_600_000, "1d": 86_400_000}
START_MS = int(pd.Timestamp("2022-01-01", tz="UTC").timestamp() * 1000)

def _get(url, tries=3):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
        except Exception:
            time.sleep(1 + i)
    raise RuntimeError("fetch failed: " + url[:90])

def klines(symbol="ETHUSDT", interval="1h"):
    path = DATA / f"{symbol}_{interval}.csv"
    DATA.mkdir(exist_ok=True)
    df = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else None
    start = int(df.index[-1].timestamp() * 1000) + IV_MS[interval] if df is not None and len(df) else START_MS
    rows, now_ms = [], int(time.time() * 1000)
    while start < now_ms - IV_MS[interval]:
        batch = None
        for host in SPOT_HOSTS:
            try:
                batch = _get(f"{host}/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start}&limit=1000"); break
            except Exception:
                continue
        if not batch: break
        rows += batch
        start = batch[-1][0] + IV_MS[interval]
        if len(batch) < 1000: break
    if rows:
        new = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "ct", "qv", "n", "tbv", "tqv", "ig"])
        new.index = pd.to_datetime(new["t"], unit="ms", utc=True)
        new = new[["open", "high", "low", "close", "volume", "n"]].astype(float)
        df = new if df is None else pd.concat([df, new])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_csv(path)
    # drop the still-forming last bar
    return df.iloc[:-1] if df is not None and df.index[-1] + pd.Timedelta(milliseconds=IV_MS[interval]) > pd.Timestamp.now(tz="UTC") else df

def funding(symbol="ETHUSDT"):
    path = DATA / f"{symbol}_funding.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else None
    start = int(df.index[-1].timestamp() * 1000) + 1 if df is not None and len(df) else START_MS
    rows = []
    while True:
        try: batch = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&startTime={start}&limit=1000")
        except Exception: break
        if not batch: break
        rows += batch; start = batch[-1]["fundingTime"] + 1
        if len(batch) < 1000: break
    if rows:
        new = pd.DataFrame(rows); new.index = pd.to_datetime(new["fundingTime"], unit="ms", utc=True)
        new = new[["fundingRate"]].astype(float).rename(columns={"fundingRate": "rate"})
        df = new if df is None else pd.concat([df, new])
        df = df[~df.index.duplicated(keep="last")].sort_index(); df.to_csv(path)
    return df

def load(symbol="ETHUSDT", interval="1h"):
    df = klines(symbol, interval)
    if df is None or df.empty: raise RuntimeError("no data")
    return df


def daily_long(symbol="ETHUSDT"):
    """Daily candles from the exchange's first listing (Aug 2017): enough history for several full cycles."""
    path = DATA / f"{symbol}_1d_long.csv"
    df = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else None
    start = int(df.index[-1].timestamp() * 1000) + IV_MS["1d"] if df is not None and len(df) else int(pd.Timestamp("2017-08-17", tz="UTC").timestamp() * 1000)
    rows, now_ms = [], int(time.time() * 1000)
    while start < now_ms - IV_MS["1d"]:
        batch = None
        for host in SPOT_HOSTS:
            try: batch = _get(f"{host}/api/v3/klines?symbol={symbol}&interval=1d&startTime={start}&limit=1000"); break
            except Exception: continue
        if not batch: break
        rows += batch; start = batch[-1][0] + IV_MS["1d"]
        if len(batch) < 1000: break
    if rows:
        new = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "ct", "qv", "n", "tbv", "tqv", "ig"])
        new.index = pd.to_datetime(new["t"], unit="ms", utc=True); new = new[["open", "high", "low", "close", "volume", "n"]].astype(float)
        df = new if df is None else pd.concat([df, new]); df = df[~df.index.duplicated(keep="last")].sort_index(); df.to_csv(path)
    return df.iloc[:-1] if df.index[-1] + pd.Timedelta(days=1) > pd.Timestamp.now(tz="UTC") else df

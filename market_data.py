"""行情数据：Yahoo 为主，失败时依次改用纳斯达克官网接口、新浪财经，最后用本地缓存的上一次成功数据。"""
import time

import pandas as pd
import requests

import invest

CACHE = invest.CACHE / "closes_cache.csv"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
SINA = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}


def _yahoo(tickers, period):
    try:
        d = invest.yf.download(tickers, period=period, auto_adjust=True, progress=False)["Close"]
    except Exception:
        return pd.DataFrame()
    if isinstance(d, pd.Series):
        d = d.to_frame(tickers[0])
    return d[[t for t in d if d[t].notna().any()]]


def _nasdaq(ticker, days):
    """纳斯达克官网的日线（未按分红调整，作备用足够）。指数类代码（^VIX 等）不支持。"""
    if ticker.startswith("^"):
        return None
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    for cls in ("etf", "stocks"):
        try:
            j = requests.get(f"https://api.nasdaq.com/api/quote/{ticker}/historical",
                             params={"assetclass": cls, "fromdate": start, "limit": 9999},
                             headers=UA, timeout=20).json()
            rows = ((j.get("data") or {}).get("tradesTable") or {}).get("rows") or []
        except Exception:
            rows = []
        if rows:
            s = pd.Series({pd.Timestamp(r["date"]): float(r["close"].replace("$", "").replace(",", "")) for r in rows})
            return s.sort_index().rename(ticker)
    return None


def closes(tickers, period="2y"):
    """返回 (日收盘价 DataFrame, 是否用了旧缓存)。"""
    tickers = sorted(set(tickers))
    days = {"2y": 730, "1y": 365, "6mo": 183}.get(period, 730)
    got = pd.DataFrame()
    for attempt in range(3):
        missing = [t for t in tickers if t not in got]
        if not missing:
            break
        d = _yahoo(missing, period)
        if len(d.columns):
            got = pd.concat([got, d], axis=1)
        if [t for t in tickers if t not in got]:
            time.sleep(3 * (attempt + 1))
    for t in [t for t in tickers if t not in got]:
        s = _nasdaq(t, days)
        if s is not None:
            got = pd.concat([got, s], axis=1)
    got = got.sort_index()
    stale = False
    missing = [t for t in tickers if t not in got]
    if missing and CACHE.exists():
        old = pd.read_csv(CACHE, index_col=0, parse_dates=True)
        for t in missing:
            if t in old:
                got = pd.concat([got, old[t]], axis=1)
                stale = True
    if len(got.columns) and not stale:
        old = pd.read_csv(CACHE, index_col=0, parse_dates=True) if CACHE.exists() else pd.DataFrame()
        merged = got.combine_first(old) if len(old) else got
        merged.sort_index().to_csv(CACHE)
    return got.sort_index().ffill(), stale


def sina_quotes(tickers):
    """新浪财经美股实时价（含盘前盘后）：{代码: 价格}。"""
    try:
        txt = requests.get("https://hq.sinajs.cn/list=" + ",".join("gb_" + t.lower() for t in tickers),
                           headers=SINA, timeout=10).content.decode("gbk", "ignore")
    except Exception:
        return {}
    out = {}
    for line in txt.splitlines():
        if "=\"" in line and line.split("=\"")[1].strip("\";"):
            sym = line.split("hq_str_gb_")[1].split("=")[0].upper()
            out[sym] = float(line.split("=\"")[1].split(",")[1])
    return out


def fx():
    """(美元兑港币, 美元兑人民币)。Yahoo 失败时用新浪。"""
    try:
        d = invest.yf.download(["HKD=X", "CNY=X"], period="7d", progress=False)["Close"].ffill().iloc[-1]
        if pd.notna(d.get("HKD=X")) and pd.notna(d.get("CNY=X")):
            return float(d["HKD=X"]), float(d["CNY=X"])
    except Exception:
        pass
    txt = requests.get("https://hq.sinajs.cn/list=fx_susdhkd,fx_susdcny", headers=SINA, timeout=10).content.decode("gbk", "ignore")
    vals = [float(line.split("=\"")[1].split(",")[1]) for line in txt.splitlines() if "=\"" in line]
    return vals[0], vals[1]

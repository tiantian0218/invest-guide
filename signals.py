"""盯盘指标与规则信号。规则全部公开、可回测，不做“预测”。"""
import logging

import numpy as np
import pandas as pd
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def indicators(close):
    """close: 日收盘价序列（至少 1 年）。返回最新一天的指标。"""
    last = close.iloc[-1]
    hi52 = close.iloc[-252:].max()
    ma200 = close.rolling(200).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    return {
        "price": last,
        "chg_1d": close.iloc[-1] / close.iloc[-2] - 1,
        "chg_1m": close.iloc[-1] / close.iloc[-22] - 1,
        "chg_ytd": last / close[close.index.year == close.index[-1].year].iloc[0] - 1,
        "from_high": last / hi52 - 1,
        "ma50": ma50,
        "ma200": ma200,
        "vs_ma200": last / ma200 - 1,
        "rsi": rsi(close).iloc[-1],
    }


def long_term_advice(ind, vix, has_cash):
    """给“长期持有指数”的人的规则化建议：(级别, 标题, 理由列表)。"""
    reasons = []
    dd, rs, above = ind["from_high"], ind["rsi"], ind["vs_ma200"] > 0
    if dd <= -0.30:
        level, title = "buy+", "大跌区：按计划定投，并可动用备用现金加仓"
        reasons.append(f"距一年高点已跌 {dd*100:.0f}%。1999 年以来在这种位置买入，持有 3 年约 2/3 的情况赚钱，"
                       "反而低于随便哪天买入的 84%：大跌之后可能还会继续跌（如 2000–2002）")
    elif dd <= -0.20:
        level, title = "buy+", "回调区：按计划定投，可小幅加仓"
        reasons.append(f"距一年高点跌了 {dd*100:.0f}%，进入技术性熊市区间")
    elif dd <= -0.10:
        level, title = "buy", "正常回调：按计划定投"
        reasons.append(f"距一年高点跌了 {dd*100:.0f}%，这种幅度的回调几乎每年都有")
    else:
        level, title = "hold", "接近高位：按计划定投，不追加、不卖出"
        reasons.append(f"距一年高点仅 {dd*100:.1f}%，处在历史最高价附近")
    if rs > 75:
        reasons.append(f"RSI {rs:.0f}，短期涨得偏快，追加资金可以分几次买入")
    elif rs < 30:
        reasons.append(f"RSI {rs:.0f}，短期跌得偏急，市场情绪恐慌")
    reasons.append(("价格在 200 日均线之上，长期趋势向上" if above else "价格跌破 200 日均线，长期趋势转弱，波动通常会变大")
                   + f"（偏离 {ind['vs_ma200']*100:+.1f}%）")
    if vix is not None:
        if vix >= 30:
            reasons.append(f"VIX {vix:.0f}，市场恐慌。历史上恐慌时期买入的长期回报偏高，但过程很煎熬")
        elif vix <= 14:
            reasons.append(f"VIX {vix:.0f}，市场很平静，往往也是大家最放松警惕的时候")
        else:
            reasons.append(f"VIX {vix:.0f}，市场情绪正常")
    if level == "buy+" and not has_cash:
        reasons.append("你账户里没有备用现金：不要为了加仓让总资产贴近 1 万港币门槛")
    return level, title, reasons


def sell_checklist(ind, weight, target_w, trb_hkd, trb_min, is_index):
    """卖出检查：只在满足明确条件时提示卖出。返回 [(是否触发, 说明)]。"""
    out = [
        (trb_hkd < trb_min * 1.05, "总资产贴近或低于 1 万港币门槛（建议补现金，而不是卖股票）"),
        (abs(weight - target_w) > 0.10, f"持仓比例偏离目标 {abs(weight-target_w)*100:.0f} 个百分点 → 卖出多的一侧或用新资金补少的一侧"),
    ]
    if not is_index:
        out.append((weight > 0.25, f"单只个股占比 {weight*100:.0f}% 超过 25% → 风险过度集中，考虑减仓"))
        out.append((ind["from_high"] < -0.35 and ind["vs_ma200"] < -0.15,
                    "个股较高点跌超 35% 且远低于 200 日均线 → 重新检查买入理由，不成立就止损"))
    return out


def ma_timing_backtest(close, window=200):
    """收盘价站上 N 日均线就持有、跌破就空仓（次日执行），与一直持有对比。"""
    ma = close.rolling(window).mean()
    pos = (close > ma).shift(1).fillna(False).astype(float)
    r = close.pct_change().fillna(0)
    start = ma.first_valid_index()
    r, pos = r[start:], pos[start:]
    hold = (1 + r).cumprod()
    timing = (1 + r * pos).cumprod()
    trades = int(pos.diff().abs().sum())
    yrs = len(r) / 252

    def stats(s):
        return s.iloc[-1] ** (1 / yrs) - 1, (s / s.cummax() - 1).min()

    return hold, timing, trades, stats(hold), stats(timing)


def analyst(ticker):
    """个股分析师一致预期；ETF 一般没有。"""
    t = yf.Ticker(ticker)
    out = {}
    try:
        out["targets"] = t.analyst_price_targets or None
    except Exception:
        out["targets"] = None
    try:
        rec = t.recommendations_summary
        out["rec"] = rec.iloc[0].to_dict() if rec is not None and len(rec) else None
    except Exception:
        out["rec"] = None
    return out


def market_temperature(close, vix_hist=None, lookback_years=10):
    """0–100 度的“价格温度”：今天的位置在过去 10 年里排第几（越高越热）。
    由距高点、偏离 200 日线、RSI、VIX（反向）四项的历史百分位平均得到。只描述冷热，不改变定投计划。"""
    c = close.iloc[-(lookback_years * 252 + 252):]
    parts = {
        "距一年高点": c / c.rolling(252, min_periods=60).max() - 1,
        "偏离200日线": c / c.rolling(200).mean() - 1,
        "RSI": rsi(c),
    }
    if vix_hist is not None and len(vix_hist) > 252:
        parts["VIX(反向)"] = -vix_hist.reindex(c.index).ffill()
    scores = {k: float((s.dropna() <= s.dropna().iloc[-1]).mean() * 100) for k, s in parts.items() if s.dropna().size}
    t = sum(scores.values()) / len(scores)
    label = ("冰冷", "偏冷", "正常", "偏热", "过热")[min(int(t // 20), 4)]
    return round(t), label, scores


def market_gauges():
    df = yf.download(["^VIX", "^TNX"], period="10d", progress=False)["Close"].ffill()
    last = df.iloc[-1]
    return (float(last["^VIX"]) if pd.notna(last.get("^VIX")) else None,
            float(last["^TNX"]) if pd.notna(last.get("^TNX")) else None)


def us_market_status(now=None):
    now = (now or pd.Timestamp.now(tz="America/New_York")).tz_convert("America/New_York")
    open_, close_ = now.normalize() + pd.Timedelta(hours=9.5), now.normalize() + pd.Timedelta(hours=16)
    bj = lambda t: t.tz_convert("Asia/Shanghai").strftime("%H:%M")
    if now.weekday() >= 5:
        return False, f"周末休市（开盘时间为北京时间 {bj(open_)}–{bj(close_)}）"
    if open_ <= now < close_:
        return True, f"美股交易中（北京时间 {bj(open_)}–{bj(close_)}）"
    return False, f"美股未开盘（北京时间 {bj(open_)}–{bj(close_)} 交易，节假日除外）"

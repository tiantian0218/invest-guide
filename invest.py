#!/usr/bin/env python3
"""汇丰香港美股账户辅助工具（只读，不下单）。

  python invest.py plan [--cny 15000]          按目标比例算出能买几股、费用、买完后的 TRB
  python invest.py add 2026-10-09 QQQM 7 312.5 [--fee 18]   记录一笔你在汇丰 App 里完成的成交（卖出用负股数）
  python invest.py status                      当前持仓、扣费后盈亏、TRB 警告、比例偏离提醒
  python invest.py backtest [--years 1 3 5 10] 历史滚动持有期回测（扣全部费用）
  python invest.py mc [--years 1] [--sims 20000]  蒙特卡洛（历史月收益块自助抽样）
  任何命令都可加 --weights QQQM=0.7,VOO=0.3 覆盖 config 里的目标比例
"""
import argparse
import csv
import json
import logging
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text()) if (ROOT / "config.json").exists() else {}
TRADES = ROOT / "trades.csv"
CACHE = ROOT / "data"
CACHE.mkdir(exist_ok=True)

TD_PER_YEAR = 252
TD_PER_MONTH = 21


def parse_weights(s):
    if not s:
        return CFG["targets"]
    w = {k: float(v) for k, v in (p.split("=") for p in s.split(","))}
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}


def proxy(t):
    return CFG.get("history_proxy", {}).get(t, t)


def history(tickers):
    key = "_".join(sorted(set(tickers)))
    f = CACHE / f"hist_{key}.csv"
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        return pd.read_csv(f, index_col=0, parse_dates=True)
    # Yahoo 对单次超过约 10 年的区间常返回空，按 8 年分段下载再拼接
    edges = list(pd.date_range("1999-03-10", pd.Timestamp.today(), freq="8YS")) + [pd.Timestamp.today() + pd.Timedelta(days=1)]
    edges[0] = pd.Timestamp("1999-03-10")
    want = sorted(set(tickers))
    parts = []
    for s, e in zip(edges[:-1], edges[1:]):
        for attempt in range(4):
            d = yf.download(want, start=s, end=e, auto_adjust=True, progress=False)["Close"]
            d = d.to_frame(want[0]) if isinstance(d, pd.Series) else d
            d = d.dropna()
            expected = len(pd.bdate_range(s, min(e, pd.Timestamp.today()))) * 0.9
            if all(t in d for t in want) and len(d) >= expected:
                break
            time.sleep(3)
        else:
            if f.exists():
                return pd.read_csv(f, index_col=0, parse_dates=True)
            sys.exit(f"历史数据下载失败: {tickers} {s.date()}~{e.date()}，稍后重试")
        parts.append(d)
    df = pd.concat(parts)
    df = df[~df.index.duplicated()].sort_index()
    if df.index.to_series().diff().dt.days.max() > 10:
        if f.exists():
            return pd.read_csv(f, index_col=0, parse_dates=True)
        sys.exit("历史数据有缺口，稍后重试")
    df.to_csv(f)
    return df


def quotes(tickers):
    want = sorted(set(tickers)) + ["HKD=X", "CNY=X"]
    for attempt in range(4):
        df = yf.download(want, period="7d", auto_adjust=True, progress=False)["Close"]
        if len(df):
            last = df.ffill().iloc[-1]
            missing = [t for t in want if pd.isna(last.get(t))]
            if not missing:
                return last
        time.sleep(3)
    import market_data
    try:
        q = market_data.sina_quotes(sorted(set(tickers)))
        q["HKD=X"], q["CNY=X"] = market_data.fx()
        if all(t in q for t in want):
            return pd.Series(q)
    except Exception:
        pass
    sys.exit(f"实时报价获取失败: {want}，稍后重试")


def fx_rates(q):
    return float(q["HKD=X"]), float(q["CNY=X"])


def fees():
    f = CFG["fees"]
    return f["per_trade_usd"], f["monthly_fee_hkd"], f["fx_cost_pct"] / 100, f["dividend_withholding_drag_pct"] / 100


# ---------------------------------------------------------------- plan
def cmd_plan(a):
    w = parse_weights(a.weights)
    q = quotes(list(w))
    usdhkd, usdcny = fx_rates(q)
    per_trade, _, fx_cost, _ = fees()
    usd = a.cny / usdcny * (1 - fx_cost)
    print(f"{a.cny:,.0f} CNY -> 约 {usd:,.2f} USD（已扣换汇点差 {fx_cost*100:.1f}%），USD/CNY={usdcny:.4f}\n")

    budget = usd - per_trade * len(w)
    rows, spent = [], 0.0
    for t, wt in w.items():
        px = float(q[t])
        n = int(budget * wt // px)
        rows.append((t, wt, px, n, n * px))
        spent += n * px
    # 用剩余现金按目标比例缺口补股
    left = budget - spent
    for _ in range(50):
        gaps = sorted(rows, key=lambda r: (r[4] / max(spent, 1)) - r[1])
        bought = False
        for i, r in enumerate(rows):
            if r[0] == gaps[0][0] and r[2] <= left:
                rows[i] = (r[0], r[1], r[2], r[3] + 1, r[4] + r[2])
                spent += r[2]
                left -= r[2]
                bought = True
        if not bought:
            break

    print(f"{'代码':<6}{'目标':>6}{'股价':>10}{'股数':>6}{'金额USD':>11}{'实际占比':>9}")
    for t, wt, px, n, amt in rows:
        print(f"{t:<6}{wt*100:>5.0f}%{px:>10.2f}{n:>6}{amt:>11.2f}{(amt/spent*100 if spent else 0):>8.1f}%")
    trades = sum(1 for r in rows if r[3] > 0)
    cash = usd - spent - per_trade * trades
    trb = (spent + cash) * usdhkd + CFG["cash_hkd"]
    print(f"\n佣金 {trades} 笔 x {per_trade} USD = {trades*per_trade} USD（占本金 {trades*per_trade/usd*100:.2f}%）")
    print(f"剩余现金 {cash:,.2f} USD；买完后 TRB 约 {trb:,.0f} HKD")
    trb_min = CFG["trb"]["min_hkd"]
    drop = 1 - (trb_min - cash * usdhkd - CFG["cash_hkd"]) / (spent * usdhkd) if spent else 0
    print(f"股票部分下跌超过 {drop*100:.1f}% 时 TRB 会跌破 {trb_min:,} HKD（之后每月扣 {CFG['trb']['below_fee_hkd_per_month']} HKD）")


# ---------------------------------------------------------------- add / status
def cmd_add(a):
    with TRADES.open("a", newline="") as f:
        csv.writer(f).writerow([a.date, a.ticker.upper(), a.shares, a.price, a.fee, a.note])
    print(f"已记录: {a.date} {a.ticker.upper()} {a.shares} 股 @ {a.price} USD, 佣金 {a.fee} USD")


def cmd_status(a):
    tr = pd.read_csv(TRADES)
    w = parse_weights(a.weights)
    if tr.empty:
        print("trades.csv 还没有成交记录。成交后用 `python invest.py add ...` 记一笔。")
        return
    pos = tr.groupby("ticker")["shares"].sum()
    cost = (tr["shares"] * tr["price_usd"] + tr["fee_usd"]).sum()
    q = quotes(list(pos.index) + list(w))
    usdhkd, usdcny = fx_rates(q)
    _, monthly_fee, fx_cost, _ = fees()

    first = pd.to_datetime(tr["date"]).min()
    months = max(0, (pd.Timestamp.today() - first).days // 30)
    paid_monthly_usd = monthly_fee * months / usdhkd

    vals = {t: n * float(q[t]) for t, n in pos.items() if n}
    mv = sum(vals.values())
    pnl = mv - cost - paid_monthly_usd
    print(f"USD/HKD={usdhkd:.4f}  USD/CNY={usdcny:.4f}\n")
    print(f"{'代码':<6}{'股数':>6}{'现价':>10}{'市值USD':>11}{'占比':>7}{'目标':>7}")
    for t, v in vals.items():
        print(f"{t:<6}{pos[t]:>6g}{float(q[t]):>10.2f}{v:>11.2f}{v/mv*100:>6.1f}%{w.get(t,0)*100:>6.0f}%")
    print(f"\n总成本(含佣金) {cost:,.2f} USD   市值 {mv:,.2f} USD")
    print(f"扣费后盈亏 {pnl:+,.2f} USD ({pnl/cost*100:+.2f}%)  ≈ {pnl*usdcny:+,.0f} CNY（未扣换回人民币点差）")

    trb = mv * usdhkd + CFG["cash_hkd"]
    tmin = CFG["trb"]["min_hkd"]
    warn_line = tmin * (1 + CFG["trb"]["warn_buffer_pct"] / 100)
    print(f"\nTRB ≈ {trb:,.0f} HKD（门槛 {tmin:,}）")
    if trb < tmin:
        print(f"  !! 已低于门槛：三个月平均低于 {tmin:,} 将每月扣 {CFG['trb']['below_fee_hkd_per_month']} HKD，建议补入现金")
    elif trb < warn_line:
        print(f"  !  距门槛不足 {CFG['trb']['warn_buffer_pct']}%，再跌 {(1-tmin/trb)*100:.1f}% 就会触发管理费")

    drift = CFG["rebalance_drift_pp"]
    for t in set(w) | set(vals):
        d = vals.get(t, 0) / mv * 100 - w.get(t, 0) * 100
        if abs(d) > drift:
            print(f"  比例提醒: {t} 偏离目标 {d:+.1f} 个百分点（阈值 {drift}），可考虑用新资金补低配的一侧")


# ---------------------------------------------------------------- backtest / mc
def portfolio_paths_start(px, w):
    """返回各标的相对首日的价格矩阵（列对齐 w 的顺序）。"""
    cols = [proxy(t) for t in w]
    return px[cols].values, np.array(list(w.values()))


def net_outcome(gross_mult, min_mult_monthly, years, n_tickers, usd0, usdhkd):
    """gross_mult: 期末组合倍数; min_mult_monthly: 每月末组合倍数矩阵（用于判断 TRB 是否跌破）。"""
    per_trade, monthly_fee, fx_cost, drag = fees()
    invested = usd0 * (1 - fx_cost) - per_trade * n_tickers
    end = invested * gross_mult * (1 - drag) ** years - per_trade * n_tickers
    trb_hkd = invested * min_mult_monthly * usdhkd + CFG["cash_hkd"]
    below_months = (trb_hkd < CFG["trb"]["min_hkd"]).sum(axis=1)
    fee_usd = (monthly_fee * years * 12 + CFG["trb"]["below_fee_hkd_per_month"] * below_months) / usdhkd
    end = np.maximum(end - fee_usd, 0) * (1 - fx_cost)
    return end / usd0 - 1, below_months


def summarize(label, r, below, years):
    pct = np.percentile(r, [5, 25, 50, 75, 95]) * 100
    ann = (1 + np.median(r)) ** (1 / years) - 1
    print(f"\n== {label} ==  样本 {len(r):,}")
    print(f"  亏损概率 {np.mean(r < 0)*100:5.1f}%   亏超20% {np.mean(r < -0.2)*100:5.1f}%   亏超40% {np.mean(r < -0.4)*100:5.1f}%")
    print(f"  收益分位  5%:{pct[0]:+7.1f}%  25%:{pct[1]:+7.1f}%  中位:{pct[2]:+7.1f}%  75%:{pct[3]:+7.1f}%  95%:{pct[4]:+7.1f}%")
    print(f"  中位年化 {ann*100:+.1f}%   期间触发 TRB 管理费的概率 {np.mean(below > 0)*100:.1f}%")


def cmd_backtest(a):
    w = parse_weights(a.weights)
    px = history([proxy(t) for t in w])
    q = quotes([])
    usdhkd, usdcny = fx_rates(q)
    usd0 = CFG["principal_cny"] / usdcny
    P, wt = portfolio_paths_start(px, w)
    print(f"组合 {w}，历史 {px.index[0].date()} ~ {px.index[-1].date()}（QQQM/VOO 用 QQQ/SPY 代替，含分红再投）")
    print(f"本金 {CFG['principal_cny']:,} CNY ≈ {usd0:,.0f} USD；收益为换回美元/港币后、扣佣金/点差/管理费的净收益（未计人民币汇率变化）")
    for y in a.years:
        n = int(y * TD_PER_YEAR)
        if n >= len(P):
            continue
        starts = np.arange(0, len(P) - n)
        steps = np.arange(TD_PER_MONTH, n + 1, TD_PER_MONTH)
        rel_end = P[starts + n] / P[starts]
        gross = rel_end @ wt
        monthly = np.stack([(P[starts + s] / P[starts]) @ wt for s in steps], axis=1)
        r, below = net_outcome(gross, monthly, y, len(w), usd0, usdhkd)
        summarize(f"任意一天买入、持有 {y:g} 年", r, below, y)
        worst = starts[np.argmin(r)]
        print(f"  最差起点 {px.index[worst].date()}（{r.min()*100:+.1f}%），最好起点 {px.index[starts[np.argmax(r)]].date()}（{r.max()*100:+.1f}%）")
    s = pd.Series((P / P[0]) @ wt)
    mdd = (s / s.cummax() - 1).min()
    print(f"\n全历史最大回撤（买入持有）: {mdd*100:.1f}%")


def cmd_mc(a):
    w = parse_weights(a.weights)
    px = history([proxy(t) for t in w])
    q = quotes([])
    usdhkd, usdcny = fx_rates(q)
    usd0 = CFG["principal_cny"] / usdcny
    m = px[[proxy(t) for t in w]].resample("ME").last().pct_change().dropna().values @ np.array(list(w.values()))
    rng = np.random.default_rng(a.seed)
    H, B = int(a.years * 12), 12
    nblk = -(-H // B)
    idx = rng.integers(0, len(m) - B, size=(a.sims, nblk))
    paths = m[(idx[:, :, None] + np.arange(B)).reshape(a.sims, -1)[:, :H]]
    cum = np.cumprod(1 + paths, axis=1)
    r, below = net_outcome(cum[:, -1], cum, a.years, len(w), usd0, usdhkd)
    print(f"蒙特卡洛：{len(m)} 个历史月收益，12 个月块自助抽样 {a.sims:,} 次，组合 {w}")
    summarize(f"持有 {a.years:g} 年", r, below, a.years)
    print(f"  按本金 {CFG['principal_cny']:,} CNY 折算: 中位 {np.median(r)*CFG['principal_cny']:+,.0f} CNY，"
          f"5% 最差情形 {np.percentile(r,5)*CFG['principal_cny']:+,.0f} CNY，95% 最好情形 {np.percentile(r,95)*CFG['principal_cny']:+,.0f} CNY")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--weights")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("plan"); s.add_argument("--cny", type=float, default=CFG["principal_cny"])
    s = sp.add_parser("add")
    s.add_argument("date"); s.add_argument("ticker"); s.add_argument("shares", type=float); s.add_argument("price", type=float)
    s.add_argument("--fee", type=float, default=CFG["fees"]["per_trade_usd"]); s.add_argument("--note", default="")
    sp.add_parser("status")
    s = sp.add_parser("backtest"); s.add_argument("--years", type=float, nargs="+", default=[1, 3, 5, 10])
    s = sp.add_parser("mc"); s.add_argument("--years", type=float, default=1); s.add_argument("--sims", type=int, default=20000)
    s.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    {"plan": cmd_plan, "add": cmd_add, "status": cmd_status, "backtest": cmd_backtest, "mc": cmd_mc}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

"""网站首页「今天」：每天打开只需要看这一页。今天要不要操作 → 我的钱 → 如果大跌会怎样 → 市场一句话。"""
import html

import numpy as np
import pandas as pd
import streamlit as st

import invest
import signals
import site_account
import site_macro

UP, DOWN, MUTED = "#d62728", "#16a34a", "#6b7280"
BOX = "padding:14px 16px;border-radius:12px;background:#f9fafb;margin:6px 0"
WEIGHT_Q = 0.7
CRASHES = [("2000 年科网泡沫", "2000-03-01", "2002-12-31"), ("2008 年金融危机", "2007-10-01", "2009-06-30"),
           ("2020 年疫情", "2020-02-01", "2020-04-30"), ("2022 年加息", "2021-11-01", "2022-12-31")]


@st.cache_data(ttl=86400, show_spinner=False)
def _history():
    return invest.history(["QQQ", "SPY"])


@st.cache_data(ttl=86400, show_spinner=False)
def evidence():
    """规则把握度用到的历史证据：70/30 按月定投，满 N 年时亏钱的比例；各次大跌的最大跌幅和回本时间。"""
    px = _history()
    nav = (1 + (WEIGHT_Q * px["QQQ"].pct_change() + (1 - WEIGHT_Q) * px["SPY"].pct_change()).fillna(0)).cumprod()
    m = nav.resample("ME").last()
    out = {"start": int(px.index[0].year)}
    for years in (3, 5, 10):
        h, losses, n = years * 12, 0, 0
        for i in range(len(m) - h):
            units = (1 / m.iloc[i:i + h]).sum()
            losses += units * m.iloc[i + h] < h
            n += 1
        out[f"dca_loss_{years}y"] = losses / n if n else None
    crashes = []
    for name, a, b in CRASHES:
        seg = nav[a:b]
        trough_day = seg.idxmin()
        peak_day = nav[a:trough_day].idxmax()
        dd = float(nav[trough_day] / nav[peak_day] - 1)
        back = nav[trough_day:][nav[trough_day:] >= nav[peak_day]]
        months = round((back.index[0] - peak_day).days / 30.4) if len(back) else None
        crashes.append({"name": name, "dd": dd, "months": months})
    yearly_dd = nav.groupby(nav.index.year).apply(lambda s: float((s / s.cummax() - 1).min()))
    out["crashes"] = crashes
    out["typical_year_dd"] = float(yearly_dd.median())
    return out


def confidence(asset, signal):
    """返回 (星级 0-3, 依据)。星级说的是这条规则有多少历史证据，不是对涨跌的把握。"""
    ev = evidence()
    if "模拟盘" in asset:
        return 0, "实验中，只记账不下单，满 2 个月再看效果"
    if "个股" in asset:
        if signal == "卖出":
            return 2, "风控规则：限制单只股票的最大亏损和仓位，目的是不让一次失误伤筋动骨，不是预测涨跌"
        if signal == "考虑卖出":
            return 1, "证据弱：跌破 200 日均线对单只股票后续涨跌的预测力有限，只作提醒，可以不照做"
        return 1, "个股波动大，规则只管仓位和止损"
    if signal == "加码":
        return 2, "大跌时用闲钱多买，买到的价格更低；前提是不借钱、不动用生活费"
    loss10 = ev.get("dca_loss_10y")
    return 3, (f"证据最强：{ev['start']} 年以来任意月份开始按月定投 70/30，满 10 年时亏钱的比例为 {loss10:.0%}，"
               f"满 5 年为 {ev['dca_loss_5y']:.0%}")


def stars(n):
    return f'<span style="color:#f59e0b;letter-spacing:1px">{"★" * n}{"☆" * (3 - n)}</span>'


def _status():
    is_open, text = signals.us_market_status()
    now = pd.Timestamp.now(tz="Asia/Shanghai")
    dot = "#16a34a" if is_open else "#9ca3af"
    st.markdown(f'<div style="color:{MUTED};font-size:14px">北京时间 {now:%m月%d日 %H:%M} · '
                f'<span style="color:{dot}">●</span> 美股{html.escape(text)}</div>', unsafe_allow_html=True)


def _personal(s):
    snap = None
    try:
        snap = s.get_paper(s.uid)
    except Exception:
        pass
    sig = ((snap or {}).get("payload") or {}).get("signals")
    if sig:
        site_account.signal_card(sig, snap["updated_at"], confidence, stars)
    else:
        st.info("还没有收到你的今日信号（本机推送程序每天早上会上传一次）。下面先显示通用的指数信号。")
        site_macro._signal()
    return site_account.money_strip(s)


def _risk(amount, personal):
    ev = evidence()
    head = "如果市场大跌，你的账户会怎样" if personal else "如果市场大跌，这笔钱会怎样"
    rows = ""
    for c in ev["crashes"]:
        loss = amount * c["dd"]
        back = f"约 {c['months'] // 12} 年 {c['months'] % 12} 个月回本" if c["months"] else "至今未回本"
        width = min(100, abs(c["dd"]) * 100)
        rows += (f'<div style="padding:8px 0;border-top:1px solid #eef0f3">'
                 f'<div style="display:flex;justify-content:space-between"><b>{c["name"]}</b>'
                 f'<span style="color:{DOWN};font-weight:700">{c["dd"]:.0%} · −¥{abs(loss):,.0f}</span></div>'
                 f'<div style="height:6px;background:#e5e7eb;border-radius:3px;margin:4px 0">'
                 f'<div style="width:{width}%;height:6px;background:{DOWN};border-radius:3px"></div></div>'
                 f'<div style="font-size:12px;color:{MUTED}">从最高点算，{back}（期间继续定投会更快）</div></div>')
    typical = amount * ev["typical_year_dd"]
    st.markdown(
        f'<div style="{BOX}"><b style="font-size:17px">{head}</b>'
        f'<div style="font-size:14px;margin:4px 0 6px">按 70% 纳指 100 + 30% 标普 500 的历史走势估算，本金 ¥{amount:,.0f}：</div>'
        f'<div style="font-size:14px;margin-bottom:4px">普通年份，年内最多浮亏一般在 <b style="color:{DOWN}">'
        f'{ev["typical_year_dd"]:.0%}（约 −¥{abs(typical):,.0f}）</b>，这是正常波动。</div>{rows}</div>',
        unsafe_allow_html=True)
    st.caption("看完问自己一句：真遇到这种跌幅，我能拿住不卖吗？如果不能，说明纳指比例偏高或投入偏多，"
               "可以在工具箱的定投计算器里试试更低的比例。历史不代表未来，未来的跌幅可能更大。")


def _market():
    try:
        d = site_macro._index_closes()
        cols = st.columns(2)
        for col, t, name in ((cols[0], "QQQM", "纳指 100"), (cols[1], "SPYM", "标普 500")):
            c = d[t].dropna()
            chg = float(c.iloc[-1] / c.iloc[-2] - 1)
            col.metric(f"{t} · {name}", f"${c.iloc[-1]:.2f}", f"{chg:+.2%}", delta_color="inverse")
    except Exception:
        st.info("行情暂时获取失败，请稍后刷新。")
    site_macro._safe(site_macro._today, "涨跌解读")


def _next_event():
    cal = site_macro._calendar()
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    nxt = next((e for e in cal if not e["past"]), None)
    if not nxt:
        return
    import macro
    bj = macro.bj_time(nxt)
    days = (pd.Timestamp(nxt["date"]) - today).days
    when = "今天" if days == 0 else "明天" if days == 1 else f"{days} 天后"
    st.markdown(f'<div style="{BOX}"><span style="color:{MUTED}">下一件大事</span> · <b>{nxt["name"]}</b> · '
                f'{when}（北京时间 {bj:%m/%d %H:%M}）<div style="font-size:14px;margin-top:2px">{nxt["why"]}</div></div>',
                unsafe_allow_html=True)


def render(s):
    _status()
    st.subheader("今天要做什么")
    total = None
    if s is not None:
        try:
            total = _personal(s)
        except Exception as e:
            st.info(f"个人数据暂时读取失败（{type(e).__name__}），先显示通用信号。")
            site_macro._signal()
    else:
        site_macro._signal()
        st.caption("登录后（「我的账户」页），这里会显示你自己的信号、持仓和盈亏。")
    st.markdown("**把握度怎么看：** ★★★ 有几十年历史数据支持；★★ 风控或常识规则，有道理但优势不大；"
                "★ 证据弱，只作提醒；☆ 实验中。星级说的是规则有多可靠，不是“明天会涨”的把握。")

    st.subheader("风险预期")
    if total:
        amount = total
    else:
        amount = st.number_input("想投入多少钱（元）", 1000, 10_000_000, 10_000, step=1000)
    site_macro._safe(lambda: _risk(amount, bool(total)), "风险测算")

    st.subheader("市场一句话")
    _market()
    site_macro._safe(_next_event, "宏观日历")
    st.caption("想了解利率、通胀、产业链这些背后的原因，去「看懂市场」；计算器和历史数据在「工具箱」。")

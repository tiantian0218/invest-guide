"""网站首页「今天」：每天打开只需要看最上面那张日签。往下依次是：我的钱 → 每一项怎么做 → 心理准备 → 市场一句话。"""
import numpy as np
import pandas as pd
import streamlit as st

import invest
import signals
import site_account
import site_macro
import site_ui as ui
from site_ui import ACT, CALM, DOWN, FAINT, LINE, MUTED, UP, WARN, esc

WEIGHT_Q = 0.7
CRASHES = [("2000 年科网泡沫", "2000-03-01", "2002-12-31"), ("2008 年金融危机", "2007-10-01", "2009-06-30"),
           ("2020 年疫情", "2020-02-01", "2020-04-30"), ("2022 年加息", "2021-11-01", "2022-12-31")]
ACTION_SIGNALS = {"买入", "加码", "卖出"}


@st.cache_data(ttl=86400, show_spinner=False)
def _history():
    return invest.history(["QQQ", "SPY"])


@st.cache_data(ttl=86400, show_spinner=False)
def _vix():
    d = invest.yf.download("^VIX", period="10y", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    return d if len(d) > 252 else None


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
        return 2, ("大跌时照常定投、不要停最重要；多投的钱只用本来不打算投资的工资结余。"
                   "回测显示平时攒现金专等大跌反而少赚（见工具箱 · 规则实验室）")
    loss10 = ev.get("dca_loss_10y")
    return 3, (f"证据最强：{ev['start']} 年以来任意月份开始按月定投 70/30，满 10 年时亏钱的比例为 {loss10:.0%}，"
               f"满 5 年为 {ev['dca_loss_5y']:.0%}")


def stars(n):
    return f'<span style="color:#f59e0b;letter-spacing:1px">{"★" * n}{"☆" * (3 - n)}</span>'


# ---------------------------------------------------------------- 日签上的小标签
def _quotes():
    d = site_macro._index_closes()
    out = {}
    for t in ("QQQM", "SPYM"):
        c = d[t].dropna()
        trend = d["QQQ"].dropna() if t == "QQQM" and "QQQ" in d else c
        out[t] = {"price": float(c.iloc[-1]), "chg": float(c.iloc[-1] / c.iloc[-2] - 1),
                  "dd": float(trend.iloc[-1] / trend.iloc[-252:].max() - 1), "date": c.index[-1]}
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _temperature():
    t, label, _ = signals.market_temperature(_history()["QQQ"], _vix())
    return t, label


def _next_event():
    cal = site_macro._calendar()
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    nxt = next((e for e in cal if not e["past"]), None)
    if not nxt:
        return None
    import macro
    days = (pd.Timestamp(nxt["date"]) - today).days
    return {**nxt, "bj": macro.bj_time(nxt), "when": "今天" if days == 0 else "明天" if days == 1 else f"{days} 天后"}


def _chips(q):
    chips = [ui.chip(f"纳指 {ui.move(q['QQQM']['chg'])}"), ui.chip(f"标普 {ui.move(q['SPYM']['chg'])}")]
    try:
        t, label = _temperature()
        chips.append(ui.chip(f"市场温度 <b>{t}°</b> {label}"))
    except Exception:
        pass
    try:
        if e := _next_event():
            chips.append(ui.chip(f"{esc(e['when'])}：{esc(e['name'])}"))
    except Exception:
        pass
    return chips


# ---------------------------------------------------------------- 日签
def _personal_signal(s):
    try:
        snap = s.get_paper(s.uid)
    except Exception:
        return None, None
    sig = ((snap or {}).get("payload") or {}).get("signals")
    return sig, (snap or {}).get("updated_at")


def _generic_rows(q):
    rows = []
    for t, name in (("QQQM", "纳指 100"), ("SPYM", "标普 500")):
        dd = q[t]["dd"]
        if dd <= -0.20:
            rows.append({"asset": f"{t} · {name}", "signal": "加码", "color": UP, "chg": q[t]["chg"],
                         "why": f"距一年高点 {dd:.0%}，进入大跌区。定投日照常买、别停；有闲钱可以多投一点，但不要借钱。"})
        else:
            rows.append({"asset": f"{t} · {name}", "signal": "定投日买", "color": ACT, "chg": q[t]["chg"],
                         "why": f"距一年高点 {dd:.0%}。到你定的定投日照常买，其他日子不用管。"})
    return rows


def _hero(q, sig, updated_at):
    chips = _chips(q)
    if sig:
        acts = [r for r in sig["rows"] if r["signal"] in ACTION_SIGNALS]
        tone = WARN if any(r["signal"] == "卖出" for r in acts) else ACT if acts else CALM
        age = (pd.Timestamp.now(tz="Asia/Shanghai").normalize()
               - pd.Timestamp(sig["date"]).tz_localize("Asia/Shanghai")).days
        updated = pd.Timestamp(updated_at).tz_convert("Asia/Shanghai")
        why = (f"根据你的持仓和规则算出，{updated:%m-%d %H:%M} 更新。"
               + ("具体每一项看下面。" if acts else "定投日以外，什么都不做就是最好的操作。"))
        if age > 0:
            why += f'<br><span class="warn">这是 {age} 天前的信号（电脑当天可能没开机），以汇丰 App 的价格为准。</span>'
        ui.day_card(sig["headline"], why, tone, chips)
        return
    crash = min(q["QQQM"]["dd"], q["SPYM"]["dd"]) <= -0.20
    if crash:
        ui.day_card("大跌区：定投别停", "市场离一年高点跌了两成以上。历史上坚持定投的人，正是在这种时候买到了便宜的份额。", UP, chips)
    else:
        ui.day_card("今天不用操作", "到你自己定的定投日照常买入就行，其他日子不用看盘。不因为涨了追加，也不因为跌了卖出。",
                    CALM, chips)


def _rows(rows, title="每一项怎么做"):
    ui.section(title, "标签颜色：红 = 买，绿 = 卖，蓝 = 按计划，灰 = 只观察")
    body, basis = "", {}
    for r in rows:
        n, b = confidence(r["asset"], r["signal"])
        basis.setdefault(b, (n, []))[1].append(r["asset"].split(" · ")[0])
        chg = f" {ui.move(r['chg'])}" if r.get("chg") is not None else ""
        body += (f'<div class="ui-row">{ui.tag(r["signal"], r["color"])}<div style="flex:1;min-width:0">'
                 f'<div style="font-weight:600">{esc(r["asset"])}{chg}'
                 f'<span style="float:right;font-size:13px" title="规则的历史证据强度">{stars(n)}</span></div>'
                 f'<div style="font-size:14px;line-height:1.55;margin-top:2px">{esc(r["why"])}</div></div></div>')
    ui.card(body, "background:#fff;border:1px solid " + LINE)
    with st.expander("星星是什么意思？规则依据"):
        st.markdown("星星表示**这条规则有多少历史证据**，不是“明天会涨”的把握。")
        for b, (n, names) in basis.items():
            st.markdown(f"{stars(n)} **{'、'.join(names)}**：{b}", unsafe_allow_html=True)
        rules = [f"- **{r['asset']}**：{r['rule']}" for r in rows if r.get("rule")]
        if rules:
            st.markdown("**对应的规则**\n" + "\n".join(rules))
        st.caption("指数没有“卖出信号”：只在需要用钱、或接近目标时按计划慢慢卖。信号全部来自写死的规则，不构成投资建议。")


# ---------------------------------------------------------------- 收益与风险预期
HORIZONS = {"1 个月": 1, "3 个月": 3, "6 个月": 6, "1 年": 12, "3 年": 36, "5 年": 60, "10 年": 120}


@st.cache_data(ttl=86400, show_spinner=False)
def outcomes(dca):
    """70/30 组合在每个历史起点放 N 个月后的结果（终值 / 投入）。dca=True 为每月投入同样的钱。"""
    px = _history()
    m = px.resample("ME").last()
    r = (WEIGHT_Q * m["QQQ"].pct_change() + (1 - WEIGHT_Q) * m["SPY"].pct_change()).dropna().values
    out = {}
    for name, h in HORIZONS.items():
        vals = []
        for i in range(len(r) - h + 1):
            if dca:
                v = 0.0
                for k in range(h):
                    v = (v + 1) * (1 + r[i + k])
                vals.append(v / h)
            else:
                vals.append(float(np.prod(1 + r[i:i + h])))
        a = np.array(vals)
        out[name] = {"min": a.min(), "p10": np.percentile(a, 10), "p50": np.median(a), "p90": np.percentile(a, 90),
                     "max": a.max(), "loss": float((a < 1).mean()), "n": len(a)}
    return {"start": int(m.index[0].year), "rows": out}


def _outcome_chart(rows):
    import plotly.graph_objects as go
    xs = list(rows)
    pct = lambda k: [(rows[x][k] - 1) * 100 for x in xs]
    fig = go.Figure()
    fig.add_bar(x=xs, y=[b - a for a, b in zip(pct("min"), pct("max"))], base=pct("min"), width=0.08,
                marker_color="#cbd5e1", name="历史最差 ~ 最好", hoverinfo="skip")
    fig.add_bar(x=xs, y=[b - a for a, b in zip(pct("p10"), pct("p90"))], base=pct("p10"), width=0.42,
                marker_color="#93c5fd", name="10 次里有 8 次落在这里", hoverinfo="skip")
    fig.add_scatter(x=xs, y=pct("p50"), mode="markers+text", marker=dict(color=ui.INK, size=9), name="一般情况",
                    text=[f"{v:+.0f}%" for v in pct("p50")], textposition="middle right", textfont=dict(size=12))
    fig.add_hline(y=0, line=dict(color=DOWN, width=1, dash="dot"))
    fig.update_layout(height=320, barmode="overlay", margin=dict(l=0, r=0, t=10, b=0), hovermode=False,
                      legend=dict(orientation="h", y=-0.18), yaxis=dict(ticksuffix="%", title=None))
    st.plotly_chart(fig, config={"displayModeBar": False})


def _outcomes(amount, dca, personal):
    data = outcomes(dca)
    rows = data["rows"]
    unit = f"每月 ¥{amount:,.0f}" if dca else f"一次投入 ¥{amount:,.0f}"
    _outcome_chart(rows)
    body = ""
    for name, h in HORIZONS.items():
        o = rows[name]
        invested = amount * (h if dca else 1)
        cell = lambda k: (f'<b class="ui-num" style="color:{UP if o[k] >= 1 else DOWN}">¥{invested * o[k]:,.0f}</b>'
                          f'<br><span class="ui-note">{(o[k] - 1):+.0%}</span>')
        loss_color = WARN if o["loss"] >= 0.2 else ui.INK if o["loss"] >= 0.08 else CALM
        body += (f'<tr><td><b>{name}</b><br><span class="ui-note">投入 ¥{invested:,.0f}</span></td>'
                 f'<td>{cell("p10")}</td><td>{cell("p50")}</td><td>{cell("p90")}</td>'
                 f'<td><b class="ui-num" style="color:{loss_color}">{o["loss"]:.0%}</b></td></tr>')
    st.markdown(f'<table class="ui-table"><tr><th>放多久</th><th>差的情况</th><th>一般情况</th><th>好的情况</th>'
                f'<th>亏钱概率</th></tr>{body}</table>', unsafe_allow_html=True)
    short, long = rows["1 个月"], rows["10 年"]
    st.caption(f"{unit}，按 {data['start']} 年以来每个月都当一次起点算（70% 纳指 100 + 30% 标普 500，含分红）。"
               "“差的情况”是 10 次里最差的 1 次，“好的情况”是 10 次里最好的 1 次。"
               f"放 1 个月亏钱的概率是 {short['loss']:.0%}，放 10 年降到 {long['loss']:.0%}：时间是最好的风险控制。")
    ui.ask(f"<b>问自己一句：</b>表里“差的情况”那一列，真发生在你身上，你能拿住不卖吗？"
           f"历史最差的一次，放 1 年会{'少' if dca else '跌'}到 {rows['1 年']['min'] - 1:.0%}。"
           "如果承受不了，就降低纳指比例或少投一些（工具箱 · 定投计算器可以试）。历史不代表未来。")


def _risk(amount, personal):
    ev = evidence()
    typical = amount * ev["typical_year_dd"]
    rows = ""
    for c in ev["crashes"]:
        back = (f"{c['months'] // 12} 年 {c['months'] % 12} 个月回本" if c["months"] >= 12 else f"{c['months']} 个月回本") \
            if c["months"] else "至今未回本"
        rows += (f'<div style="padding:9px 0;border-top:1px solid {LINE}">'
                 f'<div style="display:flex;justify-content:space-between;gap:8px"><span>{c["name"]}</span>'
                 f'<b class="ui-num" style="color:{DOWN}">−¥{abs(amount * c["dd"]):,.0f}</b></div>'
                 f'<div style="display:flex;align-items:center;gap:8px;margin-top:4px">'
                 f'<div style="flex:1;height:8px;background:#eef1f5;border-radius:4px">'
                 f'<div style="width:{min(100, abs(c["dd"]) * 100):.0f}%;height:8px;background:{DOWN};border-radius:4px"></div></div>'
                 f'<span class="ui-num" style="font-size:13px;color:{MUTED};min-width:120px;text-align:right">'
                 f'{c["dd"]:.0%} · {back}</span></div></div>')
    who = "你的账户" if personal else "这笔钱"
    ui.card(f'<div style="font-size:15px;line-height:1.6">按历史走势估算，{who}（¥{amount:,.0f}）在<b>普通年份</b>'
            f'年内最多浮亏一般在 <b class="ui-num" style="color:{DOWN};white-space:nowrap">{ev["typical_year_dd"]:.0%}（约 −¥{abs(typical):,.0f}）</b>，'
            f'这是正常波动。遇到大危机时：</div>{rows}'
            f'<div class="ui-note" style="margin-top:6px">回本时间从最高点算；期间继续定投，回本会更快。历史不代表未来，未来的跌幅可能更大。</div>')


# ---------------------------------------------------------------- 市场一句话
def _market():
    w = site_macro._why()
    lines = w["lines"]
    ui.card(f'<div style="color:{MUTED};font-size:13px">美东 {esc(w["date"])} 收盘</div>'
            f'<div style="font-size:17px;font-weight:700;margin:2px 0 4px">{esc(lines[0])}</div>'
            + "".join(f'<div style="font-size:14px;line-height:1.6">{esc(x)}</div>' for x in lines[1:3]))
    ui.ai_card(full=False)
    e = _next_event()
    if e:
        ui.card(f'<div style="color:{MUTED};font-size:13px">下一件大事 · {esc(e["when"])}（北京时间 {e["bj"]:%m/%d %H:%M}）</div>'
                f'<div style="font-size:16px;font-weight:700;margin:2px 0">{esc(e["name"])}</div>'
                f'<div style="font-size:14px;line-height:1.6">{esc(e["why"])}</div>')
    st.caption("涨跌原因是根据公开数据推算的相关性，不是确定的因果。想了解利率、通胀这些背后的原因，去「看懂市场」。")


def render(s):
    try:
        q = _quotes()
    except Exception:
        st.warning("行情暂时获取失败，请过 1 分钟刷新页面。")
        return
    sig, updated_at = _personal_signal(s) if s is not None else (None, None)
    _hero(q, sig, updated_at)
    is_open, text = signals.us_market_status()
    st.markdown(f'<div class="ui-note">{"🟢" if is_open else "⚪"} {esc(text)} · 价格为最近收盘价，以银行 App 为准</div>',
                unsafe_allow_html=True)

    total = None
    if s is not None:
        ui.section("我的钱")
        try:
            total = site_account.money_strip(s)
        except Exception as e:
            st.info(f"个人数据暂时读取失败（{type(e).__name__}）。")
        if total is None:
            st.caption("还没有记账数据，在「我的账户」记一笔入金后，这里会显示你的总资产和盈亏。")
    if sig:
        _rows(sig["rows"])
    else:
        _rows(_generic_rows(q))
        if s is None:
            st.caption("在「我的账户」登录后，这里会换成按你自己持仓算出来的信号。")

    ui.section("收益与风险预期：放多久，可能变成多少", "涨和跌都算给你看，先想清楚最坏情况，真遇到时才拿得住")
    a, b = st.columns([1, 1])
    mode = ui.pills("投入方式", ["一次性投入", "每月定投"], key="today_mode", where=a)
    dca = mode == "每月定投"
    default = 2000 if dca else int(round(total or 10_000, -2))
    amount = b.number_input("每月投入（元）" if dca else "投入多少钱（元）", 100, 10_000_000, default, step=500,
                            key=f"today_amt_{dca}")
    site_macro._safe(lambda: _outcomes(amount, dca, bool(total)), "收益测算")
    with st.expander("历史上的几次大危机，账户会跌多少、多久回本"):
        site_macro._safe(lambda: _risk(amount if not dca else amount * 12, bool(total) and not dca), "风险测算")

    ui.section("市场一句话")
    site_macro._safe(_market, "市场解读")
    ui.glossary()

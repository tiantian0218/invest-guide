"""「看懂市场」页：网站和本地看板共用。只解释市场，不给买卖建议。"""
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import lessons
import macro
import site_ui as ui

UP, DOWN, MUTED = "#d62728", "#16a34a", "#6b7280"
BOX = "padding:14px 16px;border-radius:12px;background:#f9fafb;margin:6px 0"


@st.cache_data(ttl=1800, show_spinner=False)
def _why():
    return macro.why_today()


@st.cache_data(ttl=3600, show_spinner=False)
def _yields():
    return macro.yields()


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _economy():
    return macro.economy()


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _calendar():
    return macro.calendar()


@st.cache_data(ttl=1800, show_spinner="正在拉取产业链行情…")
def _chain():
    return macro.chain_table()


@st.cache_data(ttl=3600 * 12, show_spinner="正在读取美国证监会公开的持仓报告…")
def _13f():
    return macro.holdings_13f()


@st.cache_data(ttl=3600, show_spinner=False)
def _qqqm():
    import market_data
    d, _ = market_data.closes(["QQQM"], "1y")
    return d["QQQM"].dropna()


def _box(inner, extra=""):
    return f'<div style="{BOX};{extra}">{inner}</div>'


def _card(label, main, sub, color=None):
    style = f"color:{color};" if color else ""
    return _box(f'<div style="color:{MUTED};font-size:14px">{label}</div>'
                f'<div style="font-size:26px;font-weight:700;{style}line-height:1.3">{main}</div>'
                f'<div style="color:{MUTED};font-size:13px">{sub}</div>', "height:100%")


def _explain(title, text):
    with st.expander(title):
        st.markdown(text)


def _safe(fn, what):
    try:
        fn()
    except Exception as e:
        st.info(f"{what}暂时获取失败，请稍后刷新。（{type(e).__name__}）")


# ---------------------------------------------------------------- ⓪ 今日信号（通用）
@st.cache_data(ttl=1800, show_spinner=False)
def _index_closes():
    import market_data
    d, _ = market_data.closes(["QQQM", "SPYM", "QQQ"], "2y")
    return d


def _signal(confidence=None, stars=None):
    d = _index_closes()
    rows = ""
    for t, name in (("QQQM", "纳指 100"), ("SPYM", "标普 500")):
        c = d[t].dropna()
        if t == "QQQM" and "QQQ" in d:
            c = d["QQQ"].dropna()
        dd = float(c.iloc[-1] / c.iloc[-252:].max() - 1)
        chg = float(c.iloc[-1] / c.iloc[-2] - 1)
        if dd <= -0.20:
            sig, color, why = "加码", UP, f"距一年高点 {dd:.0%}，进入大跌区。最重要的是照常定投、不要停；有本来不打算投资的结余可以多投一些，但不要借钱，也不要平时攒着现金专等大跌。"
        else:
            sig, color, why = "按计划买", "#1e78dc", (f"距一年高点 {dd:.0%}。定投日照常买，其他日子不用操作；"
                                                    "不因为涨了追加，也不因为跌了卖出。")
        rows += (f'<div style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-top:1px solid #eef0f3">'
                 f'<span style="background:{color};color:#fff;border-radius:6px;padding:2px 8px;font-weight:700;white-space:nowrap">{sig}</span>'
                 f'<div><b>{t} · {name}</b> <span style="color:{UP if chg >= 0 else DOWN}">{chg:+.2%}</span>'
                 f'<div style="font-size:14px;line-height:1.5">{why}</div>'
                 + (f'<div style="font-size:12px;color:{MUTED};margin-top:2px">把握度 {stars(confidence(t, sig)[0])} · '
                    f'{html.escape(confidence(t, sig)[1])}</div>' if confidence else "")
                 + '</div></div>')
    st.markdown(_box(f'<b style="font-size:17px">给指数定投者的信号</b>{rows}'), unsafe_allow_html=True)
    st.caption("指数没有“卖出信号”：只在你需要用钱、或接近目标时按计划慢慢卖。我们用 1999 年以来的数据测过，"
               "按利率、恐慌指数等宏观数据择时，结果都不如按时定投，所以宏观内容只用来理解市场。")


# ---------------------------------------------------------------- ① 今天为什么涨跌
def _today():
    w = _why()
    color = UP if w["qqqm"] >= 0 else DOWN
    first, rest = w["lines"][0], w["lines"][1:]
    items = "".join(f'<li style="margin:4px 0">{html.escape(x)}</li>' for x in rest)
    st.markdown(_box(
        f'<div style="color:{MUTED}">美东 {w["date"]} 收盘</div>'
        f'<div style="font-size:22px;font-weight:700;color:{color};margin:4px 0">{html.escape(first)}</div>'
        f'<ul style="margin:6px 0 0 0;padding-left:20px">{items}</ul>'), unsafe_allow_html=True)
    st.caption("这里说的是“可能的原因”，是根据公开数据推算的相关性，不是确定的因果。")
    ui.ai_card()


# ---------------------------------------------------------------- ② 接下来的大事
def _events():
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    cal = _calendar()
    soon = [dict(e, days=(pd.Timestamp(e["date"]) - today).days) for e in cal if not e["past"]][:5]
    for e in soon:
        bj = macro.bj_time(e)
        when = "今天" if e["days"] == 0 else "明天" if e["days"] == 1 else f"{e['days']} 天后"
        hot = e["kind"] in ("CPI", "FOMC", "NFP")
        tag = (f'<span style="background:#fee2e2;color:{UP};border-radius:6px;padding:1px 6px;font-size:12px;margin-left:6px">'
               '波动通常较大</span>') if hot else ""
        st.markdown(_box(
            f'<div style="display:flex;gap:14px;align-items:flex-start">'
            f'<div style="min-width:64px;text-align:center;border-right:1px solid #e5e7eb;padding-right:12px">'
            f'<div style="font-size:12px;color:{MUTED}">北京时间</div>'
            f'<div style="font-size:20px;font-weight:700">{bj:%m/%d}</div>'
            f'<div style="font-size:12px;color:{MUTED}">周{macro.WEEKDAY[bj.weekday()]} {bj:%H:%M}</div></div>'
            f'<div><div style="font-weight:700">{e["name"]}{tag}</div>'
            f'<div style="font-size:13px;color:{MUTED}">{when} · {macro.ref_cn(e)}</div>'
            f'<div style="font-size:14px;margin-top:4px">{e["why"]}</div></div></div>'), unsafe_allow_html=True)
    st.caption("数据公布前后，纳指一天涨跌 1–2% 很常见。定投照常，不需要熬夜盯盘。日期来自美国劳工统计局、经济分析局和美联储官网。")
    with st.expander("查看全部日程"):
        rows = [{"美东日期": e["date"], "事件": e["name"], "说明": macro.ref_cn(e)} for e in cal if not e["past"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, height=300)


# ---------------------------------------------------------------- ③ 利率
def _rates():
    y, eco = _yields(), _economy()
    last, week = y.iloc[-1], y.iloc[-6] if len(y) > 6 else y.iloc[0]
    a, b, c = st.columns(3)
    a.markdown(_card("美联储基准利率", f"{eco['fed_lower']:.2f}–{eco['fed_upper']:.2f}%", "美联储直接决定，最短期的“钱价”"),
               unsafe_allow_html=True)
    for col, key, label, note in ((b, "10Y", "10 年期美债", "影响房贷和股票估值"), (c, "30Y", "30 年期美债", "最长期的借钱成本")):
        d = (last[key] - week[key]) * 100
        col.markdown(_card(label, f"{last[key]:.2f}%", f"比一周前{'升' if d >= 0 else '降'} {abs(d):.0f} 个基点 · {note}",
                           UP if d >= 15 else None), unsafe_allow_html=True)
    q = _qqqm()
    yy = y.loc[y.index >= q.index[0]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=yy.index, y=yy["10Y"], name="10 年期美债收益率（左轴，%）", line=dict(color=UP, width=2)))
    fig.add_trace(go.Scatter(x=q.index, y=q, name="QQQM 价格（右轴，美元）", line=dict(color="#9ca3af", width=2), yaxis="y2"))
    fig.update_layout(height=320, margin=dict(t=30, b=10, l=10, r=10), hovermode="x unified",
                      legend=dict(orientation="h", y=1.15), yaxis=dict(title=None, ticksuffix="%"),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False, tickprefix="$"))
    st.plotly_chart(fig, config={"displayModeBar": False})
    inverted = last["2Y"] > last["10Y"]
    st.caption("看图方法：红线（利率）快速往上走的时候，灰线（纳指）常常会承压；但不是每次都这样，盈利增长更强时纳指也能扛住。"
               f"现在 2 年期 {last['2Y']:.2f}%、10 年期 {last['10Y']:.2f}%，"
               + ("短期利率高于长期，叫“收益率曲线倒挂”，历史上常出现在经济放缓之前。" if inverted
                  else "长期利率高于短期，属于正常形态。"))
    _explain("这些利率是什么？跟我有什么关系？",
             "- **美联储基准利率**：美联储开会决定的利率，相当于全世界“钱的价格”的起点。它下降时，你账户里美元现金的利息也会下降。\n"
             "- **10 年期美债收益率**：借钱给美国政府 10 年能拿到的年回报，被看作“无风险收益”。它越高，股票就要越便宜才有吸引力。\n"
             "- **1 个基点 = 0.01%**。一周上升 20 个基点（0.2%）以上就算比较快了。\n"
             "- **对你的影响**：利率上升时纳指可能短期下跌，但定投就是要在下跌时多买到一些份额，不需要因此停止定投。")


# ---------------------------------------------------------------- ④ 通胀和就业
def _economy_box():
    e = _economy()
    def arrow(cur, prev):
        return "↑" if cur > prev + 0.05 else "↓" if cur < prev - 0.05 else "→"
    a, b = st.columns(2)
    for col, key, label, target in ((a, "cpi", "CPI 通胀（全部商品）", "目标约 2%"),
                                    (b, "core_pce", "核心 PCE（美联储最看重）", "目标 2%")):
        v = e[key]
        col.markdown(_card(f"{label} · {v['month']}", f"{v['value']:.1f}% {arrow(v['value'], v['prev'])}",
                           f"上期 {v['prev']:.1f}% · {target}", "#d97706" if v["value"] > 2.5 else None),
                     unsafe_allow_html=True)
    c, d = st.columns(2)
    u, p = e["unemployment"], e["payrolls"]
    c.markdown(_card(f"失业率 · {u['month']}", f"{u['value']:.1f}% {arrow(u['value'], u['prev'])}", f"上期 {u['prev']:.1f}%"),
               unsafe_allow_html=True)
    d.markdown(_card(f"新增就业 · {p['month']}", f"{p['value'] / 10:+.1f} 万", f"近三个月平均 {p['avg3'] / 10:+.1f} 万人/月"),
               unsafe_allow_html=True)
    hot = e["core_pce"]["value"] > 2.5
    cooling = u["value"] > u["prev"] or p["avg3"] < 100
    if hot and cooling:
        text = "通胀还高于目标，但就业在降温。美联储处在“想降息又怕通胀”的两难里，数据公布前后市场容易大幅波动。"
    elif hot:
        text = "通胀高于目标、就业还不错，美联储降息会比较谨慎，利率可能维持在较高水平。"
    elif cooling:
        text = "通胀接近目标、就业在降温，市场会期待美联储降息；但如果降温太快，又会担心经济衰退。"
    else:
        text = "通胀接近目标、就业稳定，属于比较理想的“软着陆”状态。"
    st.markdown(_box(f"<b>一句话总结：</b>{text}"), unsafe_allow_html=True)
    _explain("怎么看这四个数字？",
             "- **通胀**：物价比去年贵了多少。美联储希望在 2% 左右，太高就不愿降息。\n"
             "- **核心 PCE**：去掉波动大的食品和能源，美联储定利率主要看它。\n"
             "- **失业率和新增就业**：反映经济冷热。就业太强可能推高通胀，太弱说明经济在放缓。\n"
             "- 数据来自美联储经济数据库（FRED），每月更新一次。")


# ---------------------------------------------------------------- ⑤ AI 产业链地图
def _chain_box():
    df = _chain()
    period = st.radio("看哪段时间的涨跌", ["1日", "1月", "今年"], index=1, horizontal=True, key="chain_period")
    cap = {"1日": 0.04, "1月": 0.2, "今年": 0.8}[period]
    for i, (stage, desc, _) in enumerate(macro.CHAIN):
        part = df[df["环节"] == stage]
        if part.empty:
            continue
        avg = part[period].mean()
        chips = ""
        for _, r in part.iterrows():
            v = r[period]
            if pd.isna(v):
                continue
            alpha = min(abs(v) / cap, 1) * 0.85 + 0.1
            bg = f"rgba(214,39,40,{alpha:.2f})" if v >= 0 else f"rgba(22,163,74,{alpha:.2f})"
            fg = "#fff" if alpha > 0.45 else "#111"
            chips += (f'<div style="background:{bg};color:{fg};border-radius:8px;padding:6px 8px;min-width:76px;text-align:center">'
                      f'<div style="font-size:13px;font-weight:600">{html.escape(r["名称"])}</div>'
                      f'<div style="font-size:12px">{r["代码"]} {v:+.0%}</div></div>')
        st.markdown(_box(
            f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
            f'<b>{i + 1}. {stage}</b><span style="color:{UP if avg >= 0 else DOWN};font-size:13px">平均 {avg:+.1%}</span></div>'
            f'<div style="font-size:13px;color:{MUTED};margin:2px 0 8px">{desc}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:6px">{chips}</div>'), unsafe_allow_html=True)
        if i < len(macro.CHAIN) - 1:
            st.markdown(f'<div style="text-align:center;color:{MUTED};margin:-4px 0">↓</div>', unsafe_allow_html=True)
    st.caption("颜色越深涨跌越大（红涨绿跌）。微软、英伟达、博通、美光等很多家就在你买的 QQQM 里。"
               "这张图帮你理解“钱沿着产业链怎么流动”，不是推荐股票；越靠下游的细分环节，波动通常越大。")


# ---------------------------------------------------------------- ⑥ 13F
CN = {"APPLE": "苹果", "AMERICAN EXPRESS": "美国运通", "COCA COLA": "可口可乐", "ALPHABET": "谷歌（Alphabet）",
      "BANK OF AMER": "美国银行", "CHEVRON": "雪佛龙", "OCCIDENTAL": "西方石油", "CHUBB": "安达保险", "MOODYS": "穆迪",
      "KRAFT HEINZ": "卡夫亨氏", "AMAZON": "亚马逊", "MICROSOFT": "微软", "UBER": "优步", "BROOKFIELD": "布鲁克菲尔德",
      "RESTAURANT BRANDS": "餐饮品牌国际（汉堡王母公司）", "HILTON": "希尔顿", "CHIPOTLE": "Chipotle 墨西哥餐厅",
      "NIKE": "耐克", "HOWARD HUGHES": "霍华德·休斯", "NVIDIA": "英伟达", "META PLATFORMS": "Meta",
      "TAIWAN SEMICONDUCTOR": "台积电", "STMICROELECTRONICS": "意法半导体", "NATERA": "Natera（基因检测）",
      "VISTRA": "Vistra（电力）", "TESLA": "特斯拉", "VISA": "Visa", "MASTERCARD": "万事达", "DAVITA": "德维特（透析）",
      "VERISIGN": "威瑞信", "KROGER": "克罗格超市", "SIRIUS": "天狼星卫星广播", "CONSTELLATION BRANDS": "星座品牌（啤酒）",
      "D R HORTON": "霍顿房屋", "LENNAR": "莱纳房屋", "UNITEDHEALTH": "联合健康", "DOMINOS": "达美乐披萨",
      "POOL CORP": "Pool（泳池用品）", "ALLY": "Ally 银行", "CAPITAL ONE": "第一资本", "CITIGROUP": "花旗",
      "AMERICAN ELEC": "美国电力", "COUPANG": "Coupang（韩国电商）", "BROADCOM": "博通", "ORACLE": "甲骨文",
      "MERCADOLIBRE": "美客多", "ELI LILLY": "礼来", "INSMED": "Insmed（生物药）", "YPF": "YPF（阿根廷石油）"}


def _cn(name):
    up = name.upper().replace(".", "").replace("'", "")
    hit = next((v for k, v in CN.items() if up.startswith(k)), None)
    return f"{hit} · {name.title()}" if hit else name.title()


def _f13_box():
    data = _13f()
    if not data:
        st.info("持仓报告暂时获取失败。")
        return
    names = [m["manager"] for m in data]
    pick = st.selectbox("选择基金经理", names, key="f13_pick")
    m = data[names.index(pick)]
    filed = pd.Timestamp(m["filed"])
    st.caption(f"截至 {m['report']} 的持仓，{m['filed']} 公开（已经过去 {(pd.Timestamp.now() - filed).days} 天）。"
               f"申报的美股持仓合计约 {m['total'] / 1e8:,.0f} 亿美元。")
    rows = m["rows"]
    top = [r for r in rows if r["value"] > 0][:10]

    def change(c):
        color = UP if c == "新买入" or c.startswith("+") else DOWN if c == "清仓" or c.startswith("-") else MUTED
        return f'<span style="color:{color}">{c}</span>'
    table = "".join(f'<tr><td>{html.escape(_cn(r["name"]))}</td><td style="text-align:right">{r["weight"]:.1%}</td>'
                    f'<td style="text-align:right">{change(r["change"])}</td></tr>' for r in top)
    st.markdown('<table style="width:100%;font-size:14px"><tr><th style="text-align:left">公司</th>'
                '<th style="text-align:right">占比</th><th style="text-align:right">比上季度股数</th></tr>'
                f'{table}</table>', unsafe_allow_html=True)
    new = [_cn(r["name"]) for r in rows if r["change"] == "新买入"][:8]
    gone = [_cn(r["name"]) for r in rows if r["change"] == "清仓"][:8]
    if new:
        st.markdown(f"**新买入：** {html.escape('、'.join(new))}")
    if gone:
        st.markdown(f"**清仓卖出：** {html.escape('、'.join(gone))}")
    st.warning("13F 只能看到 1.5–4.5 个月前的持仓，而且看不到空头和对冲。适合学习大佬的思路，不适合照抄。")
    _explain("13F 是什么？",
             "管理 1 亿美元以上的美国投资机构，每个季度结束后 45 天内必须向美国证监会（SEC）公开美股持仓，这份文件叫 13F。"
             "巴菲特的伯克希尔、彼得·蒂尔、德鲁肯米勒、阿克曼都会定期申报。数据直接来自 SEC 官网。")


# ---------------------------------------------------------------- ⑦ 每日一课
def _lesson_box():
    l = lessons.today()
    st.markdown(_box(
        f'<div style="color:{MUTED};font-size:13px">第 {l["n"]}/{l["total"]} 课 · {l["topic"]}</div>'
        f'<div style="font-size:20px;font-weight:700;margin:4px 0">{l["title"]}</div>'
        f'<div style="line-height:1.7">{l["body"]}</div>'
        f'<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e5e7eb"><b>和你的关系：</b>{l["tie"]}</div>'),
        unsafe_allow_html=True)
    with st.expander("全部课程"):
        for i, (topic, title, body, tie) in enumerate(lessons.LESSONS, 1):
            st.markdown(f"**{i}. {title}**（{topic}）  \n{body}  \n*和你的关系：{tie}*")


def render(learn_only=False):
    st.markdown("这一页帮你看懂**市场为什么这样动**：利率、通胀、产业链和大资金在想什么。"
                "内容只用于学习和理解，**不是买卖建议**；你的定投计划不需要因此改变。")
    sections = [("今日信号", _signal, "信号"), ("今天为什么涨跌", _today, "涨跌解读"), ("接下来的大事", _events, "宏观日历"),
                ("每日一课", _lesson_box, "课程"), ("利率：钱的价格", _rates, "利率数据"), ("通胀和就业", _economy_box, "经济数据"),
                ("AI 产业链地图", _chain_box, "产业链行情"), ("大佬在买什么（13F 持仓）", _f13_box, "持仓报告")]
    origins = {"今天为什么涨跌": "today_why", "接下来的大事": "events", "利率：钱的价格": "rates", "通胀和就业": "economy",
               "AI 产业链地图": "chain", "大佬在买什么（13F 持仓）": "f13"}
    if learn_only:
        sections = [x for x in sections if x[0] not in ("今日信号", "今天为什么涨跌")]
    for i, (title, fn, what) in enumerate(sections):
        st.subheader(f"{'①②③④⑤⑥⑦⑧'[i]} {title}")
        if title in origins:
            ui.origin(origins[title])
        _safe(fn, what)

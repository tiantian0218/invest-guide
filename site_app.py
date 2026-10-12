"""公开网站：美股指数定投入门 + 行情 + 计算器 + 选股参考。不读取任何个人账户数据。

本地预览：.venv/bin/streamlit run site_app.py --server.port 8502
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import invest
import market_data
import signals

ROOT = Path(__file__).resolve().parent
GUIDE = ROOT / "public" / "美股定投入门手册.md"
PDF = ROOT / "public" / "美股定投入门手册.pdf"

st.set_page_config(page_title="美股指数定投入门", page_icon="📈", layout="centered")
UP, DOWN = "#d62728", "#16a34a"


@st.cache_data(ttl=86400, show_spinner="正在下载历史行情（首次约 1 分钟）…")
def history():
    return invest.history(["QQQ", "SPY"])


@st.cache_data(ttl=900, show_spinner=False)
def _recent():
    d, _ = market_data.closes(["QQQM", "SPYM"], "2y")
    if any(t not in d or d[t].dropna().size < 260 for t in ("QQQM", "SPYM")):
        raise RuntimeError("incomplete download")
    return d.ffill()


def recent():
    for _ in range(3):
        try:
            return _recent()
        except RuntimeError:
            continue
    raise RuntimeError("行情下载失败")


@st.cache_data(ttl=900, show_spinner=False)
def gauges():
    return signals.market_gauges()


@st.cache_data(ttl=86400, show_spinner=False)
def vix_10y():
    d = invest.yf.download("^VIX", period="10y", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
    return d if len(d) > 252 else None


def signed(x, fmt="+.2f", unit="%"):
    return f'<span style="color:{UP if x >= 0 else DOWN}">{format(x, fmt)}{unit}</span>'


st.title("美股指数定投入门")
st.caption("用最低的成本，买下美国最大的几百家公司，然后交给时间。所有数据来自真实历史行情；历史不代表未来，不构成投资建议。")

tab_guide, tab_market, tab_calc, tab_hist, tab_pick = st.tabs(["入门手册", "今日市场", "定投计算器", "历史数据", "选股参考"])

# ---------------------------------------------------------------- 入门手册
with tab_guide:
    if PDF.exists():
        st.download_button("下载 PDF 版", PDF.read_bytes(), file_name="美股定投入门手册.pdf", mime="application/pdf")
    st.markdown(GUIDE.read_text(encoding="utf-8"))

# ---------------------------------------------------------------- 今日市场
def market_tab():
    try:
        d = recent()
        q = signals.indicators(d["QQQM"].dropna())
        s = signals.indicators(d["SPYM"].dropna())
    except Exception:
        st.warning("行情接口暂时不稳定，请过 1 分钟刷新页面。")
        return
    c1, c2 = st.columns(2)
    for col, name, ind in ((c1, "纳斯达克 100（QQQM）", q), (c2, "标普 500（SPYM）", s)):
        col.metric(name, f"${ind['price']:.2f}", f"{ind['chg_1d'] * 100:+.2f}%", delta_color="inverse")
        col.markdown(f"今年 {signed(ind['chg_ytd'] * 100, '+.1f')} · 距一年高点 {ind['from_high'] * 100:.1f}%",
                     unsafe_allow_html=True)
    st.caption("颜色按 A 股习惯：红涨绿跌。")
    try:
        temp, label, parts = signals.market_temperature(history()["QQQ"], vix_10y())
        meaning = {"冰冷": "市场很恐慌、跌得很深", "偏冷": "市场在回调", "正常": "不冷不热",
                   "偏热": "最近涨得多，处于过去 10 年偏高位置", "过热": "涨得很猛，回调概率变高"}[label]
        st.markdown(
            f'<div style="padding:14px 16px;border-radius:12px;background:#f9fafb;margin:12px 0">'
            f'<div style="color:#6b7280">市场温度（纳指 100，过去 10 年里的位置）</div>'
            f'<div style="font-size:30px;font-weight:800">{temp}° {label}</div>'
            f'<div style="position:relative;height:12px;border-radius:6px;margin:8px 0;'
            f'background:linear-gradient(90deg,#2563eb,#93c5fd,#e5e7eb,#fca5a5,#dc2626)">'
            f'<div style="position:absolute;left:calc({temp}% - 2px);top:-4px;width:4px;height:20px;background:#111"></div></div>'
            f'<div>{meaning}。<b>对定投的影响：没有</b>，定投日照常买。</div></div>', unsafe_allow_html=True)
        with st.expander("温度是怎么算的"):
            st.markdown("由四项指标在过去 10 年里的百分位平均得到：" + "；".join(f"{k} {v:.0f}" for k, v in parts.items())
                        + "。温度只描述冷热，回测显示据此择时并不能提高收益。")
    except Exception:
        pass
    try:
        vix, tnx = gauges()
    except Exception:
        vix = tnx = None
    if vix and tnx:
        st.markdown(f"- **VIX 恐慌指数** {vix:.1f}（20 以下算平静，30 以上算恐慌）\n- **美国 10 年期国债收益率** {tnx:.2f}%（越高，股票估值压力越大）")


with tab_market:
    market_tab()

# ---------------------------------------------------------------- 定投计算器
with tab_calc:
    st.markdown("按 1999 年以来的真实月度行情，把**所有可能的起点**都算一遍，看看结果的范围。")
    c1, c2 = st.columns(2)
    init = c1.number_input("现在一次性投入（元）", 0, 10_000_000, 10_000, step=5_000)
    monthly = c2.number_input("每月定投（元）", 0, 1_000_000, 2_000, step=500)
    years = c1.slider("投多少年", 1, 20, 5)
    w = c2.slider("纳指 100 占比（其余为标普 500）", 0, 100, 70, step=10) / 100
    px = history()
    m = px.resample("ME").last()
    r = (w * m["QQQ"].pct_change() + (1 - w) * m["SPY"].pct_change()).dropna().values
    H = years * 12
    if H >= len(r):
        st.warning("年数超过了历史数据长度。")
    else:
        res = []
        for start in range(len(r) - H):
            v = init
            for k in range(H):
                v = v * (1 + r[start + k]) + monthly
            res.append(v)
        res = np.array(res)
        inv = init + monthly * H
        p10, p50, p90 = np.percentile(res, [10, 50, 90])
        st.markdown(f"**总投入 ¥{inv:,.0f}**，{len(res)} 个历史起点的结果：")
        t = pd.DataFrame({"情形": ["差的情况（10 次里最差的 1 次）", "一般情况（中位数）", "好的情况（10 次里最好的 1 次）", "历史最差"],
                          "最后变成": [p10, p50, p90, res.min()]})
        t["赚/亏"] = t["最后变成"] - inv
        t["最后变成"] = t["最后变成"].map(lambda x: f"¥{x:,.0f}")
        t["赚/亏"] = t["赚/亏"].map(lambda x: f"{'+' if x >= 0 else '−'}¥{abs(x):,.0f}")
        st.table(t.set_index("情形"))
        st.markdown(f"- 结果**亏钱的比例：{(res < inv).mean() * 100:.0f}%**\n"
                    "- 投多投少只改变金额，不改变收益率；时间越长，亏钱的比例越低。\n"
                    "- 纳指 100 是过去 15 年表现最好的指数之一，未来收益大概率会低一些。")
        fig = go.Figure(go.Histogram(x=res / 10_000, nbinsx=50, marker_color="#1e78dc"))
        fig.add_vline(x=inv / 10_000, line=dict(color=UP, dash="dash"), annotation_text="总投入")
        fig.update_layout(title="所有历史起点的结果分布（万元）", height=300, margin=dict(t=40, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- 历史数据
with tab_hist:
    px = history()
    start = st.selectbox("从哪年开始看", list(range(1999, pd.Timestamp.today().year)), index=11)
    sub = px[px.index >= f"{start}-01-01"]
    growth = sub / sub.iloc[0] * 10_000
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=growth.index, y=growth["QQQ"], name="纳斯达克 100"))
    fig.add_trace(go.Scatter(x=growth.index, y=growth["SPY"], name="标普 500"))
    fig.update_layout(title=f"{start} 年初投入 1 万美元，之后的价值（含分红）", height=360, hovermode="x unified",
                      margin=dict(t=50), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, use_container_width=True)
    dd = sub / sub.cummax() - 1
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd.index, y=dd["QQQ"] * 100, name="纳斯达克 100", fill="tozeroy"))
    fig.add_trace(go.Scatter(x=dd.index, y=dd["SPY"] * 100, name="标普 500"))
    fig.update_layout(title="从最高点跌了多少（%）", height=280, hovermode="x unified", margin=dict(t=50),
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("纳指 100 历史最大跌幅 −83%（2000→2002），花了约 15 年才回到前高；标普 500 最大跌幅约 −55%（2007→2009）。")

# ---------------------------------------------------------------- 选股参考
with tab_pick:
    st.info("**核心 + 卫星**：大部分钱定投指数（核心）；个股（卫星）合计最多占总资产 15%，单只最多 5%；"
            "跌 25% 或跌破 200 日均线就卖。下表是规则筛出的“近期强势且赚钱的公司”，**不是推荐，更不是稳赚名单**。")
    f = ROOT / "data" / "screener.csv"
    if not f.exists():
        st.warning("暂时没有筛选结果。")
    else:
        res = pd.read_csv(f)
        st.caption(f"范围：标普 500 + 纳指 100 · 结果日期 {res['date'].iloc[0]} · 每月更新")
        for i, row in res.iterrows():
            st.markdown(f"**{i + 1}. {row['ticker']}** {row['name']} · ${row['price']:,.2f}  \n"
                        f"<span style='font-size:14px'>{row['why']}</span>  \n"
                        f"<span style='color:{UP};font-size:13px'>风险：{row['risk']}</span>", unsafe_allow_html=True)
        st.markdown("**筛选规则**：股价在 200 日均线之上；过去 12 个月（剔除最近 1 个月）涨幅靠前；公司盈利；"
                    "≥5 位分析师覆盖。综合分 = 动量 50% + 利润率 25% + 分析师目标价空间 25%。")

st.divider()
st.caption("本网站只提供信息和计算工具，不构成投资建议，不代客理财、不带单、不收取任何费用。"
           "请不要把银行账号和密码告诉任何人。")

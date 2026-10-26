"""公开网站：美股指数定投入门 + 行情 + 计算器 + 选股参考。不读取任何个人账户数据。

本地预览：.venv/bin/streamlit run site_app.py --server.port 8502
"""
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import cloud_api
import invest
import lessons
import macro
import market_data
import signals
import site_account
import site_lab
import site_macro
import site_today
import site_ui

# Streamlit Cloud 拉到新代码后只重新执行本文件，已导入的本地模块会一直是旧版，直到应用重启。
for _mod in (market_data, signals, invest, cloud_api, macro, lessons, site_ui, site_account, site_macro, site_today,
             site_lab):
    _mtime = Path(_mod.__file__).stat().st_mtime
    if getattr(_mod, "_loaded_mtime", None) != _mtime:
        importlib.reload(_mod)._loaded_mtime = _mtime

ROOT = Path(__file__).resolve().parent
GUIDE = ROOT / "public" / "美股定投入门手册.md"
PDF = ROOT / "public" / "美股定投入门手册.pdf"

st.set_page_config(page_title="美股指数定投入门 · 天天", page_icon="📈", layout="centered")
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


site_ui.css()
site_ui.brand("美股指数定投入门", "低成本买下美国最大的几百家公司，然后交给时间")

SESSION = site_account.current_session()
tab_today, tab_acct, tab_ai, tab_learn, tab_tools = st.tabs(["今天", "我的账户", "AI 研究", "看懂市场", "工具箱"])

with tab_today:
    site_today.render(SESSION)

with tab_acct:
    site_account.account_tab(SESSION)

with tab_ai:
    site_account.ai_tab(SESSION if cloud_api.enabled() else None)


# ---------------------------------------------------------------- 入门手册
def guide_tab():
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
        col.markdown(f"**{name}** 今年 {signed(ind['chg_ytd'] * 100, '+.1f')} · 距一年高点 {ind['from_high'] * 100:.1f}%",
                     unsafe_allow_html=True)
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


with tab_learn:
    st.subheader("市场温度")
    market_tab()
    site_macro.render(learn_only=True)


# ---------------------------------------------------------------- 定投计算器
def calc_tab():
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
        site_ui.section(f"{years} 年一共投入 ¥{inv:,.0f}，最后可能变成", f"把 {len(res)} 个历史起点都算了一遍")
        cols = st.columns(3)
        for col, (name, hint, v) in zip(cols, (("差的情况", "10 次里最差的 1 次", p10), ("一般情况", "中位数", p50),
                                              ("好的情况", "10 次里最好的 1 次", p90))):
            gain = v - inv
            col.markdown(site_account._card(f"{name} · {hint}", f"¥{v:,.0f}", site_account._signed(gain, "¥", 0),
                                            UP if gain >= 0 else DOWN), unsafe_allow_html=True)
        lose = (res < inv).mean()
        site_ui.card(f'<div style="font-size:16px">亏钱的概率：<b class="ui-num" style="font-size:22px;color:'
                     f'{DOWN if lose > 0.2 else site_ui.CALM}">{lose:.0%}</b>'
                     f'<span class="ui-note">　历史最差的一次最后变成 ¥{res.min():,.0f}</span></div>')
        st.markdown("- 投多投少只改变金额，不改变收益率；时间越长，亏钱的比例越低（把年数拉到 10 年试试）。\n"
                    "- 纳指 100 是过去 15 年表现最好的指数之一，未来收益大概率会低一些。")
        fig = go.Figure(go.Histogram(x=res / 10_000, nbinsx=50, marker_color="#1e78dc"))
        fig.add_vline(x=inv / 10_000, line=dict(color=UP, dash="dash"), annotation_text="总投入")
        fig.update_layout(title="所有历史起点的结果分布（万元）", height=300, margin=dict(t=40, b=10), showlegend=False)
        st.plotly_chart(fig)

# ---------------------------------------------------------------- 历史数据
def hist_tab():
    px = history()
    start = st.selectbox("从哪年开始看", list(range(1999, pd.Timestamp.today().year)), index=11)
    sub = px[px.index >= f"{start}-01-01"]
    growth = sub / sub.iloc[0] * 10_000
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=growth.index, y=growth["QQQ"], name="纳斯达克 100"))
    fig.add_trace(go.Scatter(x=growth.index, y=growth["SPY"], name="标普 500"))
    fig.update_layout(title=f"{start} 年初投入 1 万美元，之后的价值（含分红）", height=360, hovermode="x unified",
                      margin=dict(t=50), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig)
    dd = sub / sub.cummax() - 1
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd.index, y=dd["QQQ"] * 100, name="纳斯达克 100", fill="tozeroy"))
    fig.add_trace(go.Scatter(x=dd.index, y=dd["SPY"] * 100, name="标普 500"))
    fig.update_layout(title="从最高点跌了多少（%）", height=280, hovermode="x unified", margin=dict(t=50),
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig)
    st.caption("纳指 100 历史最大跌幅 −83%（2000→2002），花了约 15 年才回到前高；标普 500 最大跌幅约 −55%（2007→2009）。")

# ---------------------------------------------------------------- 选股参考
def pick_tab():
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


TOOLS = {"定投计算器": calc_tab, "规则实验室": site_lab.render, "历史数据": hist_tab, "选股参考": pick_tab, "入门手册": guide_tab,
         "功能地图": site_ui.feature_map}
with tab_tools:
    pick = st.segmented_control("工具", list(TOOLS), default="定投计算器", label_visibility="collapsed")
    TOOLS[pick or "定投计算器"]()

st.divider()
st.caption("所有数据来自真实历史行情；历史不代表未来。本网站只提供信息和计算工具，不构成投资建议，"
           "不代客理财、不带单、不收取任何费用。请不要把银行账号和密码告诉任何人。")
st.markdown(f'<div class="ui-sign"><b>天天</b> 做的小工具 · {pd.Timestamp.now(tz="Asia/Shanghai").year}</div>',
            unsafe_allow_html=True)

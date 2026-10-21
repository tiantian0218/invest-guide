"""工具箱「规则实验室」：把网站用到的规则拿历史数据检验一遍，分样本内 / 样本外，并看参数稳不稳。只研究指数，不涉及个股。"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import invest

ROOT = Path(__file__).resolve().parent
UP, DOWN, MUTED = "#d62728", "#16a34a", "#6b7280"
WINDOW = 120
SPLIT_YEAR = 2009
THRESHOLDS = (0.10, 0.15, 0.20, 0.25, 0.30)
KEEPS = (0.1, 0.2, 0.3)
CASH_RATE = 0.025
PORTFOLIOS = {
    "70/30 纳指+标普（你现在的）": {"QQQ": 0.7, "SPY": 0.3},
    "加 20% 长期美债": {"QQQ": 0.56, "SPY": 0.24, "TLT": 0.2},
    "加 10% 美债 + 10% 黄金": {"QQQ": 0.56, "SPY": 0.24, "TLT": 0.1, "GLD": 0.1},
    "只买标普 500": {"SPY": 1.0},
}


@st.cache_data(ttl=86400, show_spinner=False)
def _index():
    px = invest.history(["QQQ", "SPY"])
    ret = (0.7 * px["QQQ"].pct_change() + 0.3 * px["SPY"].pct_change()).fillna(0)
    nav = (1 + ret).cumprod().resample("ME").last()
    dd = (px["QQQ"] / px["QQQ"].rolling(252, min_periods=60).max() - 1).resample("ME").last()
    return nav, dd


@st.cache_data(ttl=86400, show_spinner="正在回测加码规则…")
def dip_grid():
    """每月预算 1：普通定投每月全投；加码规则每月留 keep 作现金（年息 2.5%），纳指距一年高点跌超 th 时一次投完。"""
    nav, dd = _index()
    mr = (1 + CASH_RATE) ** (1 / 12) - 1
    rows = []
    for keep in KEEPS:
        for th in THRESHOLDS:
            for i in range(len(nav) - WINDOW):
                n = nav.iloc[i:i + WINDOW + 1].values
                d = dd.iloc[i:i + WINDOW].values
                plain = (1 / n[:-1]).sum() * n[-1]
                units = res = 0.0
                for k in range(WINDOW):
                    res = res * (1 + mr) + keep
                    units += (1 - keep) / n[k]
                    if d[k] <= -th:
                        units, res = units + res / n[k], 0.0
                rows.append({"keep": keep, "th": th, "year": nav.index[i].year,
                             "excess": (units * n[-1] + res) / plain - 1})
    return pd.DataFrame(rows)


@st.cache_data(ttl=86400, show_spinner=False)
def portfolio_stats():
    px = pd.read_csv(ROOT / "data" / "hist_lab.csv", index_col=0, parse_dates=True).dropna()
    ret = px.pct_change().dropna()
    out, curves = [], {}
    for name, w in PORTFOLIOS.items():
        for rebalance in (True, False):
            if rebalance:
                m = (1 + ret).resample("ME").prod() - 1
                r = sum(m[t] * x for t, x in w.items())
                nav = (1 + r).cumprod()
                dnav = (1 + ret[list(w)].mul(pd.Series(w)).sum(axis=1)).cumprod()
            else:
                dnav = sum((px[t] / px[t].iloc[0]) * x for t, x in w.items())
                nav = dnav.resample("ME").last()
            years = (dnav.index[-1] - dnav.index[0]).days / 365.25
            cagr = float(dnav.iloc[-1] / dnav.iloc[0]) ** (1 / years) - 1
            mdd = float((dnav / dnav.cummax() - 1).min())
            yearly = dnav.resample("YE").last().pct_change().dropna()
            y2008 = float(dnav["2008"].iloc[-1] / dnav[:"2007"].iloc[-1] - 1)
            y2022 = float(dnav["2022"].iloc[-1] / dnav[:"2021"].iloc[-1] - 1)
            out.append({"组合": name, "再平衡": "定期" if rebalance else "不调整", "年化": cagr, "最大回撤": mdd,
                        "最差一年": float(yearly.min()), "2008 年": y2008, "2022 年": y2022,
                        "回撤性价比": cagr / abs(mdd)})
            if rebalance:
                curves[name] = dnav / dnav.iloc[0] * 10_000
    corr = ret.corr()
    return pd.DataFrame(out), curves, corr, (px.index[0], px.index[-1])


def _pct(x, digits=1):
    return f"{x:+.{digits}%}"


def _dip_section():
    st.markdown("**问题：** 平时留一部分钱不投，等纳指大跌（距一年高点跌超某个幅度）再一次性买入，会不会比每月按时全投更好？"
                "很多人的直觉是“会”。")
    g = dip_grid()
    table = (g.groupby(["keep", "th"])["excess"].mean().unstack("th") * 100).round(1)
    table.index = [f"每月留 {k:.0%}" for k in table.index]
    table.columns = [f"跌 {t:.0%} 才买" for t in table.columns]
    fig = go.Figure(go.Heatmap(z=table.values, x=list(table.columns), y=list(table.index), colorscale=[[0, DOWN], [0.5, "#f3f4f6"], [1, UP]],
                               zmid=0, text=[[f"{v:+.1f}%" for v in row] for row in table.values], texttemplate="%{text}",
                               hovertemplate="%{y} · %{x}<br>比按时全投 %{z:+.1f}%<extra></extra>", showscale=False))
    fig.update_layout(height=230, margin=dict(l=0, r=0, t=30, b=0),
                      title=dict(text="10 年后比“每月按时全投”多 / 少多少（所有起点平均）", font=dict(size=14)))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    base = g[(g.keep == 0.2) & (g.th == 0.2)]
    ins, oos = base[base.year < SPLIT_YEAR], base[base.year >= SPLIT_YEAR]
    worst = g.groupby(["keep", "th"])["excess"].mean().max()
    st.markdown(
        f"- **15 种参数组合全部跑输**，最好的一组也是 {_pct(worst)}。等待期间现金按年息 2.5% 计，已经算得很宽松。\n"
        f"- 用最常见的“每月留 20%、跌 20% 才买”来看：{SPLIT_YEAR} 年以前起步的窗口平均 {_pct(ins.excess.mean())}，"
        f"{SPLIT_YEAR} 年以后起步的窗口（相当于样本外检验）平均 {_pct(oos.excess.mean())}，赢的比例 {(oos.excess > 0).mean():.0%}。\n"
        "- 原因：股市大部分时间在涨，攒着等大跌的钱错过了这些上涨；真正的大跌又很少，等到了也补不回来。")
    st.success("**结论（已经改进到信号里）：** 有钱就按计划投，不要攒着等大跌。大跌时最重要的是**照常定投、不要停**；"
               "如果手头有本来不打算投资的工资结余，大跌时可以多投一些，但这只是锦上添花。")


def _diversify_section():
    df, curves, corr, (a, b) = portfolio_stats()
    st.markdown(f"**问题：** 纳指和标普 500 走势很像（每天涨跌的相关系数约 {corr.loc['QQQ', 'SPY']:.2f}，1 代表完全同步），"
                "所以 70/30 其实分散得不多。再加一种和股票关系不大的资产（长期美债、黄金），会怎样？"
                f"数据区间 {a:%Y-%m} 至 {b:%Y-%m}。")
    view = df[df["再平衡"] == "定期"].drop(columns="再平衡").copy()
    for c in ("年化", "最大回撤", "最差一年", "2008 年", "2022 年"):
        view[c] = view[c].map(lambda x: f"{x:+.1%}")
    view["回撤性价比"] = view["回撤性价比"].map(lambda x: f"{x:.2f}")
    st.dataframe(view, hide_index=True, width="stretch")
    fig = go.Figure()
    for name, c in curves.items():
        fig.add_scatter(x=c.index, y=c.values, name=name, line=dict(width=2.5 if "现在" in name else 1.5))
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0), hovermode="x unified", yaxis=dict(type="log", tickprefix="$"),
                      title=dict(text="1 万美元定期再平衡后的走势（对数坐标）", font=dict(size=14)), legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    nb = df[(df["组合"] == list(PORTFOLIOS)[1])]
    gain = float(nb[nb["再平衡"] == "定期"]["年化"].iloc[0] - nb[nb["再平衡"] == "不调整"]["年化"].iloc[0])
    st.markdown(
        f"- 股票和长期美债的相关系数约 {corr.loc['SPY', 'TLT']:.2f}，黄金约 {corr.loc['SPY', 'GLD']:.2f}，都远低于纳指和标普之间的关系，"
        "所以加进去后**最大回撤明显变小**，代价是年化收益也低一些。\n"
        "- **2022 年是例外**：那年利率暴涨，股票和债券一起跌，分散几乎失效。低相关不等于永远负相关。\n"
        f"- **定期再平衡**（涨多的卖一点、跌多的补一点）对加债组合的年化影响约 {gain:+.2%}，更大的作用是把风险维持在设定水平。"
        "定投时把新钱优先买低于目标比例的那只，就能顺带完成再平衡，不用卖。")
    st.info("这部分是研究，不是建议。如果钱是十年以上不用的闲钱、也拿得住大跌，全股票是合理选择；"
            "如果看了「今天」页的风险预期，觉得跌一半会忍不住卖，再考虑加入债券。")


def _pitfalls():
    st.markdown(
        "看到“年化 17%、最大回撤只有 −3%”这种回测，先用这四条检查：\n\n"
        "1. **过度拟合**：参数调得越细，越像在背历史答案。好规则在一大片参数范围内都有效，而不是只在某个精确数字上有效。"
        "→ 上面的加码检验列出了 15 组参数，而不是只挑最好的一组。\n"
        "2. **没有样本外检验**：只用一段历史调参再用同一段验证，等于开卷考试。→ 我们把 2009 年前后分开看。\n"
        "3. **忽略成交成本和真实成交**：回测默认想买就能按收盘价买到。→「假如照做了」按你的真实佣金率扣成本。\n"
        "4. **幸存者偏差和偷看未来**：只用今天还活着的股票、或者在公告前就用了财报数据，回测会好得不真实。"
        "→ 我们只研究指数，信号只用当天以前的数据。\n\n"
        "另外，四五年的回测哪怕“每年都赚钱”，也可能只是碰上了合适的行情，不能说明没有过拟合。")


def render():
    st.markdown("网站给出的每条规则，都应该先经得起历史数据的检验。这一页把检验过程摊开给你看。")
    st.subheader("① 大跌加码：攒钱等大跌划算吗")
    _dip_section()
    st.subheader("② 分散：加一点不跟股市走的资产会怎样")
    _diversify_section()
    st.subheader("③ 看懂回测的四个陷阱")
    _pitfalls()

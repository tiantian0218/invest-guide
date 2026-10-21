"""网站的统一样式：颜色、字号、卡片、标签。所有页面都从这里取，保证看起来是一个整体。"""
import html

import pandas as pd
import streamlit as st

INK, MUTED, FAINT, LINE, SURFACE = "#18223a", "#64748b", "#94a3b8", "#e6e9f0", "#f4f6fa"
UP, DOWN = "#d62728", "#16a34a"
CALM, ACT, WARN = "#0e7c66", "#1d4ed8", "#c2410c"
WEEKDAYS = "一二三四五六日"

CSS = f"""
<style>
[data-testid="stMainBlockContainer"] {{ padding-top: 1.6rem; padding-bottom: 3rem; }}
[data-testid="stToolbar"], header[data-testid="stHeader"] {{ display: none; }}
.stApp {{ color: {INK}; }}
.stApp [data-baseweb="tab-list"] {{ position: sticky; top: 0; z-index: 50; background: #fff; gap: 4px; }}
.stApp button[data-baseweb="tab"] {{ padding: 10px 14px; }}
.stApp button[data-baseweb="tab"] p {{ font-size: 17px; font-weight: 600; }}
.ui-num {{ font-variant-numeric: tabular-nums; }}
.ui-brand {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 2px; }}
.ui-brand b {{ font-size: 24px; letter-spacing: .5px; }}
.ui-brand span {{ color: {MUTED}; font-size: 14px; }}
.ui-sec {{ margin: 28px 0 10px; }}
.ui-sec b {{ font-size: 19px; }}
.ui-sec span {{ display: block; color: {MUTED}; font-size: 13px; margin-top: 2px; }}
.ui-card {{ padding: 14px 16px; border-radius: 14px; background: {SURFACE}; margin: 6px 0; }}
.ui-chip {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 13px; margin: 0 6px 6px 0;
           background: #fff; border: 1px solid {LINE}; color: {INK}; white-space: nowrap; }}
.ui-day {{ display: flex; gap: 18px; padding: 18px 18px 12px; border-radius: 16px; background: #fff;
          border: 1px solid {LINE}; box-shadow: 0 1px 2px rgba(24,34,58,.05); margin: 8px 0 4px; }}
.ui-day .date {{ min-width: 64px; text-align: center; border-right: 1px dashed {LINE}; padding-right: 16px; }}
.ui-day .date .m {{ font-size: 13px; color: {MUTED}; }}
.ui-day .date .d {{ font-size: 44px; font-weight: 800; line-height: 1.05; }}
.ui-day .date .w {{ font-size: 13px; color: {MUTED}; }}
.ui-day .verdict {{ font-size: 26px; font-weight: 800; line-height: 1.3; }}
.ui-day .why {{ font-size: 15px; line-height: 1.6; margin: 6px 0 10px; }}
.ui-row {{ display: flex; gap: 10px; align-items: flex-start; padding: 11px 0; border-top: 1px solid {LINE}; }}
.ui-row:first-child {{ border-top: none; }}
.ui-tag {{ color: #fff; border-radius: 6px; padding: 2px 8px; font-weight: 700; font-size: 14px; white-space: nowrap; }}
.ui-note {{ font-size: 13px; color: {MUTED}; line-height: 1.6; }}
.ui-ask {{ border-left: 3px solid {WARN}; padding: 8px 12px; background: #fff7ed; border-radius: 0 10px 10px 0;
          font-size: 14px; line-height: 1.6; margin: 8px 0; }}
table.ui-table {{ width: 100%; border-collapse: collapse; font-size: 14px; border: none; }}
table.ui-table th {{ text-align: left; color: {MUTED}; font-weight: 500; font-size: 13px; border: none;
                    border-bottom: 1px solid {LINE}; padding: 6px 8px; white-space: nowrap; }}
table.ui-table td {{ border: none; border-bottom: 1px solid {LINE}; padding: 8px; vertical-align: top; }}
[data-testid="stExpander"] summary p {{ font-weight: 600; }}
.stApp [data-testid="stHeadingWithActionElements"] h3 {{ font-size: 20px; font-weight: 700; padding-top: 18px; }}
.stApp [data-testid="stHeadingWithActionElements"] h2 {{ font-size: 22px; font-weight: 700; }}
@media (max-width: 640px) {{
  .ui-day {{ gap: 12px; padding: 14px 12px 8px; }}
  .ui-day .date {{ min-width: 48px; padding-right: 10px; }}
  .ui-day .date .d {{ font-size: 34px; }}
  .ui-day .verdict {{ font-size: 21px; }}
}}
</style>
"""


def css():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x):
    return html.escape(str(x))


def brand(title, tagline):
    st.markdown(f'<div class="ui-brand"><b>{esc(title)}</b><span>{esc(tagline)}</span></div>', unsafe_allow_html=True)


def section(title, hint=None):
    st.markdown(f'<div class="ui-sec"><b>{esc(title)}</b>{f"<span>{esc(hint)}</span>" if hint else ""}</div>',
                unsafe_allow_html=True)


def move(x, digits=2):
    """涨跌幅：红涨绿跌，并加箭头，不只靠颜色。"""
    if x is None:
        return "—"
    color, arrow = (UP, "↑") if x >= 0 else (DOWN, "↓")
    return f'<span class="ui-num" style="color:{color}">{arrow}{abs(x):.{digits}%}</span>'


def chip(text):
    return f'<span class="ui-chip">{text}</span>'


def tag(text, color):
    return f'<span class="ui-tag" style="background:{color}">{esc(text)}</span>'


def day_card(verdict, why, tone, chips=(), extra=""):
    now = pd.Timestamp.now(tz="Asia/Shanghai")
    st.markdown(
        f'<div class="ui-day" style="border-top:5px solid {tone}">'
        f'<div class="date"><div class="m">{now.month} 月</div><div class="d ui-num">{now.day}</div>'
        f'<div class="w">周{WEEKDAYS[now.weekday()]}</div></div>'
        f'<div style="flex:1;min-width:0"><div class="verdict" style="color:{tone}">{esc(verdict)}</div>'
        f'<div class="why">{why}</div>{"".join(chips)}{extra}</div></div>', unsafe_allow_html=True)


def card(inner, style=""):
    st.markdown(f'<div class="ui-card" style="{style}">{inner}</div>', unsafe_allow_html=True)


def ask(text):
    st.markdown(f'<div class="ui-ask">{text}</div>', unsafe_allow_html=True)


GLOSSARY = {
    "QQQM": "一只 ETF（交易所买卖的基金），买 1 股就等于同时买了纳斯达克 100 指数里的 100 家大公司，多为科技公司。",
    "SPYM": "一只 ETF，跟踪标普 500 指数，覆盖美国 500 家大公司，行业更分散，波动比纳指小。",
    "定投": "每隔固定时间买入固定金额，不管涨跌。目的不是买在最低点，而是不用猜时机、也不会因为情绪乱操作。",
    "70/30": "这里的默认比例：70% 的钱买纳指 100（QQQM），30% 买标普 500（SPYM）。",
    "回撤 / 浮亏": "从最高点往下跌了多少。只要不卖，浮亏就还不是真的亏；但要有心理准备。",
    "200 日均线": "过去 200 个交易日收盘价的平均值，常用来粗略判断长期趋势。价格在它下面，说明近一年走势偏弱。",
    "把握度 ★": "这条规则背后有多少历史证据。★★★ 有几十年数据支持；★★ 风控或常识；★ 证据弱，只作提醒；☆ 实验中。"
               "它说的是规则可不可靠，不是“明天会涨”的把握。",
    "市场温度": "把几个冷热指标放在过去 10 年里排位，0° 最冷、100° 最热。只描述冷热，不改变定投计划。",
}


def glossary(keys=None):
    with st.expander("看不懂的词？点这里"):
        st.markdown("\n".join(f"- **{k}**：{v}" for k, v in GLOSSARY.items() if keys is None or k in keys))

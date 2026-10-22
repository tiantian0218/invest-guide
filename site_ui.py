"""网站的统一样式：颜色、字号、卡片、标签。所有页面都从这里取，保证看起来是一个整体。"""
import html
import json
from pathlib import Path

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
.ui-origin {{ border: 1px dashed #c7d2fe; background: #f8faff; border-radius: 10px; padding: 9px 12px; margin: 4px 0 12px;
             font-size: 14px; line-height: 1.65; }}
.ui-origin .src {{ font-size: 12px; color: {ACT}; font-weight: 600; }}
.ui-origin details summary {{ cursor: pointer; color: {ACT}; font-size: 13px; margin-top: 2px; }}
.ui-origin details div {{ margin-top: 6px; }}
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


# ---------------------------------------------------------------- 功能来源：抖音视频 → 网站模块
VIDEOS = {
    "macro": ("抖音 @xxx《趁年轻千万别研究美股》",
              "标题是反话：年轻人应该尽早研究美股，但不是为了赚快钱，而是借美股学会看懂利率、通胀、产业链和大资金，"
              "形成一套理解世界经济的方法。"),
    "agents": ("抖音 @毛线《将 AI 融入选股》",
               "用 AI 编程工具搭开源项目 TradingAgents：让多个 AI 分别扮演技术分析师、基本面分析师、新闻分析师、"
               "看多研究员、看空研究员和风控经理，辩论之后再给结论。"),
    "quant": ("抖音 @Mr.看海《怎样用 Codex 做量化策略研究》",
              "让 AI 帮你走完“提出想法 → 写回测 → 检验 → 复盘”的研究循环，同时提醒回测里最容易踩的坑。"),
    "multi": ("抖音 @SEA《多策略组合：CAGR 17%，最大回撤仅 −3%》",
              "把几种走势不同步的策略放在一起、定期再平衡，组合的波动和回撤会比单个策略小很多。"),
}

ORIGINS = {
    "today_why": ("macro", "把当天的利率、恐慌指数、大公司涨跌串起来，推测纳指和标普今天为什么涨或跌。",
                  "视频里说“美股是一张实时更新的世界经济地图”：美联储决定钱的价格，科技巨头决定资本流向，股价反映市场愿意为未来付多少钱。"
                  "这一块就是每天读一次这张地图。注意它推算的是相关性，不是确定的因果。"),
    "events": ("macro", "提前列出通胀数据（CPI、PCE）、就业数据和美联储开会的日子，让你知道哪天可能大涨大跌。",
               "<b>CPI</b> 是物价指数，衡量东西变贵得有多快。物价涨太快，美联储就不敢降息、甚至加息；借钱变贵，"
               "“靠未来赚钱”的科技公司估值就会被压低，所以数据公布当晚纳指经常大幅波动。"
               "<b>对你的影响：</b>定投不用躲开这些日子，只是提前知道，跌了不慌。"),
    "rates": ("macro", "展示 10 年、30 年期美国国债收益率的变化，解释利率为什么会影响股价。",
              "<b>美债收益率</b>就是把钱借给美国政府能拿到的利息，几乎没有风险。"
              "如果不冒风险都能拿 5%，大家买股票就会更挑剔：公司未来的利润折算到今天，就不值那么多钱。"
              "视频里的例子：30 年期美债收益率从 5.1% 涨到 5.3%，整个高估值的科技板块都会被重新定价。QQQM 科技股多，对利率更敏感。"),
    "economy": ("macro", "展示通胀和就业这两组美联储最看重的数据，以及它们最近的方向。",
                "美联储有两个任务：物价稳定、就业充分。通胀高、就业强，降息就会推迟，股市承压；"
                "通胀回落、就业转弱，降息预期升温，股市往往先涨。看懂这一点，就能理解“好消息为什么让股市跌”。"),
    "chain": ("macro", "按 AI 产业链（芯片 → 内存 → 网络 → 电力）列出相关公司今天的涨跌。",
              "一个热门产品背后有一串供应商。视频里的例子：英伟达的芯片需要 HBM 高带宽内存（美光、海力士），"
              "算力扩张会卡在网络（博通、Marvell），数据中心建好后又缺电。AI 火了，这一串公司都会动。"
              "<b>对你的影响：</b>QQQM 里已经装了其中大部分公司，看懂即可，不用单独去追。"),
    "f13": ("macro", "列出巴菲特等知名投资人最近一季公开的持仓变化。",
            "<b>13F</b> 是美国管理超过 1 亿美元的机构每季度必须公开的持仓清单。"
            "但它公开时已经比实际交易晚了至少 45 天，照着买往往是买在别人已经买完、甚至开始卖的时候，"
            "回测也没有稳定的超额收益。所以这里只用来学习大佬的思路，不当买入信号。"),
    "dip": ("quant", "用 1999 年以来的历史数据，检验“攒着钱等大跌再买”是否比按时定投更好。",
            "<b>回测</b>就是用历史数据模拟“如果过去 20 多年一直按这条规则做，结果会怎样”。"
            "视频介绍的是让 AI 帮忙做这件事；我们用它检验了一个很常见的直觉，结果是 15 种参数全部跑输按时定投，"
            "所以网站的信号改成了“有钱就按计划投，大跌时别停”。"),
    "diversify": ("multi", "检验在纳指和标普之外加入长期美债或黄金后，收益和回撤会怎样变化。",
                  "<b>CAGR</b> 是年化收益率，平均每年涨多少。<b>最大回撤</b>是从最高点最多跌了多少。"
                  "<b>相关系数</b>衡量两样东西是否同涨同跌：1 是完全同步，0 是没关系。"
                  "把不同步的东西放在一起，一个跌时另一个不一定跌，总资产就稳一些；<b>再平衡</b>就是定期把比例调回原样。"
                  "但视频里“年化 17%、最大回撤只有 −3%”好得不真实，要用下面的四个陷阱去检查。"),
    "pitfalls": ("quant", "教你一眼识别好得不真实的回测结果。",
                 "视频提醒：AI 写回测很快，但很容易写出“过去看起来很赚钱、将来不灵”的策略。"
                 "常见原因是参数调得太细（背答案）、没有拿新数据考试、忽略手续费，以及不小心用了当时还不知道的数据。"),
    "ai_review": ("agents", "每天让 AI 分别站在“看多”和“看空”两边，给你持有和关注的个股各找三条理由，再给中立结论。",
                  "就像请两个律师辩论，避免只听到一面之词。AI 说得头头是道但不一定对，"
                  "所以每次判断都会记下来，1 周、1 个月后和纳指比，公开它的真实成绩。只是参考，不是买卖信号。"),
    "research": ("agents", "输入任意一只股票，几分钟内得到一份多角色研究报告和“买入 / 观望 / 卖出”建议。",
                 "仿照 TradingAgents：技术分析师看走势，基本面分析师看赚不赚钱、贵不贵，新闻分析师看最近发生了什么；"
                 "看多和看空研究员根据这三份报告辩论；最后风控经理结合你的持仓和网站规则（个股合计不超过 15%、"
                 "单只不超过 5%、亏 25% 止损）给出建议和仓位上限。AI 会出错，建议只作参考，成绩同样会被记录。"),
}


def origin(key):
    """在模块标题下标出：这块来自哪条抖音、它是干什么的、用大白话解释。"""
    vid, does, plain = ORIGINS[key]
    src, idea = VIDEOS[vid]
    st.markdown(f'<div class="ui-origin"><div class="src">灵感来源 · {esc(src)}</div>'
                f'<div><b>这块是干什么的：</b>{does}</div>'
                f'<details><summary>用大白话解释</summary><div><b>视频的观点：</b>{idea}</div><div>{plain}</div></details></div>',
                unsafe_allow_html=True)


MODULE_PLACE = {"today_why": "看懂市场 · 今天为什么涨跌（「今天」页的“市场一句话”也用它）", "events": "看懂市场 · 接下来的大事",
                "rates": "看懂市场 · 利率", "economy": "看懂市场 · 通胀和就业", "chain": "看懂市场 · AI 产业链地图",
                "f13": "看懂市场 · 大佬在买什么", "dip": "工具箱 · 规则实验室 ①", "diversify": "工具箱 · 规则实验室 ②",
                "pitfalls": "工具箱 · 规则实验室 ③", "ai_review": "我的账户 · 个股 AI 体检（登录后）",
                "research": "我的账户 · 个股研究（登录后）"}


def feature_map():
    st.markdown("这个网站的不少功能，来自我们看过的几条抖音视频。下面列出每条视频讲了什么、变成了网站的哪一块。"
                "每个模块的标题下也有同样的“灵感来源”说明，点“用大白话解释”能看到概念解释。")
    for vid, (src, idea) in VIDEOS.items():
        rows = "".join(f'<div class="ui-row"><div style="flex:1"><b>{esc(MODULE_PLACE[k])}</b>'
                       f'<div class="ui-note">{does}</div></div></div>'
                       for k, (v, does, _) in ORIGINS.items() if v == vid)
        card(f'<div style="font-weight:700;font-size:16px">{esc(src)}</div>'
             f'<div style="font-size:14px;line-height:1.6;margin:4px 0 6px">{idea}</div>{rows}')
    st.caption("这些视频的观点我们都只拿来学习和检验，经不起数据检验的（比如攒钱等大跌）已经写明结论，不会变成买卖信号。")


# ---------------------------------------------------------------- 每日 AI 解读（ai_daily.py 每天生成并推到仓库）
AI_DAILY = Path(__file__).resolve().parent / "data" / "ai_daily.json"


def ai_daily():
    try:
        d = json.loads(AI_DAILY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if pd.Timestamp.now(tz="Asia/Shanghai") - pd.Timestamp(d["made_at"]) > pd.Timedelta(days=4):
        return None
    return d


def ai_card(full=True):
    d = ai_daily()
    if not d:
        return
    c = d.get("concept") or {}
    more = (f'<div style="margin-top:8px;padding-top:8px;border-top:1px solid {LINE}"><b>今天学一个词 · {esc(c.get("term", ""))}：</b>'
            f'{esc(c.get("plain", ""))}</div>' if full and c else "")
    watch = f'<div><b>接下来：</b>{esc(d["watch"])}</div>' if full and d.get("watch") else ""
    card(f'<div class="ui-note">AI 解读 · 美东 {esc(d["date"])} · Grok 根据公开数据撰写，可能出错</div>'
         f'<div style="font-size:17px;font-weight:700;margin:2px 0 4px">{esc(d["title"])}</div>'
         f'<div style="font-size:14px;line-height:1.7">{esc(d["story"])}</div>'
         f'<div style="font-size:14px;line-height:1.7;margin-top:4px"><b>对你：</b>{esc(d["for_you"])}</div>{watch}{more}',
         f"border-left:3px solid {ACT}")

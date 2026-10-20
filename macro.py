"""看懂市场：利率、通胀就业、宏观日历、AI 产业链、大型基金 13F 持仓、每日涨跌解读。只用于学习和解释。"""
import io
import json
import re
import time
from html import unescape

import pandas as pd
import requests

import invest
import market_data

CACHE = invest.CACHE
UA = {"User-Agent": "invest-helper research contact@invest-guide.app"}

# QQQ 前十大持仓的大致权重（%），用于估算谁拖累 / 带动了纳指。每季度变化不大。
QQQ_TOP = {"NVDA": 9.5, "MSFT": 8.3, "AAPL": 7.8, "AMZN": 5.5, "AVGO": 5.0, "META": 3.6,
           "GOOGL": 2.6, "GOOG": 2.5, "TSLA": 3.0, "NFLX": 1.3, "COST": 2.4}
NAMES = {"NVDA": "英伟达", "MSFT": "微软", "AAPL": "苹果", "AMZN": "亚马逊", "AVGO": "博通", "META": "Meta",
         "GOOGL": "谷歌", "GOOG": "谷歌", "TSLA": "特斯拉", "NFLX": "奈飞", "COST": "好市多", "AMD": "AMD",
         "TSM": "台积电", "ASML": "阿斯麦", "MU": "美光", "WDC": "西部数据", "MRVL": "迈威尔", "ANET": "Arista",
         "COHR": "Coherent", "LITE": "Lumentum", "CIEN": "Ciena", "VST": "Vistra", "CEG": "Constellation",
         "GEV": "GE Vernova", "ETN": "伊顿", "FCX": "自由港", "SCCO": "南方铜业", "ORCL": "甲骨文",
         "PLTR": "Palantir", "AMAT": "应用材料", "QQQM": "纳指100", "SPYM": "标普500", "STX": "希捷", "VRT": "维谛"}

# 视频里讲的 AI 链条：算力芯片 → 制造 → 存储 → 网络/光通信 → 数据中心电力 → 原材料（铜），以及最上游的需求方（云和应用）。
CHAIN = [
    ("需求方：云和 AI 应用", "大公司花钱建数据中心、买芯片，是整条链的“订单来源”", ["MSFT", "GOOGL", "AMZN", "META", "ORCL"]),
    ("算力芯片", "训练和运行 AI 模型的“大脑”", ["NVDA", "AMD", "AVGO"]),
    ("芯片制造和设备", "把芯片设计变成实物：代工厂和光刻机", ["TSM", "ASML", "AMAT"]),
    ("存储（HBM / 硬盘）", "AI 芯片旁边的高速内存和数据仓库", ["MU", "WDC", "STX"]),
    ("网络和光通信", "让成千上万块芯片互相“说话”的交换机和光模块", ["ANET", "MRVL", "COHR", "LITE", "CIEN"]),
    ("数据中心电力和散热", "数据中心非常耗电，发电、电网设备和散热成了新瓶颈", ["VST", "CEG", "GEV", "ETN", "VRT"]),
    ("原材料：铜", "电线、电网、数据中心都离不开铜", ["FCX", "SCCO"]),
]

# 13F：管理 1 亿美元以上的机构每季度结束后 45 天内必须公开美股持仓。
MANAGERS = [("巴菲特 · 伯克希尔", "0001067983"), ("彼得·蒂尔 · Thiel Macro", "0001562087"),
            ("德鲁肯米勒 · Duquesne", "0001536411"), ("比尔·阿克曼 · 潘兴广场", "0001336528")]

EVENT_INFO = {
    "CPI": ("CPI 通胀数据", "美国物价一个月涨了多少。高于预期 → 市场担心美联储不降息甚至加息 → 科技股往往下跌；低于预期则相反。"),
    "NFP": ("非农就业报告", "上个月美国新增多少工作、失业率多少。就业太强可能推高通胀和利率，太弱又让人担心经济衰退。"),
    "PCE": ("PCE 通胀数据", "美联储最看重的通胀指标。和 CPI 类似，越高越不利于降息。"),
    "FOMC": ("美联储议息会议", "决定美国基准利率（全世界“钱的价格”）。结果在美东下午 2 点公布（北京时间凌晨 2 或 3 点），之后还有主席发布会。"),
    "GDP": ("GDP 经济增长", "美国经济一个季度增长了多少，反映经济整体冷热。"),
}


def _get(url, **kw):
    r = requests.get(url, headers=UA, timeout=30, **kw)
    r.raise_for_status()
    return r


def _cached(name, max_age_hours, fetch):
    """网络失败时退回上次的缓存。"""
    path = CACHE / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return json.loads(path.read_text())
    try:
        data = fetch()
        path.write_text(json.dumps(data, ensure_ascii=False, default=str))
        return data
    except Exception:
        if path.exists():
            return json.loads(path.read_text())
        raise


# ---------- 利率 ----------
def yields():
    """美国财政部每日国债收益率（%）：列 2Y / 10Y / 30Y。"""
    def fetch():
        frames = []
        year = pd.Timestamp.now().year
        for y in (year - 1, year):
            url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                   f"{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
            frames.append(pd.read_csv(io.StringIO(_get(url).text)))
        d = pd.concat(frames)
        d = d.rename(columns={"2 Yr": "2Y", "10 Yr": "10Y", "30 Yr": "30Y"})[["Date", "2Y", "10Y", "30Y"]]
        d["Date"] = pd.to_datetime(d["Date"]).dt.strftime("%Y-%m-%d")
        return d.sort_values("Date").to_dict("list")
    d = pd.DataFrame(_cached("macro_yields.json", 6, fetch))
    return d.set_index(pd.to_datetime(d.pop("Date"))).astype(float)


# ---------- 通胀和就业 ----------
def _fred(ids):
    text = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={','.join(ids)}").text
    d = pd.read_csv(io.StringIO(text))
    d = d.set_index(pd.to_datetime(d.iloc[:, 0])).iloc[:, 1:]
    return d.apply(pd.to_numeric, errors="coerce")


def economy():
    """最新的通胀、就业和联邦基金利率，每项附带上一期用于比较。"""
    def fetch():
        m = _fred(["CPIAUCSL", "CPILFESL", "PCEPILFE", "UNRATE", "PAYEMS"]).loc["2023":]
        rate = _fred(["DFEDTARU", "DFEDTARL"]).dropna().iloc[-1]
        out = {"fed_upper": float(rate["DFEDTARU"]), "fed_lower": float(rate["DFEDTARL"])}
        for key, col in (("cpi", "CPIAUCSL"), ("core_cpi", "CPILFESL"), ("core_pce", "PCEPILFE")):
            yoy = (m[col] / m[col].shift(12) - 1).dropna() * 100
            out[key] = {"month": f"{yoy.index[-1]:%Y-%m}", "value": round(float(yoy.iloc[-1]), 2),
                        "prev": round(float(yoy.iloc[-2]), 2)}
        u = m["UNRATE"].dropna()
        out["unemployment"] = {"month": f"{u.index[-1]:%Y-%m}", "value": float(u.iloc[-1]), "prev": float(u.iloc[-2])}
        jobs = m["PAYEMS"].dropna().diff().dropna()
        out["payrolls"] = {"month": f"{jobs.index[-1]:%Y-%m}", "value": int(jobs.iloc[-1]),
                           "avg3": int(jobs.iloc[-3:].mean())}
        return out
    return _cached("macro_economy.json", 12, fetch)


# ---------- 宏观日历 ----------
def _text(url):
    h = _get(url).text
    h = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", h)))


def _parse_date(s, year=None):
    s = re.sub(r"\bSept\b", "Sep", s.replace(".", ""))
    return pd.Timestamp(f"{s} {year}" if year else s)


def calendar():
    """未来的重要数据发布日期（美东日期）。每周抓一次官方日程。"""
    def fetch():
        ev = []
        for kind, url in (("CPI", "https://www.bls.gov/schedule/news_release/cpi.htm"),
                          ("NFP", "https://www.bls.gov/schedule/news_release/empsit.htm")):
            for ref, day in re.findall(r"([A-Z][a-z]+ \d{4}) ([A-Z][a-z]{2,4}\.? \d{1,2}, \d{4}) \d{1,2}:\d{2} [AP]M", _text(url)):
                ev.append({"date": f"{_parse_date(day):%Y-%m-%d}", "kind": kind, "ref": ref})
        bea = _text("https://www.bea.gov/news/schedule")
        year = re.search(r"Year (\d{4})", bea)
        year = int(year.group(1)) if year else pd.Timestamp.now().year
        for day, title in re.findall(r"([A-Z][a-z]+ \d{1,2}) \d{1,2}:\d{2} [AP]M N ?ews (Personal Income and Outlays, [A-Z][a-z]+ \d{4}|GDP \([^)]*\), \w+ Quarter \d{4})", bea):
            ev.append({"date": f"{_parse_date(day, year):%Y-%m-%d}", "kind": "PCE" if title.startswith("Personal") else "GDP",
                       "ref": title.split(", ")[-1]})
        fomc = _text("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
        for block in re.finditer(r"(\d{4}) FOMC Meetings(.*?)(?=\d{4} FOMC Meetings|\* Meeting associated|Note:|$)", fomc):
            year = int(block.group(1))
            for month, d1, d2 in re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December)(?:/\w+)? (\d{1,2})-(\d{1,2})\*?", block.group(2)[:1500]):
                ev.append({"date": f"{_parse_date(f'{month} {d2}', year):%Y-%m-%d}", "kind": "FOMC", "ref": f"{month} {d1}-{d2}"})
        ev = {(e["date"], e["kind"]): e for e in ev}.values()
        return sorted(ev, key=lambda e: e["date"])
    rows = _cached("macro_calendar.json", 24 * 7, fetch)
    today = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
    out = []
    for e in rows:
        name, why = EVENT_INFO[e["kind"]]
        out.append(dict(e, name=name, why=why, past=e["date"] < today))
    return out


def upcoming(days=14):
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    return [dict(e, days=(pd.Timestamp(e["date"]) - today).days) for e in calendar()
            if 0 <= (pd.Timestamp(e["date"]) - today).days <= days]


def bj_time(e):
    """美东 8:30 / 14:00 换算成北京时间（夏令时 20:30 / 次日 02:00，冬令时 21:30 / 次日 03:00）。"""
    et = pd.Timestamp(e["date"] + (" 14:00" if e["kind"] == "FOMC" else " 08:30")).tz_localize("America/New_York")
    return et.tz_convert("Asia/Shanghai")


# ---------- 行情：涨跌解读和产业链 ----------
def chain_table(closes=None):
    tickers = sorted({t for _, _, ts in CHAIN for t in ts})
    if closes is None:
        closes, _ = market_data.closes(tickers + ["QQQM"], "1y")
    rows = []
    for stage, desc, ts in CHAIN:
        for t in ts:
            if t not in closes or closes[t].dropna().size < 25:
                continue
            s = closes[t].dropna()
            ytd = s[s.index >= f"{s.index[-1].year}-01-01"]
            rows.append({"环节": stage, "说明": desc, "代码": t, "名称": NAMES.get(t, t), "价格": float(s.iloc[-1]),
                         "1日": float(s.iloc[-1] / s.iloc[-2] - 1), "1月": float(s.iloc[-1] / s.iloc[-22] - 1),
                         "今年": float(s.iloc[-1] / ytd.iloc[0] - 1) if len(ytd) > 1 else None})
    return pd.DataFrame(rows)


def why_today():
    """用一两句大白话解释最近一个交易日纳指为什么涨跌。只说“可能的原因”，不是确定的因果。"""
    tickers = list(QQQ_TOP) + ["QQQM", "SPYM", "^VIX"]
    c, _ = market_data.closes([t for t in tickers if t != "^VIX"], "6mo")
    day = c.index[-1]
    ret = (c.iloc[-1] / c.iloc[-2] - 1)
    q = float(ret["QQQM"])
    contrib = {t: QQQ_TOP[t] / 100 * float(ret[t]) for t in QQQ_TOP if t in ret and pd.notna(ret[t])}
    merged = {}
    for t, v in contrib.items():
        merged[NAMES[t]] = merged.get(NAMES[t], 0) + v
    top_sum = sum(merged.values())
    movers = sorted(merged.items(), key=lambda kv: kv[1], reverse=q >= 0)[:3]
    movers = [(n, v) for n, v in movers if (v > 0) == (q >= 0) and abs(v) > 0.0005]

    y = yields()
    y = y[y.index <= day]
    d10 = (y["10Y"].iloc[-1] - y["10Y"].iloc[-2]) * 100 if len(y) > 1 else 0
    d30 = (y["30Y"].iloc[-1] - y["30Y"].iloc[-2]) * 100 if len(y) > 1 else 0
    w10 = (y["10Y"].iloc[-1] - y["10Y"].iloc[-6]) * 100 if len(y) > 6 else 0

    size = abs(q)
    up = q > 0
    mood = ("基本没动" if size < 0.003 else ("小涨" if up else "小跌") if size < 0.01 else
            ("上涨" if up else "下跌") if size < 0.02 else ("大涨" if up else "大跌"))
    lines = [f"纳指 100（QQQM）{mood} {q:+.2%}，标普 500（SPYM）{float(ret['SPYM']):+.2%}。"]
    if movers and size >= 0.003:
        names = "、".join(f"{n}（{float(ret[[t for t in QQQ_TOP if NAMES[t] == n][0]]):+.1%}）" for n, _ in movers)
        share = top_sum / q if q else 0
        lines.append(f"{'带头上涨的是' if up else '拖累最大的是'}{names}。"
                     + f"前十大公司占纳指约一半分量，贡献了约 {min(max(share, 0), 1):.0%} 的{'涨幅' if up else '跌幅'}，"
                     + ("主要是大公司在带动。" if share > 0.7 else "和它们的分量相当，说明涨跌比较普遍。" if share > 0.35
                        else "其他公司的影响更大。"))
    if abs(d10) >= 5:
        direction = "上升" if d10 > 0 else "下降"
        effect = "通常压低科技股估值（借钱更贵、未来利润折算到今天更不值钱）" if d10 > 0 else "通常对科技股有利"
        same = (d10 > 0) == (q < 0)
        lines.append(f"10 年期美债收益率{direction} {abs(d10):.0f} 个基点到 {y['10Y'].iloc[-1]:.2f}%，{effect}"
                     + ("，和今天的走势一致。" if same else "，但今天股市没有按这个方向走，说明还有别的因素更重要。"))
    elif abs(w10) >= 15:
        lines.append(f"过去一周 10 年期美债收益率累计{'上升' if w10 > 0 else '下降'} {abs(w10):.0f} 个基点，"
                     f"{'对高估值科技股是压力' if w10 > 0 else '对科技股是支撑'}。")
    recent = [e for e in calendar() if e["date"] == f"{day:%Y-%m-%d}"]
    for e in recent:
        lines.append(f"当天公布了{e['name']}（{e['ref']}），这类数据经常引起较大波动。")
    if len(lines) == 1 and size >= 0.003:
        lines.append("没有明显的单一原因，属于正常的日常波动。")
    return {"date": f"{day:%Y-%m-%d}", "qqqm": q, "lines": lines, "d10": d10, "d30": d30,
            "y10": float(y["10Y"].iloc[-1]), "y30": float(y["30Y"].iloc[-1])}


WEEKDAY = "一二三四五六日"


def event_line(e):
    bj = bj_time(e)
    when = "今天" if e["days"] == 0 else "明天" if e["days"] == 1 else f"{e['days']} 天后"
    return f"{when}（美东 {e['date'][5:]}，北京时间 {bj:%m-%d %H:%M} 周{WEEKDAY[bj.weekday()]}）{e['name']}"


def digest_md():
    """日报里的「看懂市场」：今天为什么涨跌、接下来几天的大事、每日一课。"""
    import lessons
    out = ["### 看懂市场"]
    try:
        w = why_today()
        out.append(f"**今天为什么涨跌**（美东 {w['date'][5:]}）")
        out += [f"- {x}" for x in w["lines"]]
    except Exception as e:
        print(f"涨跌解读跳过：{e}")
    try:
        soon = upcoming(3)
        nxt = soon or upcoming(30)[:1]
        if nxt:
            out.append("**接下来要关注**" if soon else "**下一件大事**")
            out += [f"- {event_line(e)}：{e['why']}" for e in nxt]
            if soon:
                out.append("- 数据公布前后波动会变大，定投照常，不用熬夜盯盘")
    except Exception as e:
        print(f"宏观日历跳过：{e}")
    l = lessons.today()
    out.append(f"**每日一课（{l['n']}/{l['total']} · {l['topic']}）：{l['title']}**")
    out.append(l["body"])
    out.append(f"和你的关系：{l['tie']}")
    return "\n".join(out) + "\n"


# ---------- 13F ----------
def _infotable(cik, acc):
    folder = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
    files = _get(folder + "/index.json").json()["directory"]["item"]
    xml = next(f["name"] for f in files if f["name"].lower().endswith(".xml") and "primary_doc" not in f["name"].lower())
    text = re.sub(r"<(/?)\w+:", r"<\1", _get(f"{folder}/{xml}").text)
    rows = []
    for block in re.findall(r"<infoTable>(.*?)</infoTable>", text, re.S):
        g = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S) or [None, ""])[1].strip()
        if g("putCall"):
            continue
        rows.append({"name": g("nameOfIssuer"), "cusip": g("cusip"), "value": float(g("value") or 0),
                     "shares": float(g("sshPrnamt") or 0)})
    d = pd.DataFrame(rows).groupby(["cusip"], as_index=False).agg(name=("name", "first"), value=("value", "sum"),
                                                                 shares=("shares", "sum"))
    # 2023 年起规定按美元填报，但仍有机构按千美元填；隐含股价普遍低于 1 美元说明单位是千。
    if (d["value"] / d["shares"].where(d["shares"] > 0)).median() < 1:
        d["value"] *= 1000
    return d


def holdings_13f():
    """每位基金经理最近两个季度的持仓对比。每天最多抓一次。"""
    def fetch():
        out = []
        for label, cik in MANAGERS:
            sub = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()["filings"]["recent"]
            idx = [i for i, f in enumerate(sub["form"]) if f in ("13F-HR", "13F-HR/A")]
            seen, picks = set(), []
            for i in idx:
                if sub["reportDate"][i] not in seen:
                    seen.add(sub["reportDate"][i])
                    picks.append(i)
                if len(picks) == 2:
                    break
            if len(picks) < 2:
                continue
            cur, prev = (_infotable(cik, sub["accessionNumber"][i]) for i in picks)
            m = cur.merge(prev, on="cusip", how="outer", suffixes=("", "_prev")).fillna({"value": 0, "shares": 0,
                                                                                          "value_prev": 0, "shares_prev": 0})
            m["name"] = m["name"].fillna(m["name_prev"])
            total = m["value"].sum()
            m["weight"] = m["value"] / total if total else 0
            m["change"] = m.apply(lambda r: "新买入" if r["shares_prev"] == 0 else "清仓" if r["shares"] == 0 else
                                  f"{r['shares'] / r['shares_prev'] - 1:+.0%}" if abs(r["shares"] / r["shares_prev"] - 1) >= 0.05
                                  else "基本不变", axis=1)
            out.append({"manager": label, "report": sub["reportDate"][picks[0]], "filed": sub["filingDate"][picks[0]],
                        "total": total, "rows": m.sort_values("value", ascending=False)
                        [["name", "value", "weight", "shares", "shares_prev", "change"]].to_dict("records")})
            time.sleep(0.3)
        return out
    return _cached("macro_13f.json", 24, fetch)

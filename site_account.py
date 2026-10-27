"""公开网站的「我的账户」页：注册 / 登录 / 持仓盈亏 / 记账。数据存在 Supabase，每个用户只能看到自己的。"""
import hashlib
import html
import json
import secrets
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import cloud_api
import site_ui as ui
import market_data

UP, DOWN = "#d62728", "#16a34a"
CORE = ["QQQM", "SPYM"]
COOKIE = "ig_rt"
COOKIE_DAYS = 30


def summarize(deposits, trades, prices):
    """返回 (持仓表, 汇总字典)。卖出时股数填负数。"""
    tr = pd.DataFrame(trades, columns=cloud_api.TABLES["trades"])
    dep = pd.DataFrame(deposits, columns=cloud_api.TABLES["deposits"])
    for c in ("shares", "price_usd", "fee_usd"):
        tr[c] = pd.to_numeric(tr[c]).fillna(0)
    for c in ("cny", "usd"):
        dep[c] = pd.to_numeric(dep[c]).fillna(0)
    rows = []
    for t, g in tr.groupby("ticker"):
        sh = cost = 0.0
        for _, r in g.sort_values("date").iterrows():
            if r["shares"] > 0:
                cost += r["shares"] * r["price_usd"] + r["fee_usd"]
                sh += r["shares"]
            elif sh > 0:
                cost *= max(0.0, 1 + r["shares"] / sh)
                sh += r["shares"]
        if sh <= 1e-9:
            continue
        px = prices.get(t)
        mv = sh * px if px else None
        rows.append({"代码": t, "股数": sh, "平均成本": cost / sh, "现价": px, "市值": mv,
                     "盈亏": mv - cost if mv is not None else None, "成本": cost})
    pos = pd.DataFrame(rows)
    spent = float((tr["shares"] * tr["price_usd"] + tr["fee_usd"]).sum())
    cash = float(dep["usd"].sum()) - spent
    mv = float(pos["市值"].fillna(pos["成本"]).sum()) if len(pos) else 0.0
    return pos, {"cash": cash, "mv": mv, "total": mv + cash, "in_usd": float(dep["usd"].sum()),
                 "in_cny": float(dep["cny"].sum()), "cost": float(pos["成本"].sum()) if len(pos) else 0.0}


@st.cache_data(ttl=900, show_spinner=False)
def _prices(tickers):
    d, _ = market_data.closes(list(tickers), "6mo")
    return {t: float(d[t].dropna().iloc[-1]) for t in tickers if t in d and d[t].notna().any()}


@st.cache_data(ttl=3600, show_spinner=False)
def _fx():
    return market_data.fx()


_cookie_bridge = components.declare_component("cookie_bridge", path=str(Path(__file__).parent / "cookie_bridge"))


def _set_tokens(tokens, remember=None):
    st.session_state["sb_tokens"] = tokens
    if remember is not None:
        st.session_state["sb_remember"] = remember
    st.session_state.pop("sb_logged_out", None)


def _read_cookie():
    """本机能从请求头读到；Streamlit Cloud 的代理会去掉自定义 cookie，只能等浏览器端组件回传。
    返回 None 表示浏览器还没回话，"" 表示确实没有。"""
    try:
        rt = st.context.cookies.get(COOKIE)
    except Exception:
        rt = None
    return rt or _cookie_bridge(name=COOKIE, key="cookie_bridge", default=None)


def _session():
    tok = st.session_state.get("sb_tokens")
    if not tok and not st.session_state.get("sb_logged_out"):
        rt = _read_cookie()
        if rt is None:
            st.session_state["sb_cookie_pending"] = True
        if rt:
            try:
                tok = cloud_api.refresh(rt)
                _set_tokens(tok, remember=True)
            except Exception:
                st.session_state["sb_logged_out"] = True
    if not tok:
        return None
    return cloud_api.Session(tok, on_refresh=_set_tokens)


def _sync_cookie():
    """Supabase 的续期令牌每次使用后都会换新，所以每次运行结束都把最新的写回浏览器。"""
    tok = st.session_state.get("sb_tokens")
    if tok and st.session_state.get("sb_remember"):
        value, age = tok["refresh_token"], COOKIE_DAYS * 86400
    elif st.session_state.get("sb_logged_out") or (tok and not st.session_state.get("sb_remember")):
        value, age = "", 0
    else:
        return
    if st.session_state.get("sb_cookie_written") == (value, age):
        return
    st.session_state["sb_cookie_written"] = (value, age)
    cookie = json.dumps(f"{COOKIE}={value}; path=/; max-age={age}; SameSite=Lax; Secure")
    components.html(f"<script>try{{parent.document.cookie={cookie}}}catch(e){{document.cookie={cookie}}}</script>", height=0)


def _reset_by_email():
    """接入自有发信服务（SMTP）并在邮件模板里加入 {{ .Token }} 后，在 Secrets 里设 reset_by_email = true。"""
    try:
        return bool(st.secrets["supabase"].get("reset_by_email"))
    except Exception:
        return False


def _login_box():
    st.caption("每个人只能看到自己的数据。请设置一个**新的**密码，不要和银行、邮箱的密码相同；"
               "本网站永远不会向你索要银行账号密码。")
    mode = st.radio("操作", ["登录", "注册新账号", "忘记密码"], horizontal=True, label_visibility="collapsed")
    if mode == "登录":
        with st.form("login"):
            email = st.text_input("邮箱")
            pw = st.text_input("密码", type="password")
            remember = st.checkbox(f"在这台设备上保持登录（{COOKIE_DAYS} 天）", value=True,
                                   help="公用电脑请不要勾选")
            if st.form_submit_button("登录", type="primary"):
                try:
                    _set_tokens(cloud_api.sign_in(email.strip(), pw), remember=remember)
                    st.rerun()
                except cloud_api.CloudError as e:
                    st.error(str(e))
    elif mode == "注册新账号":
        with st.form("signup"):
            email = st.text_input("邮箱")
            pw = st.text_input("密码（至少 8 位）", type="password")
            pw2 = st.text_input("再输一次密码", type="password")
            if st.form_submit_button("注册", type="primary"):
                if pw != pw2:
                    st.error("两次密码不一样")
                elif len(pw) < 8:
                    st.error("密码至少 8 位")
                else:
                    try:
                        r = cloud_api.sign_up(email.strip(), pw)
                        if r.get("access_token"):
                            st.session_state["sb_tokens"] = r
                            st.rerun()
                        st.success("注册成功！请切换到「登录」。如果提示邮箱未验证，请到邮箱点击确认链接（可能在垃圾邮件里）。")
                    except cloud_api.CloudError as e:
                        st.error(str(e))
    elif not _reset_by_email():
        st.info("忘记密码暂时需要联系网站管理员处理。请把密码记在手机备忘录或密码管理器里。")
    else:
        email = st.text_input("注册时用的邮箱", key="rs_email")
        if st.button("发送验证码"):
            try:
                cloud_api.reset_password(email.strip())
                st.success("如果这个邮箱注册过，验证码已发出（注意查看垃圾邮件）。")
            except cloud_api.CloudError as e:
                st.error(str(e))
        with st.form("reset"):
            code = st.text_input("邮件里的 6 位验证码")
            pw = st.text_input("新密码（至少 8 位）", type="password")
            if st.form_submit_button("重设密码"):
                try:
                    s = cloud_api.Session(cloud_api.verify_recovery(email.strip(), code))
                    s.update_password(pw)
                    st.session_state["sb_tokens"] = s.tokens
                    st.success("密码已更新，已为你登录。")
                    st.rerun()
                except cloud_api.CloudError as e:
                    st.error(str(e))


def _money(x, unit="$"):
    return f"{'−' if x < 0 else ''}{unit}{abs(x):,.2f}"


def _colored(x, unit="$"):
    return f'<span style="color:{UP if x >= 0 else DOWN}">{"+" if x >= 0 else ""}{_money(x, unit)}</span>'


def _signed(x, unit, digits=2):
    return f"{'+' if x >= 0 else '−'}{unit}{abs(x):,.{digits}f}"


def _card(label, main, sub, color=None):
    style = f"color:{color};" if color else ""
    return (f'<div class="ui-card" style="height:100%;margin:0">'
            f'<div style="color:{ui.MUTED};font-size:14px">{label}</div>'
            f'<div class="ui-num" style="font-size:26px;font-weight:700;{style}line-height:1.3">{main}</div>'
            f'<div style="color:{ui.MUTED};font-size:13px">{sub}</div></div>')


def _cell(main, sub, color=None):
    style = f' style="color:{color}"' if color else ""
    return f'<span{style}><b>{main}</b></span><br><span style="color:#9ca3af;font-size:12px">{sub}</span>'


def _logout(s=None):
    if s is not None:
        cloud_api.logout(s.tokens["access_token"])
    st.session_state.pop("sb_tokens", None)
    st.session_state["sb_logged_out"] = True


def current_session():
    """整页只调用一次（读 cookie 的组件每次运行只能出现一次），结果交给「今天」和「我的账户」共用。"""
    return _session() if cloud_api.enabled() else None


def account_tab(s):
    if not cloud_api.enabled():
        st.info("账户功能还在准备中，敬请期待。")
        return
    _account_body(s)
    _sync_cookie()


def money_strip(s):
    """首页用的一行「我的钱」，返回人民币总资产（拿不到返回 None）。"""
    try:
        dep, tr = s.rows("deposits"), s.rows("trades")
    except cloud_api.CloudError:
        return None
    if not dep and not tr:
        return None
    tickers = tuple(sorted({r["ticker"] for r in tr} | set(CORE)))
    try:
        prices, (_, usdcny) = _prices(tickers), _fx()
    except Exception:
        return None
    pos, sm = summarize(dep, tr, prices)
    total = sm["total"] * usdcny
    pnl = total - sm["in_cny"]
    pct = pnl / sm["in_cny"] * 100 if sm["in_cny"] else 0.0
    a, b, c = st.columns(3)
    a.markdown(_card("总资产", f"¥{total:,.0f}", f"${sm['total']:,.2f}"), unsafe_allow_html=True)
    b.markdown(_card("总盈亏", f"{_signed(pnl, '¥', 0)}", f"{pct:+.2f}%（含汇率）", UP if pnl >= 0 else DOWN),
               unsafe_allow_html=True)
    c.markdown(_card("可用现金", f"¥{sm['cash'] * usdcny:,.0f}", f"${sm['cash']:,.2f}"), unsafe_allow_html=True)
    st.caption("持仓明细、记账和「假如照做了」回溯在「我的账户」。")
    return total


def _account_body(s):
    if s is None:
        if st.session_state.pop("sb_cookie_pending", False):
            st.caption("正在恢复上次的登录…")
        ui.section("登录后，这个工具会变成你自己的投资助理")
        _features([("专属信号", "按你的持仓算", "「今天」页的日签换成你自己的：该买什么、买多少、哪只个股该卖。"),
                   ("自动记账", "汇丰成交即入账", "成交邮件自动写进记录，持仓、盈亏、人民币和汇率一起算好。"),
                   ("复盘", "照做了会怎样", "每月总结你的实际收益 vs 全部照做 vs 只定投指数，并检查仓位是否偏离。"),
                   ("AI 研究", "个股和问答", "输入股票名字就能得到多空辩论和操作建议，成绩公开打分。")])
        _login_box()
        return
    c1, c2 = st.columns([4, 1])
    c1.caption(f"已登录：{s.email}")
    if c2.button("退出登录"):
        _logout(s)
        st.rerun()
    try:
        shares = s.shares()
    except cloud_api.CloudError as e:
        _logout()
        st.error(f"登录已过期，请重新登录（{e}）")
        return
    shared_to_me = [r for r in (shares or []) if r.get("viewer") == s.uid]
    owner, readonly = s.uid, False
    if shared_to_me:
        names = {s.uid: "我自己的账户"} | {r["owner"]: f"{r['owner_email']} 的账户（只读）" for r in shared_to_me}
        owner = st.selectbox("查看", list(names), format_func=names.get)
        readonly = owner != s.uid
    try:
        dep, tr = s.rows("deposits", owner=owner), s.rows("trades", owner=owner)
    except cloud_api.CloudError as e:
        _logout()
        st.error(f"登录已过期，请重新登录（{e}）")
        return
    if readonly:
        st.info("这是家人共享给你的账户，只能查看，不能修改。")

    tickers = tuple(sorted({r["ticker"] for r in tr} | set(CORE)))
    try:
        prices, (usdhkd, usdcny) = _prices(tickers), _fx()
    except Exception:
        prices, usdhkd, usdcny = {}, None, None
        st.warning("行情暂时获取失败，市值按成本显示。")
    pos, sm = summarize(dep, tr, prices)

    if readonly:
        _signal_box(s, owner)
    ui.section("我的钱", None if readonly else "今天要不要操作，看「今天」页最上面的日签")
    if not dep and not tr:
        st.markdown("这个账户还没有记录。" if readonly else
                    "还没有记录。钱到账后先在下面**记一笔入金**，买入成交后**记一笔成交**。")
        views = ["记账"] + ([] if readonly else ["自动记账与共享"])
        view = ui.pills("看什么", views, key="acct_view_empty", default="记账", label_visibility="collapsed")
    else:
        pnl_usd = sm["total"] - sm["in_usd"]
        pct_usd = pnl_usd / sm["in_usd"] * 100 if sm["in_usd"] else 0.0
        a, b, c = st.columns(3)
        if usdcny:
            hkd = (lambda x: f"HK${x * usdhkd:,.0f}") if usdhkd else (lambda x: "")
            total_cny = sm["total"] * usdcny
            pnl_cny = total_cny - sm["in_cny"]
            pct_cny = pnl_cny / sm["in_cny"] * 100 if sm["in_cny"] else 0.0
            a.markdown(_card("总资产", f"¥{total_cny:,.0f}", f"${sm['total']:,.2f} · {hkd(sm['total'])}"), unsafe_allow_html=True)
            b.markdown(_card("总盈亏（人民币）", f"{_signed(pnl_cny, '¥', 0)}（{pct_cny:+.2f}%）",
                             f"股票本身 {_signed(pnl_usd, '$')}（{pct_usd:+.2f}%）", UP if pnl_cny >= 0 else DOWN),
                       unsafe_allow_html=True)
            c.markdown(_card("可用现金", f"¥{sm['cash'] * usdcny:,.0f}", f"${sm['cash']:,.2f} · {hkd(sm['cash'])}"),
                       unsafe_allow_html=True)
            st.caption(f"累计转入 ¥{sm['in_cny']:,.0f}。按今日汇率 1 美元 = {usdcny:.4f} 元"
                       + (f" = {usdhkd:.4f} 港币" if usdhkd else "") + " 折算。"
                       "人民币盈亏 = 股票涨跌 + 汇率变化 + 换汇成本，所以会和美元盈亏不同。颜色按 A 股习惯：红涨绿跌。")
        else:
            a.markdown(_card("总资产", _money(sm["total"]), "汇率暂时获取失败，先按美元显示"), unsafe_allow_html=True)
            b.markdown(_card("总盈亏", f"{_signed(pnl_usd, '$')}（{pct_usd:+.2f}%）", "美元口径", UP if pnl_usd >= 0 else DOWN),
                       unsafe_allow_html=True)
            c.markdown(_card("可用现金", _money(sm["cash"]), "美元"), unsafe_allow_html=True)
        views = ["持仓", "复盘", "记账"] + ([] if readonly else ["自动记账与共享"])
        view = ui.pills("看什么", views, key="acct_view", default="持仓", label_visibility="collapsed")
        if view == "持仓" and len(pos):
            rate = usdcny or 0
            rows = []
            for _, r in pos.iterrows():
                mv, pnl = r["市值"], r["盈亏"]
                color = (UP if pnl >= 0 else DOWN) if pd.notna(pnl) else None
                if rate and pd.notna(mv):
                    mv_cell = _cell(f"¥{mv * rate:,.0f}", f"${mv:,.2f}")
                    pnl_cell = _cell(_signed(pnl * rate, "¥", 0), _signed(pnl, "$"), color)
                else:
                    mv_cell = f"${mv:,.2f}" if pd.notna(mv) else "—"
                    pnl_cell = _colored(pnl) if pd.notna(pnl) else "—"
                pct = pnl / r["成本"] * 100 if pd.notna(pnl) and r["成本"] else None
                rows.append({
                    "代码": html.escape(str(r["代码"])), "股数": f"{r['股数']:g}",
                    "现价（美元）": f"${r['现价']:,.2f}" if pd.notna(r["现价"]) else "—",
                    "平均成本（美元）": f"${r['平均成本']:,.2f}",
                    "市值": mv_cell, "盈亏": pnl_cell,
                    "盈亏%": f'<span style="color:{color}">{pct:+.2f}%</span>' if pct is not None else "—",
                })
            st.markdown(pd.DataFrame(rows).to_html(index=False, escape=False, classes="ui-table"),
                        unsafe_allow_html=True)
            st.caption("美股以美元交易，现价和成本保留美元；市值和盈亏按今日汇率折成人民币，灰色小字为美元。"
                       "价格为最近收盘价，每 15 分钟更新；以银行 App 显示为准。")
    if view == "复盘":
        st.caption("照做了会怎样、每月总结和短线实验。AI 对你个股的看法在「AI 研究」。")
        _whatif_box(s, owner)
        _monthly_box(s, owner)
        _paper_box(s, owner)
    elif view == "记账":
        if readonly:
            _records(s, dep, tr, readonly=True)
            return
        c1, c2 = st.columns(2)
        with c1.expander("记一笔入金（钱换成美元到账后）", expanded=not dep):
            with st.form("dep", clear_on_submit=True):
                d = st.date_input("到账日期")
                cny = st.number_input("转出的人民币", min_value=0.0, value=0.0, step=500.0)
                usd = st.number_input("到账美元", min_value=0.0, value=0.0, step=1.0)
                note = st.text_input("备注（可不填）")
                if st.form_submit_button("保存入金"):
                    if usd <= 0:
                        st.error("请填写到账美元")
                    else:
                        s.insert("deposits", [{"date": str(d), "cny": cny, "usd": usd, "note": note}])
                        st.rerun()
        with c2.expander("记一笔成交（买入成交后）", expanded=bool(dep) and not tr):
            with st.form("trade", clear_on_submit=True):
                d = st.date_input("成交日期")
                t = st.text_input("代码", value="QQQM").strip().upper()
                n = st.number_input("股数（卖出填负数）", value=1.0, step=1.0)
                p = st.number_input("成交价（美元）", min_value=0.0, value=0.0, step=0.01, format="%.2f")
                fee = st.number_input("佣金（美元）", min_value=0.0, value=0.0, step=1.0)
                note = st.text_input("备注（可不填）")
                if st.form_submit_button("保存成交"):
                    if not t or p <= 0 or n == 0:
                        st.error("请填写代码、股数和成交价")
                    else:
                        s.insert("trades", [{"date": str(d), "ticker": t, "shares": n, "price_usd": p, "fee_usd": fee, "note": note}])
                        st.rerun()
        _records(s, dep, tr)
    elif view == "自动记账与共享":
        _mail_guide()
        _share_box(s, shares)


HSBC_SENDERS = ("HSBC@notification.hsbc.com.hk", "hsbc.notifications@message.hsbc.com.hk",
                "hsbc.communications@message.hsbc.com.hk", "donotreply@mail.hsbc.com.hk")


def _mail_guide():
    ui.section("汇丰成交自动记账", "成交后 10 分钟内自动写进交易记录，并推送一条微信确认；全程不需要汇丰的账号密码")
    flow = "".join(f'<div class="ui-step"><b>{a}</b><span>{b}</span></div>' for a, b in (
        ("汇丰", "成交后发邮件到你的 Outlook"), ("Outlook 规则", "原样重定向到 QQ 邮箱"),
        ("你的 Mac", "每 10 分钟读一次 QQ 邮箱"), ("网站 + 微信", "写入记录、同步、推送确认")))
    st.markdown(f'<div class="ui-flow">{flow}</div>', unsafe_allow_html=True)
    senders = "".join(f"<code>{x}</code><br>" for x in HSBC_SENDERS)
    ui.card(f'''<div class="ui-guide">
<p><b>第 1 步 · 汇丰 App 打开成交邮件</b><br>「设定 → 通知 / 提示」里打开证券交易执行的电邮提示，并确认登记的电邮是你的 Outlook 地址。</p>
<p><b>第 2 步 · Outlook 新建规则</b>（网页版：设置 → 邮件 → 规则 → 添加规则）<br>
条件选 <b>From（发件人）</b>，一次填入下面四个汇丰地址（满足任意一个即可）：<br>{senders}
操作选 <b>Redirect to（重定向到）</b>你的 QQ 邮箱，勾选“停止处理更多规则”，保存。</p>
<p><b>第 3 步 · QQ 邮箱开启 IMAP</b><br>QQ 邮箱 → 设置 → 账户 → 开启 IMAP/SMTP，生成<b>授权码</b>；在 Mac 上运行
<code>python hsbc_mail.py setup</code>，授权码由你自己输入，只存在 Mac 的钥匙串里。</p>
<p><b>第 4 步 · 验证</b><br>下一笔成交后 10 分钟内应收到“已自动记账”的微信，并在「记账」里看到这笔记录。</p></div>''')
    with st.expander("常见问题"):
        st.markdown(
            "- **为什么要“重定向”而不是“转发”？** 重定向会保留汇丰原来的发件人，程序靠它认出这是汇丰邮件。\n"
            "- **规则里“立即运行”是灰色的？** 正常。Outlook 不允许对带转发 / 重定向的规则手动运行，它只处理之后新到的邮件。\n"
            "- **漏了一笔怎么办？** 在 Outlook 里把那封成交邮件手动转发到 QQ 邮箱，标题保持原样；程序会从正文里取汇丰原邮件的时间，交易日期不会记错。\n"
            "- **只填 `hsbc` 关键字行不行？** 不行。“From” 条件需要完整地址；关键字要用“Sender address includes”，"
            "而且多个条件之间是“并且”关系，混用容易一封都不匹配。\n"
            "- **会不会记重？** 不会。同一个交易编号只记一次。\n"
            "- **佣金呢？** 邮件里没有佣金，先记 0，月结单出来后在记录里补上。")
    st.caption("这套流程依赖你自己电脑上的记账程序，目前只对网站作者本人的账户生效。")


def _features(items):
    width = 300 if len(items) % 2 == 0 else 180
    st.markdown(f'<div class="ui-feats" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,{width}px),1fr))">' + "".join(
        f'<div class="ui-feat"><div class="k">{a}</div><div class="t">{b}</div><div class="d">{c}</div></div>'
        for a, b, c in items) + "</div>", unsafe_allow_html=True)


def ai_tab(s):
    ui.section("AI 研究", "几位 AI 分析师分工替你做功课：看走势、看财报、看新闻，再让看多和看空两方辩论")
    if s is None:
        _features([("个股研究", "输入名字就能查", "英伟达、AAPL、SpaceX 都行。技术面、基本面、消息面三份报告，多空辩论后给出买入 / 观望 / 卖出和仓位上限。"),
                   ("问一个问题", "像问老师一样", "“利率涨了为什么纳指跌？”结合你的持仓用大白话回答。"),
                   ("每日持仓体检", "成绩公开", "每天早上给你持有的个股做一次多空体检，1 周 / 1 个月后和纳指比，判断对不对一目了然。")])
        ui.origin("research")
        st.info("登录后可用，研究结果只有你自己能看到。登录入口在「我的账户」。")
        return
    _ai_desk(s)
    _review_box(s, s.uid)
    ui.origin("research")


def _records(s, dep, tr, readonly=False):
    for table, label, cols in (("deposits", "入金记录", {"date": "日期", "cny": "人民币", "usd": "美元", "note": "备注"}),
                               ("trades", "成交记录", {"date": "日期", "ticker": "代码", "shares": "股数", "price_usd": "价格",
                                                    "fee_usd": "佣金", "note": "备注"})):
        rows = dep if table == "deposits" else tr
        if not rows:
            continue
        with st.expander(f"{label}（{len(rows)} 条）"):
            df = pd.DataFrame(rows)
            st.dataframe(df[list(cols)].rename(columns=cols), hide_index=True)
            if readonly:
                continue
            pick = st.multiselect("删除记错的记录", df["id"], key=f"del_{table}",
                                  format_func=lambda i: " · ".join(str(v) for v in df.loc[df["id"] == i, list(cols)[:-1]].iloc[0]))
            if pick and st.button("确认删除", key=f"btn_{table}"):
                s.delete(table, pick)
                st.rerun()


INVITE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _hash(code):
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def _share_box(s, shares):
    with st.expander("家人共享（只读查看）"):
        if shares is None:
            st.info("家人共享功能还没开通：管理员需要先在数据库里运行 cloud/share.sql。")
            return
        now = pd.Timestamp.now(tz="UTC")
        mine = [r for r in shares if r["owner"] == s.uid]
        viewers = [r for r in mine if r.get("viewer")]
        pending = [r for r in mine if not r.get("viewer") and r.get("code_hash") and pd.Timestamp(r["expires_at"]) > now]
        to_me = [r for r in shares if r.get("viewer") == s.uid]

        st.markdown("**让家人查看我的账户**：家人用**自己的账号**登录，输入你给的邀请码，就能看到你的持仓和盈亏，"
                    "但不能记账、不能删除。你的密码不需要告诉任何人，随时可以取消。")
        for r in viewers:
            a, b = st.columns([4, 1])
            a.markdown(f"✅ {html.escape(r.get('viewer_email') or '家人')} 可以查看")
            if b.button("取消授权", key=f"rm_{r['id']}"):
                s.remove_share(r["id"])
                st.rerun()
        for r in pending:
            a, b = st.columns([4, 1])
            exp = pd.Timestamp(r["expires_at"]).tz_convert("Asia/Shanghai")
            a.markdown(f"⏳ 一个邀请码还没被使用（{exp:%m-%d %H:%M} 前有效）")
            if b.button("作废", key=f"rm_{r['id']}"):
                s.remove_share(r["id"])
                st.rerun()
        shown = st.session_state.pop("sb_new_invite", None)
        if shown:
            st.success(f"邀请码：**{shown}**  \n24 小时内有效，只能用一次。请当面或用微信发给家人，不要发到群里。")
        with st.form("invite", clear_on_submit=True):
            pw = st.text_input("为了确认是你本人，请再输入一次你的登录密码", type="password")
            if st.form_submit_button("生成邀请码"):
                try:
                    cloud_api.sign_in(s.email, pw)
                except cloud_api.CloudError:
                    st.error("密码不对，没有生成邀请码")
                else:
                    code = "".join(secrets.choice(INVITE_CHARS) for _ in range(8))
                    s.create_invite(_hash(code))
                    st.session_state["sb_new_invite"] = code
                    st.rerun()

        st.divider()
        st.markdown("**查看家人的账户**：输入家人给你的邀请码。")
        for r in to_me:
            a, b = st.columns([4, 1])
            a.markdown(f"👀 你可以查看 {html.escape(r['owner_email'])} 的账户（在页面最上方切换）")
            if b.button("不再查看", key=f"rm_{r['id']}"):
                s.remove_share(r["id"])
                st.rerun()
        with st.form("redeem", clear_on_submit=True):
            code = st.text_input("邀请码（8 位）")
            if st.form_submit_button("确认"):
                try:
                    who = s.redeem(code.strip().upper())
                    st.session_state["sb_redeemed"] = who
                    st.rerun()
                except cloud_api.CloudError as e:
                    st.error(str(e))
        who = st.session_state.pop("sb_redeemed", None)
        if who:
            st.success(f"成功！现在可以在页面最上方切换查看 {who} 的账户。")


def _signal_box(s, owner):
    try:
        snap = s.get_paper(owner)
    except cloud_api.CloudError:
        return
    sig = ((snap or {}).get("payload") or {}).get("signals")
    if sig:
        signal_card(sig, snap["updated_at"])


def signal_card(sig, updated_at, confidence=None, stars=None):
    updated = pd.Timestamp(updated_at).tz_convert("Asia/Shanghai")
    age = (pd.Timestamp.now(tz="Asia/Shanghai").normalize() - pd.Timestamp(sig["date"]).tz_localize("Asia/Shanghai")).days
    rows = ""
    for r in sig["rows"]:
        chg = f'<span style="color:{UP if r["chg"] >= 0 else DOWN}"> {r["chg"]:+.2%}</span>' if r.get("chg") is not None else ""
        conf = ""
        if confidence:
            n, basis = confidence(r["asset"], r["signal"])
            conf = (f'<div style="font-size:12px;color:#6b7280;margin-top:2px">把握度 {stars(n)} · {html.escape(basis)}</div>')
        rows += (f'<div style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-top:1px solid #eef0f3">'
                 f'<span style="background:{r["color"]};color:#fff;border-radius:6px;padding:2px 8px;font-weight:700;'
                 f'white-space:nowrap;font-size:14px">{html.escape(r["signal"])}</span>'
                 f'<div><div style="font-weight:600">{html.escape(r["asset"])}{chg}</div>'
                 f'<div style="font-size:14px;line-height:1.5">{html.escape(r["why"])}</div>'
                 f'<div style="font-size:12px;color:#9ca3af">规则：{html.escape(r["rule"])}</div>{conf}</div></div>')
    stale = (f'<div style="color:#d97706;font-size:13px">这是 {age} 天前的信号（电脑当天可能没开机），以汇丰 App 的价格为准。</div>'
             if age > 0 else "")
    st.markdown(
        f'<div style="padding:14px 16px;border-radius:12px;background:#f9fafb;margin:6px 0 12px">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline">'
        f'<b style="font-size:18px">今日信号</b><span style="color:#6b7280;font-size:12px">更新于 {updated:%m-%d %H:%M}</span></div>'
        f'<div style="font-size:20px;font-weight:700;margin:6px 0 2px">{html.escape(sig["headline"])}</div>{stale}'
        f'{rows}</div>', unsafe_allow_html=True)
    st.caption("红色标签 = 买入 / 加码，绿色 = 卖出 / 考虑卖出，蓝色 = 持有不动，灰色 = 只观察。"
               "信号全部来自写死的规则，不构成投资建议；工具不会替你下单。")


def _whatif_box(s, owner):
    try:
        snap = s.get_paper(owner)
    except cloud_api.CloudError:
        return
    w = ((snap or {}).get("payload") or {}).get("whatif")
    if not w or not w.get("rows"):
        return
    g = w["gap_usd"]
    rate = w.get("usdcny") or 0

    def pct(x):
        return "—" if x is None else f'<span style="color:{UP if x >= 0 else DOWN}">{x:+.1%}</span>'

    with st.expander(f"假如全部照做，现在会怎样（{w['since'][5:]} 起，截至美东 {w['asof'][5:]}）", expanded=False):
        a, b, c = st.columns(3)
        a.markdown(_card("给过的建议", f"{w['n_advice']} 条", f"照做了 {w['n_followed']} 条"), unsafe_allow_html=True)
        if abs(g) < 0.01:
            c_main, c_sub, color = "持平", "照做和实际没有差别", None
        elif g > 0:
            c_main, c_sub, color = _signed(-g * rate, "¥", 0), f"照做会多赚 ${g:,.2f}", DOWN
        else:
            c_main, c_sub, color = _signed(-g * rate, "¥", 0), f"你的做法多赚 ${-g:,.2f}", UP
        b.markdown(_card("你的实际 vs 全部照做", c_main, c_sub, color), unsafe_allow_html=True)
        unplanned = [r for r in w["rows"] if r["kind"] == "计划外"]
        c.markdown(_card("计划外交易", f"{len(unplanned)} 笔", "和同样的钱买 QQQM 比较"), unsafe_allow_html=True)
        if (curve := w.get("curve")) and len(curve) > 1:
            import plotly.graph_objects as go
            fig = go.Figure()
            for key, name, color, dash in (("actual", "你的实际", "#2563eb", None), ("follow", "全部照做", "#f97316", "dot"),
                                           ("dca", "只定投指数（70/30）", "#9ca3af", "dash")):
                fig.add_scatter(x=[c["date"] for c in curve], y=[c[key] for c in curve], name=name,
                                line=dict(color=color, dash=dash, width=2.5 if key == "actual" else 2))
            fig.update_layout(height=260, margin=dict(l=0, r=0, t=30, b=0), hovermode="x unified",
                              title=dict(text="三本账的浮动盈亏（美元）", font=dict(size=14)),
                              legend=dict(orientation="h", y=-0.2), yaxis=dict(tickprefix="$"))
            st.plotly_chart(fig, config={"displayModeBar": False})
        stats = [x for x in w.get("stats", []) if any(x[k]["n"] for k in ("1天", "1周", "1月"))]
        if stats:
            st.markdown("**建议准不准**（买入类看之后涨没涨，卖出类看之后跌没跌）")
            st.markdown("".join(
                f'<div style="font-size:14px">{html.escape(x["signal"])}建议 {x["n"]} 条：'
                + "，".join(f'{k}后对了 {x[k]["right"]}/{x[k]["n"]}' for k in ("1天", "1周", "1月") if x[k]["n"])
                + "</div>" for x in stats), unsafe_allow_html=True)
        body = ""
        for r in w["rows"]:
            tag = ('<span style="background:#fef3c7;color:#92400e;border-radius:4px;padding:0 4px;font-size:12px">计划外</span> '
                   if r["kind"] == "计划外" else "")
            h = r.get("h") or {}
            cells = "".join(f'<td style="text-align:right">{pct(h.get(k))}</td>' for k in ("1天", "1周", "1月"))
            body += (f'<tr style="border-top:1px solid #eef0f3"><td style="white-space:nowrap">{r["date"][5:]}</td>'
                     f'<td>{tag}{html.escape(r["advice"])}<br><span style="color:#6b7280;font-size:12px">'
                     f'你：{html.escape(r["did"])}</span></td>'
                     f'{cells}<td style="text-align:right">{pct(r.get("total"))}</td></tr>'
                     + (f'<tr><td></td><td colspan="5" style="font-size:13px;padding-bottom:6px">→ {html.escape(r["note"])}</td></tr>'
                        if r.get("note") else ""))
        th = "".join(f'<th style="text-align:right">{k}</th>' for k in ("1天", "1周", "1月", "至今"))
        st.markdown('<div style="overflow-x:auto"><table style="width:100%;font-size:14px;border-collapse:collapse">'
                    '<tr style="color:#6b7280;font-size:12px"><th style="text-align:left">日期</th>'
                    f'<th style="text-align:left">建议 / 你的操作</th>{th}</tr>{body}</table></div>', unsafe_allow_html=True)
        st.caption("怎么算的：按建议当晚的美股收盘价当作假想成交价；1天/1周/1月是之后第 1、5、21 个交易日的涨跌，“至今”到最新收盘价。"
                   f"影响金额已扣佣金（按你历史成交的平均费率 {w.get('fee_rate', 0):.2%}）。计划外的买入和“同样的钱当天买 QQQM”比较；"
                   "“只定投指数”是把你每笔买入的钱按 70/30 买 QQQM/SPYM。几天、几周的对比运气成分很大，看满几个月才有参考意义。")


def _monthly_box(s, owner):
    try:
        snap = s.get_paper(owner)
    except cloud_api.CloudError:
        return
    r = ((snap or {}).get("payload") or {}).get("monthly")
    if not r:
        return
    rate = r.get("usdcny") or 0
    partial = f"（截至 {r['asof'][5:]}）" if r["asof"][:7] == r["month"] else ""
    with st.expander(f"月度复盘 · {r['month']}{partial}", expanded=False):
        cols = st.columns(3)
        for col, (k, name) in zip(cols, (("actual", "你的实际"), ("follow", "全部照做"), ("dca", "只定投指数"))):
            v = r["pnl"][k]
            col.markdown(_card(f"{name} · 本月", _signed(v * rate, "¥", 0), _signed(v, "$", 2), UP if v >= 0 else DOWN),
                         unsafe_allow_html=True)
        if r.get("market"):
            st.caption("同期市场：" + "，".join(f"{t} {v:+.1%}" for t, v in r["market"].items())
                       + "。一个月的涨跌基本是运气，长期坚持才看得出差别。")
        if c := r.get("coach"):
            ui.card(f'<div class="ui-note">AI 教练点评（Grok）</div>'
                    f'<div style="font-size:14px;line-height:1.8"><b>做得好：</b>{html.escape(c["good"])}'
                    + (f'<br><b>可以改进：</b>{html.escape(c["improve"])}' if c.get("improve") else "")
                    + f'<br><b>下个月记住：</b>{html.escape(c["next"])}</div>', f"border-left:3px solid {ui.ACT}")
        if r["n_advice"]:
            st.markdown(f"**照做情况**：{r['n_advice']} 条建议照做了 {r['n_followed']} 条")
        for x in r.get("missed", []) + [f"计划外：{u}" for u in r.get("unplanned", [])]:
            st.markdown(f'<div style="font-size:14px;color:#4b5563">· {html.escape(x)}</div>', unsafe_allow_html=True)
        st.markdown("**仓位检查**")
        st.markdown("".join(
            f'<div style="font-size:14px;line-height:1.7">{"✅" if x["ok"] else "⚠️"} {html.escape(x["item"])}：'
            f'{html.escape(x["value"])}{"　" + html.escape(x["tip"]) if x["tip"] else ""}</div>' for x in r["risk"]),
            unsafe_allow_html=True)
        if len(r.get("history", [])) > 1:
            import plotly.graph_objects as go
            fig = go.Figure()
            for key, name, color in (("actual", "你的实际", "#2563eb"), ("follow", "全部照做", "#f97316"),
                                     ("dca", "只定投指数", "#9ca3af")):
                fig.add_bar(x=[h["month"] for h in r["history"]], y=[h[key] for h in r["history"]], name=name,
                            marker_color=color)
            fig.update_layout(height=240, margin=dict(l=0, r=0, t=30, b=0), barmode="group",
                              title=dict(text="每月浮动盈亏变化（美元）", font=dict(size=14)),
                              legend=dict(orientation="h", y=-0.25), yaxis=dict(tickprefix="$"))
            st.plotly_chart(fig, config={"displayModeBar": False})


STANCE_COLORS = {"偏多": UP, "中性": "#6b7280", "偏空": DOWN}


def _review_box(s, owner):
    try:
        snap = s.get_paper(owner)
    except cloud_api.CloudError:
        return
    data = ((snap or {}).get("payload") or {}).get("reviews")
    if not data or not data.get("items"):
        return
    updated = pd.Timestamp(data["updated"]).tz_convert("Asia/Shanghai")
    with st.expander(f"每日持仓体检：看多 vs 看空（更新于 {updated:%m-%d %H:%M}）", expanded=False):
        ui.origin("ai_review")
        st.caption("由大模型根据行情、财务和新闻数据生成，**只是参考，不是信号**：今天该不该操作以上面的规则信号为准。")
        for t, r in data["items"].items():
            color = STANCE_COLORS.get(r["stance"], "#6b7280")
            st.markdown(
                f'<div style="display:flex;gap:10px;align-items:baseline;margin-top:8px">'
                f'<span style="background:{color};color:#fff;border-radius:6px;padding:2px 8px;font-weight:700">{html.escape(r["stance"])}</span>'
                f'<b style="font-size:17px">{html.escape(t)}</b><span style="color:#6b7280;font-size:13px">{html.escape(str(r.get("name", "")))} · '
                f'${r["price"]:,.2f} · 把握{html.escape(str(r.get("confidence", "")))} · 美东 {r["date"][5:]}</span></div>'
                f'<div style="font-size:15px;margin:4px 0 6px">{html.escape(str(r.get("summary", "")))}</div>', unsafe_allow_html=True)
            a, b = st.columns(2)
            a.markdown(f'<div style="padding:10px 12px;border-radius:10px;background:#fef2f2;height:100%">'
                       f'<b style="color:{UP}">看多理由</b><ul style="margin:4px 0 0;padding-left:18px;font-size:14px">'
                       + "".join(f"<li>{html.escape(x)}</li>" for x in r.get("bull") or []) + "</ul></div>", unsafe_allow_html=True)
            b.markdown(f'<div style="padding:10px 12px;border-radius:10px;background:#f0fdf4;height:100%">'
                       f'<b style="color:{DOWN}">看空理由</b><ul style="margin:4px 0 0;padding-left:18px;font-size:14px">'
                       + "".join(f"<li>{html.escape(x)}</li>" for x in r.get("bear") or []) + "</ul></div>", unsafe_allow_html=True)
            extra = []
            if r.get("risks"):
                extra.append("<b>接下来留意：</b>" + "；".join(html.escape(x) for x in r["risks"]))
            if r.get("rule"):
                extra.append(f"<b>规则信号：</b>{html.escape(r['rule'])}")
            if r.get("vs_rule"):
                extra.append(f"<b>AI 对规则的看法：</b>{html.escape(r['vs_rule'])}")
            if extra:
                st.markdown('<div style="font-size:14px;line-height:1.6;margin:6px 0 4px">' + "<br>".join(extra) + "</div>",
                            unsafe_allow_html=True)
        tr = data.get("track") or {}
        by = tr.get("by") or {}
        scored = {k: v for k, v in by.items() if v.get("n")}
        if scored:
            st.markdown("**AI 看法的成绩**（偏多后跑赢 QQQM 算对，偏空后跑输算对，中性不计）："
                        + "，".join(f"{k}后对了 {v['right']}/{v['n']}" for k, v in scored.items()))
        else:
            st.caption(f"AI 已给出 {tr.get('n', 0)} 次看法，满 1 周后开始打分。成绩差就说明它不值得听。")


ACTION_COLORS = {"买入": UP, "小仓位试水": "#f97316", "观望": "#6b7280", "持有": "#6b7280", "减仓": "#0d9488", "卖出": DOWN}
VIEW_COLORS = {"偏多": UP, "中性": "#6b7280", "偏空": DOWN}


def _research_card(r):
    d = r["decision"]
    color = ACTION_COLORS.get(d.get("action"), "#6b7280")
    st.markdown(
        f'<div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">{ui.tag(d.get("action", ""), color)}'
        f'<b style="font-size:17px">{html.escape(r["ticker"])}</b><span class="ui-note">{html.escape(str(r.get("name", "")))} · '
        f'${r["price"]:,.2f} · 把握{html.escape(str(d.get("confidence", "")))} · 美东 {r["date"][5:]}</span></div>'
        f'<div style="font-size:16px;font-weight:600;margin:6px 0">{html.escape(str(d.get("summary", "")))}</div>',
        unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["结论和计划", "三位分析师", "多空辩论"])
    with t1:
        st.markdown("".join(f"- {html.escape(x)}\n" for x in d.get("reasons") or []))
        rows = [(k, d.get(v)) for k, v in (("仓位", "position"), ("怎么做", "plan"), ("认错离场", "stop"),
                                           ("会改变判断", "change"), ("适合持有", "horizon")) if d.get(v)]
        st.markdown('<table class="ui-table">' + "".join(
            f'<tr><td style="white-space:nowrap;color:{ui.MUTED}">{k}</td><td>{html.escape(str(v))}</td></tr>' for k, v in rows)
                    + "</table>", unsafe_allow_html=True)
    with t2:
        for k, rep in r["reports"].items():
            extra = [f"{label}：{rep[f]}" for f, label in (("valuation", "估值"), ("support", "支撑"), ("resistance", "压力"))
                     if rep.get(f)]
            st.markdown(f'{ui.tag(rep.get("view", ""), VIEW_COLORS.get(rep.get("view"), "#6b7280"))} <b>{k}分析师</b>',
                        unsafe_allow_html=True)
            st.markdown("".join(f"- {html.escape(x)}\n" for x in rep.get("points", []) + extra + rep.get("events", [])))
    with t3:
        a, b = st.columns(2)
        for col, key, label, bg, fg in ((a, "bull", "看多研究员", "#fef2f2", UP), (b, "bear", "看空研究员", "#f0fdf4", DOWN)):
            side = r["debate"][key]
            col.markdown(f'<div style="padding:10px 12px;border-radius:10px;background:{bg}"><b style="color:{fg}">{label}</b>'
                         f'<ul style="margin:4px 0 0;padding-left:18px;font-size:14px">'
                         + "".join(f"<li>{html.escape(x)}</li>" for x in side.get("points", []))
                         + f'</ul><div class="ui-note">反驳对方：{html.escape(str(side.get("rebut", "")))}</div></div>',
                         unsafe_allow_html=True)


def _ai_desk(s):
    try:
        snap = s.get_paper()
    except cloud_api.CloudError:
        st.caption("暂时连不上数据库，稍后再试。")
        return
    payload = (snap or {}).get("payload") or {}
    reqs, answers = payload.get("requests") or [], payload.get("answers") or {}
    with st.form("ai_ask", clear_on_submit=True):
        kind = st.radio("想做什么", ["个股研究", "问一个问题"], horizontal=True, label_visibility="collapsed")
        q = st.text_input("内容", placeholder="个股研究：输入名字或代码，如 英伟达、AAPL；问问题：如 为什么利率涨了纳指会跌？",
                          label_visibility="collapsed")
        if st.form_submit_button("提交", type="primary") and q.strip():
            fresh = (s.get_paper() or {}).get("payload") or {}
            fresh["requests"] = (fresh.get("requests") or [])[-29:] + [{
                "id": secrets.token_hex(4), "kind": "research" if kind == "个股研究" else "ask", "q": q.strip()[:200],
                "at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat()}]
            s.put_paper(fresh)
            st.rerun()
    st.caption("你的 Mac 每 2 分钟看一次有没有新问题；个股研究要 6 次 AI 调用，大约 3–5 分钟。"
               "Mac 需要开机，并连着能访问网站数据库的网络（目前公司网络可以）。")
    if not reqs:
        return
    if st.button("刷新结果"):
        st.rerun()
    for i, r in enumerate(reversed(reqs[-8:])):
        a = answers.get(r["id"]) or {}
        label = ("个股研究" if r["kind"] == "research" else "问答") + f" · {r['q']}"
        when = pd.Timestamp(r["at"]).tz_convert("Asia/Shanghai")
        if a.get("status") == "done":
            res = a["result"]
            head = f"{res['decision']['action']} · " if r["kind"] == "research" else ""
            with st.expander(f"{head}{label}（{when:%m-%d %H:%M}）", expanded=i == 0):
                if r["kind"] == "research":
                    _research_card(res)
                else:
                    st.markdown(res["answer"])
        else:
            state = {"running": "AI 正在研究…", "error": f"没成功：{a.get('error', '')}"}.get(a.get("status"), "排队中，等你的 Mac 接单")
            st.markdown(f'<div class="ui-row"><span class="ui-note">{when:%m-%d %H:%M}</span>'
                        f'<span style="flex:1">{html.escape(label)}</span><span class="ui-note">{html.escape(state)}</span></div>',
                        unsafe_allow_html=True)
    st.caption("AI 会出错。个股研究的每条建议都会被记录，1 周、1 个月后和纳指比，成绩显示在下面的「每日持仓体检」里。")


def _paper_box(s, owner):
    try:
        snap = s.get_paper(owner)
    except cloud_api.CloudError:
        return
    if not snap:
        return
    p = snap["payload"]
    st_ = p.get("stats") or {}
    bt = p.get("backtest", {})
    updated = pd.Timestamp(snap["updated_at"]).tz_convert("Asia/Shanghai")
    with st.expander(f"短线实验（模拟盘，不花钱）· 更新于 {updated:%m-%d %H:%M}", expanded=False):
        st.warning("**只记账、不下单，不构成任何买卖建议。** 跑满 2 个月（约 40 笔已结束）再评估。"
                   f"历史回测 {bt.get('次数', '—')} 次：胜率 {bt.get('胜率', 0):.0%}，平均 {bt.get('平均', 0):+.1%}，"
                   f"但中位数 {bt.get('中位数', 0):+.1%}——多数时候小亏，靠极少数暴涨股拉高平均，接近买彩票。")
        a, b, c = st.columns(3)
        a.markdown(_card("已记录信号", f"{st_.get('信号', 0)}",
                         f"{st_.get('已卖出', 0)} 笔已结束 · {st_.get('持有中', 0)} 笔持有中"), unsafe_allow_html=True)
        for col, label, key, sub in ((b, "理论账", "理论账盈亏", f"每个信号 ¥{p.get('stake', 1000):,}"),
                                     (c, "实际账", "实际账盈亏", f"最多同时 {p.get('slots', 3)} 只")):
            v = st_.get(key, 0.0) or 0.0
            col.markdown(_card(label, _signed(v, "¥", 0), sub, UP if v >= 0 else DOWN), unsafe_allow_html=True)
        if not p.get("trades"):
            st.caption(f"从 {p.get('start')} 开始记录，还没有触发信号。")
        st.markdown(f"**今晚观察名单**（数据截至美东 {p.get('asof') or '—'}；开盘价 ≥ 触发价才记一笔模拟买入）")
        if p.get("watch"):
            w = pd.DataFrame(p["watch"])
            st.dataframe(pd.DataFrame({
                "代码": w["ticker"], "昨收": w["close"].map("${:,.2f}".format), "触发价": w["trigger"].map("${:,.2f}".format),
                "近3日最大单日涨幅": w["big_day"].map("{:+.0%}".format), "放量倍数": w["vol_x"].map("{:.1f}x".format),
            }), hide_index=True)
        else:
            st.caption("今天没有符合条件的股票。")
        if p.get("trades"):
            t = pd.DataFrame(p["trades"])
            st.markdown("**模拟成交记录**")
            st.dataframe(pd.DataFrame({
                "买入日": t["date"], "代码": t["ticker"], "买入价": t["entry"].map("${:,.2f}".format),
                "卖出日": t["exit_date"].fillna("—"),
                "卖出价": pd.to_numeric(t["exit"], errors="coerce").map(lambda x: "—" if pd.isna(x) else f"${x:,.2f}"),
                "状态": t["status"], "收益": t["ret"].map("{:+.1%}".format),
                "实际账": t["real"].map({True: "✓", False: "满仓跳过"}),
            }), hide_index=True)
        r = p.get("rules", {})
        st.caption(f"规则：美股市值 3–45 亿美元的中小盘；过去 {r.get('lookback', 3)} 个交易日内有过单日 ≥+{r.get('big', 0.1):.0%} 大涨、"
                   f"且前一交易日放量 ≥{r.get('vol_mult', 3):.0f} 倍的进入观察名单；当晚开盘跳空 ≥+{r.get('gap', 0.05):.0%} 记模拟买入，"
                   f"第 {p.get('hold', 5)} 个交易日开盘卖出；已扣来回成本 {p.get('cost', 0.003):.1%}。")

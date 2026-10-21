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
    st.markdown("登录后可以记录**自己的**入金和成交，网站自动算持仓和盈亏。每个人只能看到自己的数据。")
    st.caption("请设置一个**新的**密码，不要和银行、邮箱的密码相同。本网站永远不会向你索要银行账号密码。")
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
    return (f'<div style="padding:14px 16px;border-radius:12px;background:#f9fafb;height:100%">'
            f'<div style="color:#6b7280;font-size:14px">{label}</div>'
            f'<div style="font-size:28px;font-weight:700;{style}line-height:1.3">{main}</div>'
            f'<div style="color:#6b7280;font-size:13px">{sub}</div></div>')


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
    else:
        st.caption("今日信号在「今天」页。")
    _whatif_box(s, owner)
    if not dep and not tr:
        st.markdown("这个账户还没有记录。" if readonly else
                    "还没有记录。钱到账后先在下面**记一笔入金**，买入成交后**记一笔成交**。")
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
        if len(pos):
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
            st.markdown("**持仓**")
            st.markdown(pd.DataFrame(rows).to_html(index=False, escape=False), unsafe_allow_html=True)
            st.caption("美股以美元交易，现价和成本保留美元；市值和盈亏按今日汇率折成人民币，灰色小字为美元。"
                       "价格为最近收盘价，每 15 分钟更新；以银行 App 显示为准。")

    _paper_box(s, owner)
    st.divider()
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
    _share_box(s, shares)


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

    with st.expander(f"假如照做了 · 从 {w['since'][5:]} 起的建议回溯（数据截至美东 {w['asof'][5:]}）", expanded=True):
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
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
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
    with st.expander(f"短线实验（模拟盘，不花钱）· 更新于 {updated:%m-%d %H:%M}", expanded=True):
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

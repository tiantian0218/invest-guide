"""公开网站的「我的账户」页：注册 / 登录 / 持仓盈亏 / 记账。数据存在 Supabase，每个用户只能看到自己的。"""
import pandas as pd
import streamlit as st

import cloud_api
import market_data

UP, DOWN = "#d62728", "#16a34a"
CORE = ["QQQM", "SPYM"]


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


def _session():
    tok = st.session_state.get("sb_tokens")
    if not tok:
        return None

    def keep(new):
        st.session_state["sb_tokens"] = new
    return cloud_api.Session(tok, on_refresh=keep)


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
            if st.form_submit_button("登录", type="primary"):
                try:
                    st.session_state["sb_tokens"] = cloud_api.sign_in(email.strip(), pw)
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


def account_tab():
    if not cloud_api.enabled():
        st.info("账户功能还在准备中，敬请期待。")
        return
    s = _session()
    if s is None:
        _login_box()
        return
    c1, c2 = st.columns([4, 1])
    c1.caption(f"已登录：{s.email}")
    if c2.button("退出登录"):
        st.session_state.pop("sb_tokens", None)
        st.rerun()
    try:
        dep, tr = s.rows("deposits"), s.rows("trades")
    except cloud_api.CloudError as e:
        st.session_state.pop("sb_tokens", None)
        st.error(f"登录已过期，请重新登录（{e}）")
        return

    tickers = tuple(sorted({r["ticker"] for r in tr} | set(CORE)))
    try:
        prices, (usdhkd, usdcny) = _prices(tickers), _fx()
    except Exception:
        prices, usdhkd, usdcny = {}, None, None
        st.warning("行情暂时获取失败，市值按成本显示。")
    pos, sm = summarize(dep, tr, prices)

    if not dep and not tr:
        st.markdown("还没有记录。钱到账后先在下面**记一笔入金**，买入成交后**记一笔成交**。")
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
                    "代码": r["代码"], "股数": f"{r['股数']:g}",
                    "现价（美元）": f"${r['现价']:,.2f}" if pd.notna(r["现价"]) else "—",
                    "平均成本（美元）": f"${r['平均成本']:,.2f}",
                    "市值": mv_cell, "盈亏": pnl_cell,
                    "盈亏%": f'<span style="color:{color}">{pct:+.2f}%</span>' if pct is not None else "—",
                })
            st.markdown("**持仓**")
            st.markdown(pd.DataFrame(rows).to_html(index=False, escape=False), unsafe_allow_html=True)
            st.caption("美股以美元交易，现价和成本保留美元；市值和盈亏按今日汇率折成人民币，灰色小字为美元。"
                       "价格为最近收盘价，每 15 分钟更新；以银行 App 显示为准。")

    st.divider()
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

    for table, label, cols in (("deposits", "入金记录", {"date": "日期", "cny": "人民币", "usd": "美元", "note": "备注"}),
                               ("trades", "成交记录", {"date": "日期", "ticker": "代码", "shares": "股数", "price_usd": "价格",
                                                    "fee_usd": "佣金", "note": "备注"})):
        rows = dep if table == "deposits" else tr
        if not rows:
            continue
        with st.expander(f"{label}（{len(rows)} 条）"):
            df = pd.DataFrame(rows)
            st.dataframe(df[list(cols)].rename(columns=cols), hide_index=True)
            pick = st.multiselect("删除记错的记录", df["id"], key=f"del_{table}",
                                  format_func=lambda i: " · ".join(str(v) for v in df.loc[df["id"] == i, list(cols)[:-1]].iloc[0]))
            if pick and st.button("确认删除", key=f"btn_{table}"):
                s.delete(table, pick)
                st.rerun()

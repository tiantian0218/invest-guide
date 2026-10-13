"""Supabase 登录与数据读写（只用 REST 接口，不依赖额外 SDK）。

配置来源：网站上读 Streamlit Secrets 的 [supabase] url / anon_key；本机读 cloud/config.json。
anon_key 是可公开的前端密钥，数据隔离靠数据库的行级安全规则；service_role 密钥永远不要放进来。
"""
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
LOCAL_CFG = ROOT / "cloud" / "config.json"
TABLES = {
    "deposits": ["date", "cny", "usd", "note"],
    "trades": ["date", "ticker", "shares", "price_usd", "fee_usd", "note"],
}


class CloudError(Exception):
    pass


def _clean(url):
    url = url.strip().rstrip("/")
    return url[: -len("/rest/v1")] if url.endswith("/rest/v1") else url


def config():
    try:
        import streamlit as st
        s = st.secrets.get("supabase")
        if s and s.get("url") and s.get("anon_key"):
            return _clean(s["url"]), s["anon_key"].strip()
    except Exception:
        pass
    if LOCAL_CFG.exists():
        c = json.loads(LOCAL_CFG.read_text())
        return _clean(c["url"]), c["anon_key"].strip()
    return None


def enabled():
    return config() is not None


def _msg(r):
    try:
        j = r.json()
    except ValueError:
        return r.text[:200]
    raw = j.get("msg") or j.get("error_description") or j.get("message") or j.get("error") or str(j)
    zh = {
        "Invalid login credentials": "邮箱或密码不对",
        "Email not confirmed": "邮箱还没验证，请先点击注册邮件里的确认链接",
        "User already registered": "这个邮箱已经注册过了，请直接登录",
    }
    for k, v in zh.items():
        if k in raw:
            return v
    if "Password should be" in raw:
        return "密码太短，至少 8 位"
    if "rate limit" in raw.lower():
        return "操作太频繁，请过一会儿再试"
    return raw


def _auth(path, body, **params):
    url, key = config()
    params = {k: v for k, v in params.items() if v}
    r = requests.post(f"{url}/auth/v1/{path}", json=body, params=params, headers={"apikey": key}, timeout=20)
    if r.status_code >= 400:
        raise CloudError(_msg(r))
    return r.json() if r.text else {}


def sign_up(email, password, redirect=None):
    return _auth("signup", {"email": email, "password": password}, redirect_to=redirect)


def sign_in(email, password):
    return _auth("token", {"email": email, "password": password}, grant_type="password")


def refresh(refresh_token):
    return _auth("token", {"refresh_token": refresh_token}, grant_type="refresh_token")


def logout(access_token):
    """让这次登录在服务器端失效（续期令牌一并作废）。网络失败时忽略，本地照样退出。"""
    url, key = config()
    try:
        # scope=local：只退出当前设备；默认 global 会把电脑同步等其他设备一起踢下线
        requests.post(f"{url}/auth/v1/logout", params={"scope": "local"}, headers={"apikey": key, "Authorization": f"Bearer {access_token}"},
                      timeout=10)
    except requests.RequestException:
        pass


def reset_password(email, redirect=None):
    return _auth("recover", {"email": email}, redirect_to=redirect)


def verify_recovery(email, code):
    """用重置邮件里的 6 位验证码换取登录令牌（Supabase 邮件模板需包含 {{ .Token }}）。"""
    return _auth("verify", {"type": "recovery", "email": email, "token": code.strip()})


class Session:
    """一个已登录用户。access_token 过期时用 refresh_token 自动续期。"""

    def __init__(self, tokens, on_refresh=None):
        self.tokens = tokens
        self.on_refresh = on_refresh

    @property
    def email(self):
        return (self.tokens.get("user") or {}).get("email", "")

    def _req(self, method, path, retry=True, **kw):
        url, key = config()
        h = {"apikey": key, "Authorization": f"Bearer {self.tokens['access_token']}",
             "Content-Type": "application/json", "Prefer": "return=representation"}
        r = requests.request(method, f"{url}/rest/v1/{path}", headers=h, timeout=20, **kw)
        if r.status_code == 401 and retry:
            self.tokens = refresh(self.tokens["refresh_token"])
            if self.on_refresh:
                self.on_refresh(self.tokens)
            return self._req(method, path, retry=False, **kw)
        if r.status_code >= 400:
            raise CloudError(_msg(r))
        return r.json() if r.text else []

    def update_password(self, password):
        url, key = config()
        r = requests.put(f"{url}/auth/v1/user", json={"password": password}, timeout=20,
                         headers={"apikey": key, "Authorization": f"Bearer {self.tokens['access_token']}"})
        if r.status_code >= 400:
            raise CloudError(_msg(r))

    def rows(self, table, include_deleted=False):
        q = f"{table}?select=*&order=date.asc,id.asc"
        if not include_deleted:
            q += "&deleted=eq.false"
        return self._req("GET", q)

    def insert(self, table, rows):
        rows = [{k: r[k] for k in TABLES[table] if k in r} for r in rows]
        return self._req("POST", table, json=rows) if rows else []

    def delete(self, table, ids):
        if not ids:
            return []
        return self._req("PATCH", f"{table}?id=in.({','.join(str(i) for i in ids)})", json={"deleted": True})

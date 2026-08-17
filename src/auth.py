"""Supabase 认证模块 — 替换本地 users.json"""

from typing import Optional
import streamlit as st
from supabase import create_client, Client

SUPABASE_URL = "https://cxxoxbambqkpwpldsrnj.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_64MeU_WIVNWzcksKIUnWww_ywJtaEe9"

# ---------- 惰性初始化 ----------
_supabase: Client = None

def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _supabase


# ---------- RPC 封装 ----------

def _rpc(name: str, params: dict) -> dict:
    """调用 Supabase RPC 并返回 dict"""
    try:
        res = get_supabase().rpc(name, params).execute()
        # res.data 可能是单个 dict 或 list
        data = res.data
        if isinstance(data, list) and len(data) == 1:
            return data[0]
        if isinstance(data, dict):
            return data
        if data is None:
            return {"success": False, "error": "无响应"}
        return data
    except Exception as e:
        return {"success": False, "error": str(e)}


def login(username: str, password: str) -> dict:
    """登录，返回 {success, username, role, token} 或 {success:False, error}"""
    return _rpc("login_user", {"p_username": username, "p_password": password})


def register(username: str, password: str) -> dict:
    return _rpc("register_user", {"p_username": username, "p_password": password})


def validate_session(token: str) -> dict:
    return _rpc("validate_session", {"p_token": token})


def logout(token: str) -> dict:
    return _rpc("logout_user", {"p_token": token})


def list_users(token: str) -> list:
    res = _rpc("list_users", {"p_token": token})
    if isinstance(res, list):
        return res
    return []


def update_user_role(token: str, username: str, role: str) -> dict:
    return _rpc("update_user_role", {"p_token": token, "p_username": username, "p_role": role})


def delete_user(token: str, username: str) -> dict:
    return _rpc("delete_user", {"p_token": token, "p_username": username})


def change_password(token: str, old_pw: str, new_pw: str) -> dict:
    return _rpc("change_password", {"p_token": token, "p_old_password": old_pw, "p_new_password": new_pw})


def reset_user_password(token: str, username: str, new_pw: str) -> dict:
    return _rpc("reset_user_password", {"p_token": token, "p_username": username, "p_new_password": new_pw})


def export_users(token: str) -> list:
    res = _rpc("export_users", {"p_token": token})
    if isinstance(res, list):
        return res
    return []


def import_users(token: str, users: list) -> dict:
    return _rpc("import_users", {"p_token": token, "p_users_json": users})


def get_preference(token: str, key: str) -> Optional[str]:
    """读取用户偏好值，未设置返回 None"""
    res = _rpc("get_preference", {"p_token": token, "p_key": key})
    if isinstance(res, dict) and res.get("success"):
        return res.get("value")
    return None


def set_preference(token: str, key: str, value: str) -> dict:
    """写入用户偏好值"""
    return _rpc("set_preference", {"p_token": token, "p_key": key, "p_value": value})


# ---------- Session 持久化（URL query params）----------

def set_session_token(token: str):
    """把 session token 写入 URL，刷新不丢"""
    st.query_params["token"] = token


def get_session_token() -> Optional[str]:
    """从 URL 读取 session token"""
    return st.query_params.get("token")


def clear_session_token():
    """清除 URL 中的 token"""
    if "token" in st.query_params:
        del st.query_params["token"]


def restore_session() -> Optional[dict]:
    """页面加载时尝试恢复登录态，返回 {username, role, token} 或 None"""
    token = get_session_token()
    if not token:
        return None
    res = validate_session(token)
    if res.get("success"):
        return {"username": res["username"], "role": res["role"], "token": token}
    else:
        clear_session_token()
        return None


# ---------- 系统健康检查（预警界面用）----------

def check_supabase_health() -> dict:
    """主动探测 Supabase 后端可用性与 API key 有效性。

    返回字段：
      online        : bool  服务器是否可达
      api_key_valid : bool  anon key 是否有效
      status        : str   "ok" / "warn" / "error"
      message       : str   人类可读说明
      latency_ms    : int   响应耗时（毫秒），失败时为 None
      checked_at    : str   探测时间
    """
    import time as _t
    result = {"online": False, "api_key_valid": False, "status": "error",
              "message": "", "latency_ms": None,
              "checked_at": _t.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        t0 = _t.time()
        get_supabase().rpc("validate_session", {"p_token": "__health_probe__"}).execute()
        result["latency_ms"] = round((_t.time() - t0) * 1000)
        result["online"] = True
        result["api_key_valid"] = True
        result["status"] = "ok"
        result["message"] = "后端在线，API key 有效"
    except Exception as e:
        err = str(e)
        if any(k in err for k in ("401", "403", "Unauthorized", "Invalid API key", "invalid key")):
            result["online"] = True
            result["api_key_valid"] = False
            result["status"] = "warn"
            result["message"] = "服务器在线，但 API key 无效或已过期（HTTP 401/403）"
        elif any(k in err.lower() for k in ("connect", "timeout", "resolve", "network")):
            result["message"] = "无法连接服务器：项目可能已暂停/过期"
        else:
            result["online"] = True
            result["status"] = "warn"
            result["message"] = f"探测异常：{err[:120]}"
    return result

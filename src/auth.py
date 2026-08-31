"""Supabase 认证模块 — 替换本地 users.json"""

import json
import os
from typing import Optional
import streamlit as st
from supabase import create_client, Client


def _read_secret(key: str) -> Optional[str]:
    """读取 Supabase 配置：优先级 st.secrets > 环境变量。

    企业部署要求：必须通过 .streamlit/secrets.toml 或平台密钥注入，
    代码中不再内置任何默认密钥（旧 key 已废弃并轮换）。
    """
    try:
        val = st.secrets.get("supabase", {}).get(key)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(key) or None


# Supabase 连接配置：仅从 st.secrets / 环境变量读取，未配置时启动相关功能会给出明确提示。
SUPABASE_URL = _read_secret("SUPABASE_URL") or ""
SUPABASE_ANON_KEY = _read_secret("SUPABASE_ANON_KEY") or ""

# ---------- 惰性初始化 ----------
_supabase: Client = None

_MISSING_CONFIG_MSG = (
    "Supabase 未配置：请在 .streamlit/secrets.toml（本地）或部署平台的 Secrets 中"
    "设置 SUPABASE_URL 与 SUPABASE_ANON_KEY")


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            raise RuntimeError(_MISSING_CONFIG_MSG)
        _supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _supabase


# ---------- RPC 封装 ----------

def _rpc(name: str, params: dict):
    """调用 Supabase RPC 并原样返回 data（list 或 dict，不做类型改写）。

    注意：json_agg 返回的 list 即使只有一个元素也保持 list，
    避免调用方无法区分「单条记录的 dict」和「单元素列表」。
    """
    try:
        res = get_supabase().rpc(name, params).execute()
        data = res.data
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


# ---------- Session 持久化（Cookie 优先，URL query params 兜底）----------

def _cookie_token() -> Optional[str]:
    """从浏览器 Cookie 读取 token（Streamlit 的只读 Cookie API）。"""
    try:
        tok = st.context.cookies.get("token")
        return tok or None
    except Exception:
        return None


def _set_cookie_js(token: str) -> None:
    """通过同源 iframe 的 JS 写入 Cookie（Streamlit 暂无 Python 写 Cookie API）。"""
    try:
        import streamlit.components.v1 as components
        safe = json.dumps(token)
        components.html(
            "<script>try{document.cookie='token='+encodeURIComponent(" + safe +
            ")+';path=/;max-age=604800;SameSite=Lax';}catch(e){}</script>",
            height=0,
        )
    except Exception:
        pass


def _clear_cookie_js() -> None:
    """通过 JS 清除 Cookie。"""
    try:
        import streamlit.components.v1 as components
        components.html(
            "<script>try{document.cookie='token=;path=/;max-age=0';}catch(e){}</script>",
            height=0,
        )
    except Exception:
        pass


def set_session_token(token: str):
    """写入 session token：Cookie 为主；URL query param 仅作瞬时兜底。

    下次页面加载若 Cookie 生效，restore_session() 会自动清掉 URL 中的 token。
    """
    _set_cookie_js(token)
    try:
        st.query_params["token"] = token
    except Exception:
        pass


def get_session_token() -> Optional[str]:
    """优先从 Cookie 读取 token，回退到 URL query param（兼容旧链接）。"""
    return _cookie_token() or st.query_params.get("token")


def clear_session_token():
    """清除 Cookie 与 URL 中的 token。"""
    _clear_cookie_js()
    try:
        if "token" in st.query_params:
            del st.query_params["token"]
    except Exception:
        pass


def restore_session() -> Optional[dict]:
    """页面加载时尝试恢复登录态，返回 {username, role, token} 或 None"""
    token = get_session_token()
    if not token:
        return None
    res = validate_session(token)
    if res.get("success"):
        # Cookie 生效后，清理 URL 中的兜底 token（token 不再长期暴露在 URL）
        if _cookie_token():
            try:
                if "token" in st.query_params:
                    del st.query_params["token"]
            except Exception:
                pass
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


# ---------- 用户反馈（意见箱 + 仿真结果反馈）----------

def _normalize_list(res) -> list:
    """把 RPC 返回值归一化为 list（处理 _rpc 对单元素 list 的误判）。"""
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        if res.get("success") is False:
            return []
        return [res]
    return []


def submit_feedback(token: str, category: str, title: str, content: str,
                    related_run: str = None) -> dict:
    return _rpc("submit_feedback", {"p_token": token, "p_category": category,
                                    "p_title": title, "p_content": content,
                                    "p_related_run": related_run})


def list_my_feedbacks(token: str) -> list:
    return _normalize_list(_rpc("list_my_feedbacks", {"p_token": token}))


def list_feedbacks(token: str) -> list:
    return _normalize_list(_rpc("list_feedbacks", {"p_token": token}))


def update_feedback_status(token: str, feedback_id: str, status: str) -> dict:
    return _rpc("update_feedback_status", {"p_token": token, "p_id": feedback_id,
                                           "p_status": status})


def reply_feedback(token: str, feedback_id: str, reply: str) -> dict:
    return _rpc("reply_feedback", {"p_token": token, "p_id": feedback_id,
                                   "p_reply": reply})


def delete_feedback(token: str, feedback_id: str) -> dict:
    return _rpc("delete_feedback", {"p_token": token, "p_id": feedback_id})


def update_feedback_display_time(token: str, feedback_id: str, display_time: str) -> dict:
    """管理员修改反馈的显示时间（display_time 为空表示恢复原始时间）。"""
    return _rpc("update_feedback_display_time", {
        "p_token": token, "p_id": feedback_id, "p_display_time": display_time})


# ---------- 操作审计 ----------

def log_action(token: str, action: str, detail: dict = None) -> dict:
    """写入操作审计日志（audit_log 表，由 migrations/05 创建）。

    供应用层记录仿真运行、数据导入导出等非认证类事件；
    登录/角色变更/反馈处理等关键操作已在 SQL RPC 内自动审计。
    """
    return _rpc("log_action", {
        "p_token": token, "p_action": action, "p_detail": detail or {}})


# ---------- 仿真运行记录（migrations/06）----------

def save_sim_run(token: str, strategy: str, params: dict, env: dict,
                 metrics, layout_key: str = None, demand_source: str = None) -> dict:
    """持久化一次仿真运行结果（metrics 可为 dict 或 list）。"""
    return _rpc("save_sim_run", {
        "p_token": token, "p_strategy": strategy,
        "p_params": params or {}, "p_env": env or {},
        "p_metrics": metrics if metrics is not None else {},
        "p_layout_key": layout_key, "p_demand_source": demand_source})


def list_sim_runs(token: str, all_users: bool = False, limit: int = 200) -> list:
    """查询仿真运行记录：本人记录；管理员 all_users=True 时查全部。"""
    res = _rpc("list_sim_runs", {
        "p_token": token, "p_all": bool(all_users), "p_limit": int(limit)})
    if isinstance(res, list):
        return res
    return []


def delete_sim_run(token: str, run_id: str) -> dict:
    """删除运行记录（管理员可删任意；本人只能删自己的）。"""
    return _rpc("delete_sim_run", {"p_token": token, "p_id": run_id})

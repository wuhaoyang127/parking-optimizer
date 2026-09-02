"""auth 包：用户账号 RPC（登录/注册/角色/密码/偏好）。"""
from typing import Optional

from auth._base import _rpc, _rpc_with_retry


def login(username: str, password: str) -> dict:
    """登录，返回 {success, username, role, token} 或 {success:False, error}"""
    return _rpc("login_user", {"p_username": username, "p_password": password})


def register(username: str, password: str) -> dict:
    return _rpc("register_user", {"p_username": username, "p_password": password})


def validate_session(token: str) -> dict:
    return _rpc_with_retry("validate_session", {"p_token": token})


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
    res = _rpc_with_retry("get_preference", {"p_token": token, "p_key": key})
    if isinstance(res, dict) and res.get("success"):
        return res.get("value")
    return None


def set_preference(token: str, key: str, value: str) -> dict:
    """写入用户偏好值"""
    return _rpc("set_preference", {"p_token": token, "p_key": key, "p_value": value})

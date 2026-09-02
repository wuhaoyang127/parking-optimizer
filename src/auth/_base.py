"""auth 包：Supabase 配置读取、连接池与 RPC 基础封装。"""
import json
import os
import time
from typing import Optional
import streamlit as st
from supabase import create_client, Client
import httpx


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


def _is_transient_net(e: Exception) -> bool:
    """网络瞬时错误（连接被重置/超时/断连，如 WinError 10053）。"""
    if isinstance(e, httpx.HTTPError):
        return True
    return isinstance(e, (ConnectionError, TimeoutError, OSError))


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


def _rpc_with_retry(name: str, params: dict, *, tries: int = 4, backoff: float = 1.0):
    """带网络自愈的 RPC（仅用于只读/幂等调用）。

    公网到 Supabase 的连接可能被代理/负载均衡器重置（WinError 10053），
    遇到瞬时网络错误自动退避重试并重建连接池；非瞬时错误按原契约返回错误 dict。
    """
    global _supabase
    for i in range(tries):
        try:
            res = get_supabase().rpc(name, params).execute()
            data = res.data
            if data is None:
                return {"success": False, "error": "无响应"}
            return data
        except Exception as e:
            if not _is_transient_net(e) or i == tries - 1:
                return {"success": False, "error": str(e)}
            time.sleep(backoff)
            backoff *= 1.5
            _supabase = None

"""auth 包：系统健康检查。"""
from auth._base import get_supabase


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


def check_driver_health() -> dict:
    """探测车主端（Render）在线状态与研究运行时可用性。

    返回字段：
      web_online          : bool  车主端 /api/v2/health 是否 200
      research_runtime_ok : bool  /api/research/v1/capabilities 是否返回可用算法
      push_configured     : bool  是否配置了 API 地址 + ≥32 字符 publish token
      web_url             : str   车主端地址（未配置为空）
      message             : str   失败原因（截断）
      checked_at          : str   探测时间
    """
    import time as _t
    from driver_bridge.settings import setting
    result = {"web_online": False, "research_runtime_ok": False, "push_configured": False,
              "web_url": "", "message": "", "checked_at": _t.strftime("%Y-%m-%d %H:%M:%S")}
    web_url = setting("PARKING_DRIVER_WEB_URL")
    api_url = setting("PARKING_DRIVER_API_URL")
    result["web_url"] = web_url
    result["push_configured"] = bool(api_url and len(setting("PARKING_PUBLISH_TOKEN")) >= 32)

    if web_url:
        try:
            import urllib.request
            with urllib.request.urlopen(web_url.rstrip("/") + "/api/v2/health", timeout=8) as r:
                result["web_online"] = r.status == 200
        except Exception as e:
            result["message"] = f"网页健康探测失败：{str(e)[:140]}"

    if result["push_configured"]:
        try:
            from driver_bridge.client import call
            caps = call("/api/research/v1/capabilities")
            result["research_runtime_ok"] = bool(caps.get("supported"))
            if not result["research_runtime_ok"]:
                result["message"] = "研究运行时未返回可用算法"
        except Exception as e:
            msg = f"研究运行时探测失败：{str(e)[:140]}"
            result["message"] = (result["message"] + "；" + msg).strip("；")
    return result

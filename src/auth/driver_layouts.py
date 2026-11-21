"""布局推送：优先走 SECURITY DEFINER RPC（anon key 降权）；迁移未执行时回退 service key。"""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from auth._base import _read_secret, _rpc

LAYOUTS_KEY = "driver_layouts"


def _service_settings() -> tuple[str, str]:
    url = (_read_secret("SUPABASE_URL") or "").rstrip("/")
    key = _read_secret("SUPABASE_SERVICE_KEY") or ""
    if not url or not key:
        raise RuntimeError("未配置 SUPABASE_URL / SUPABASE_SERVICE_KEY")
    return url, key


def _service_rest(method: str, path: str, key: str, payload=None, prefer: str | None = None) -> str:
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Content-Type": "application/json", "User-Agent": "streamlit-server"}
    if prefer:
        headers["Prefer"] = prefer
    req = Request(_service_settings()[0] + "/rest/v1/" + path, method=method,
                  data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
                  headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError("Supabase 写入失败: " + exc.read(2000).decode("utf-8", "replace")) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("网络错误: " + str(exc)) from None


def list_driver_layouts(token: str) -> list:
    """读取已推送布局；优先 RPC，迁移未执行时回退 service key。"""
    res = _rpc("list_driver_layouts", {"p_token": token})
    if isinstance(res, list):
        return res
    _, key = _service_settings()
    body = _service_rest("GET", f"app_settings?key=eq.{LAYOUTS_KEY}&select=value", key)
    rows = json.loads(body)
    if not rows:
        return []
    val = rows[0].get("value")
    return val if isinstance(val, list) else []


def push_driver_layout(token: str, layout: dict) -> bool:
    """追加/覆盖一个布局（按 id）；优先 RPC，迁移未执行时回退 service key。"""
    res = _rpc("push_driver_layout", {"p_token": token, "p_layout": layout})
    if isinstance(res, dict) and res.get("success"):
        return True
    _, key = _service_settings()
    items = [x for x in list_driver_layouts(token) if x.get("id") != layout.get("id")]
    items.append(layout)
    _service_rest("POST", "app_settings", key, payload={"key": LAYOUTS_KEY, "value": items},
                  prefer="resolution=merge-duplicates")
    return True

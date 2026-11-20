"""布局推送：把研究端自定义布局写入 Supabase（service_role 直连 app_settings）。"""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from auth._base import _read_secret

LAYOUTS_KEY = "driver_layouts"


def _settings() -> tuple[str, str]:
    url = (_read_secret("SUPABASE_URL") or "").rstrip("/")
    key = _read_secret("SUPABASE_SERVICE_KEY") or ""
    if not url or not key:
        raise RuntimeError("未配置 SUPABASE_URL / SUPABASE_SERVICE_KEY")
    return url, key


def _rest(method: str, path: str, key: str, payload=None) -> str:
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Content-Type": "application/json", "User-Agent": "streamlit-server"}
    req = Request(_settings()[0] + "/rest/v1/" + path, method=method,
                  data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
                  headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError("Supabase 写入失败: " + exc.read(2000).decode("utf-8", "replace")) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("网络错误: " + str(exc)) from None


def list_driver_layouts() -> list:
    """读取已推送的布局列表；无记录返回 []。"""
    _, key = _settings()
    body = _rest("GET", f"app_settings?key=eq.{LAYOUTS_KEY}&select=value", key)
    rows = json.loads(body)
    if not rows:
        return []
    val = rows[0].get("value")
    return val if isinstance(val, list) else []


def push_driver_layout(layout: dict) -> bool:
    """追加/覆盖一个布局（按 id）。"""
    _, key = _settings()
    items = [x for x in list_driver_layouts() if x.get("id") != layout.get("id")]
    items.append(layout)
    _rest("POST", "app_settings", key, payload={"key": LAYOUTS_KEY, "value": items})
    return True

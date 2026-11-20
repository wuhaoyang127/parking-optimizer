"""Supabase 快照持久化：车主端 ReleaseStore 状态经 service_role 直连 app_settings 表。

复用研究端已有的 app_settings 键值表（key -> JSONB），避免额外建表（DDL）。
与 auth_supabase（anon key 调 RPC）不同：这里用 SUPABASE_SERVICE_KEY 直连读写，
让「已发布算法/激活/试用/审计/观测/备份」在 Render 重新部署/重启后仍能恢复。
"""
from __future__ import annotations
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STATE_KEY = "driver_release_store_state"


def _settings() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase 持久化未配置：请设置 SUPABASE_URL 与 SUPABASE_SERVICE_KEY")
    return url, key


def _rest(method: str, path: str, key: str, payload=None, prefer: str | None = None) -> str:
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    req = Request(_settings()[0] + "/rest/v1/" + path, method=method,
                  data=None if payload is None else json.dumps(payload, allow_nan=False).encode(),
                  headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError("Supabase 持久化失败: " + exc.read(2000).decode("utf-8", "replace")) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Supabase 持久化网络错误: " + str(exc)) from None


def pull_state():
    """读取最近一次持久化的 ReleaseStore 快照；无记录返回 None。"""
    _, key = _settings()
    body = _rest("GET", f"app_settings?key=eq.{STATE_KEY}&select=value", key)
    rows = json.loads(body)
    if not rows:
        return None
    return rows[0].get("value")


def push_state(snapshot):
    """把 ReleaseStore 快照 upsert 到 app_settings（按主键 key 合并）。"""
    _, key = _settings()
    _rest("POST", "app_settings", key,
          payload={"key": STATE_KEY, "value": snapshot},
          prefer="resolution=merge-duplicates")


LAYOUTS_KEY = "driver_layouts"


def pull_layouts():
    """读取推送布局列表；无记录返回 []。"""
    _, key = _settings()
    body = _rest("GET", f"app_settings?key=eq.{LAYOUTS_KEY}&select=value", key)
    rows = json.loads(body)
    if not rows:
        return []
    val = rows[0].get("value")
    return val if isinstance(val, list) else []


def push_layout(layout):
    """追加/覆盖一个布局（按 id）。研究端「布局推送」调用。"""
    _, key = _settings()
    items = [x for x in pull_layouts() if x.get("id") != layout.get("id")]
    items.append(layout)
    _rest("POST", "app_settings", key,
          payload={"key": LAYOUTS_KEY, "value": items},
          prefer="resolution=merge-duplicates")

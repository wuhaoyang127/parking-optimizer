"""Research-side server-to-server API client; credentials never enter the browser."""
import json
from driver_bridge.settings import setting
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse


def call(path, payload=None, admin=False, *, raw=False):
    base = setting("PARKING_DRIVER_API_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlparse(base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("车主端 API 地址不能包含账号、口令、查询参数或片段")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise ValueError("非本机连接必须使用 HTTPS")
    token = setting("PARKING_ADMIN_TOKEN" if admin else "PARKING_PUBLISH_TOKEN")
    if len(token) < 32:
        raise ValueError("尚未配置服务端对接密钥（至少32字符）")
    request = Request(base + path, data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8-sig") if raw else json.load(response)
    except HTTPError as exc:
        # Only return the API error body, never Request headers or credentials.
        raise ValueError("车主端拒绝请求：" + exc.read(2000).decode("utf-8", "replace")) from None


def publish(algo, params, note="", *, seed=0, model=None):
    import uuid
    capabilities = call("/api/research/v1/capabilities")
    if algo not in capabilities["supported"]:
        raise ValueError(f"{algo} 尚未完成车主端在线输入适配，不能启用")
    return call("/api/research/v1/releases", {
        "release_id": "research-" + uuid.uuid4().hex,
        "algorithm_id": algo, "source_hash": capabilities["source_hash"],
        "params": params or {}, "note": note or "", "seed": seed, "model": model,
    })

"""生成 Supabase 自定义角色 driver_app 的 JWT（最小权限 key）。

用法：
    python scripts/generate_driver_app_jwt.py

按提示粘贴 Supabase 控制台（Settings → API）里的 JWT Secret，
输出一个 role=driver_app 的 JWT，用它替换车主端 Render 的
SUPABASE_SERVICE_KEY（以及研究端若还用 service key 的地方）。

只用标准库，不需要安装任何依赖。
"""
import base64
import hashlib
import hmac
import json
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_jwt(secret: str, role: str = "driver_app", years: int = 10) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "role": role,
        "iss": "supabase",
        "iat": now,
        "exp": now + years * 365 * 24 * 3600,
    }
    head = _b64url(json.dumps(header, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"


def main() -> None:
    secret = input("粘贴 Supabase JWT Secret（Settings → API，以 sb 开头的长串）: ").strip()
    if len(secret) < 32:
        print("⚠️  Secret 太短，看起来不对，请重新粘贴。")
        return
    token = generate_jwt(secret)
    print("\n=== driver_app JWT（复制下面这一行）===\n")
    print(token)
    print("\n用这个 token 替换车主端 Render 的 SUPABASE_SERVICE_KEY 即可。")


if __name__ == "__main__":
    main()

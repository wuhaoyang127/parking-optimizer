"""本机计算 worker 入口（云端界面 + 本地 CPU）。

用法（在项目根目录）：
    py local_worker.py
    py local_worker.py --username wuhaoyang127 --password your_pw

工作方式：
    1. 用本地 .streamlit/secrets.toml（或环境变量）里的 Supabase 配置登录；
    2. 轮询领取该用户在云端 app 下发的「本地计算任务」；
    3. 用本机 CPU 跑完仿真，把结果写回 Supabase；
    4. 云端 app 的「刷新结果」按钮会自动载入结果。

注意：需要在 Supabase 先执行 migrations/07_compute_tasks.sql（一次性）。
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from worker_net import (_SupabaseClient, _read_secret, _read_credentials,  # noqa: E402
                        _save_cached_credentials)
from worker_compute import run_local_task  # noqa: E402

# Windows 控制台/重定向输出可能使用 GBK（cp936），打印 ✓/✗/▶ 等符号会触发
# UnicodeEncodeError 使 worker 直接崩溃。统一加 errors="replace" 兜底：
# 保持当前终端编码不变（中文正常显示），无法编码的符号降级为 ?，不再崩溃。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="停车场 App 本机计算 worker")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--poll", type=float, default=3.0, help="无任务时的轮询间隔（秒）")
    args = parser.parse_args()

    url = _read_secret("SUPABASE_URL")
    key = _read_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        print("[✗] 缺少 Supabase 配置：请设置环境变量 SUPABASE_URL / SUPABASE_ANON_KEY，"
              "或在 .streamlit/secrets.toml 中配置")
        sys.exit(1)
    sb = _SupabaseClient(url, key)

    username, password = _read_credentials(args.username, args.password)
    if not username or not password:
        print("[✗] 缺少登录账号：请用 --username/--password 指定，"
              "或在 credentials.local.txt 中配置")
        sys.exit(1)

    def login():
        # worker 使用独立登录态（login_worker），不与网页 session_token 互相顶掉
        res = sb.rpc("login_worker", {"p_username": username, "p_password": password})
        data = res.data
        if isinstance(data, dict) and data.get("success"):
            return data.get("token")
        print(f"[✗] 登录失败：{data}")
        return None

    token = login()
    if not token:
        sys.exit(1)
    _save_cached_credentials(username, password)
    print(f"[✓] 登录成功（{username}，worker 独立登录态）。等待云端下发本地计算任务…（Ctrl+C 退出）")

    while True:
        try:
            res = sb.rpc("claim_compute_task", {"p_token": token})
            data = res.data
            if not isinstance(data, dict) or not data.get("success"):
                if isinstance(data, dict) and data.get("error") == "未登录":
                    print("[!] 登录态失效，重新登录…")
                    token = login()
                    if not token:
                        sys.exit(1)
                    continue
                print(f"[✗] 领取任务失败：{data}")
                time.sleep(args.poll)
                continue

            task = data.get("task")
            if not task:
                time.sleep(args.poll)
                continue

            task_id = task.get("id")
            payload = task.get("payload") or {}
            print(f"[▶] 领取任务 {task_id}（策略：{(payload.get('strategy') or {}).get('name')}）")
            t0 = time.time()
            try:
                result = run_local_task(payload)
                done_res = sb.rpc("complete_compute_task", {
                    "p_token": token, "p_task_id": task_id, "p_status": "done",
                    "p_result": result, "p_error": None})
                ddata = getattr(done_res, "data", done_res)
                if isinstance(ddata, dict) and not ddata.get("success"):
                    print(f"[·] 任务 {task_id} 已被网页端删除或无法回写（{ddata}），"
                          f"丢弃本次结果。")
                else:
                    print(f"[✓] 任务 {task_id} 完成（耗时 {time.time() - t0:.1f}s）")
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                try:
                    sb.rpc("complete_compute_task", {
                        "p_token": token, "p_task_id": task_id, "p_status": "failed",
                        "p_result": {}, "p_error": err})
                except Exception:
                    pass
                print(f"[✗] 任务 {task_id} 失败：{err}")
        except KeyboardInterrupt:
            print("\n[·] 已退出")
            break
        except Exception as e:
            print(f"[!] 循环异常：{e}")
            time.sleep(args.poll)


if __name__ == "__main__":
    main()

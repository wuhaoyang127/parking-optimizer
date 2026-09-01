"""本机计算 worker（云端界面 + 本地 CPU）。

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
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from supabase import create_client  # noqa: E402
import httpx  # noqa: E402

# Windows 控制台/重定向输出可能使用 GBK（cp936），打印 ✓/✗/▶ 等符号会触发
# UnicodeEncodeError 使 worker 直接崩溃。统一加 errors="replace" 兜底：
# 保持当前终端编码不变（中文正常显示），无法编码的符号降级为 ?，不再崩溃。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass


# ---------- 网络自愈 ----------

def _is_transient_net(e: Exception) -> bool:
    """网络瞬时错误（连接被重置/超时/断连，如 WinError 10053）。"""
    if isinstance(e, httpx.HTTPError):
        return True
    return isinstance(e, (ConnectionError, TimeoutError, OSError))


class _SupabaseClient:
    """带网络抖动自愈的 Supabase RPC 客户端。

    公网到 Supabase 的连接可能被代理/负载均衡器重置（常见 WinError 10053：
    软件中断了已建立的连接）。RPC 调用遇到瞬时网络错误时自动退避重试，
    并重建底层连接池，避免「循环异常 10053」刷屏或任务卡住。
    """

    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key
        self.client = create_client(url, key)

    def rpc(self, name: str, params: dict, *, tries: int = 4, backoff: float = 1.5):
        for i in range(tries):
            try:
                return self.client.rpc(name, params).execute()
            except Exception as e:
                if not _is_transient_net(e) or i == tries - 1:
                    raise
                print(f"[!] 网络抖动（{type(e).__name__}），{backoff:.0f}s 后重试"
                      f"（{i + 1}/{tries - 1}）…")
                time.sleep(backoff)
                backoff *= 1.5
                try:
                    self.client = create_client(self.url, self.key)
                except Exception:
                    pass


# ---------- 配置读取 ----------

def _read_secret(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    toml_path = ROOT / ".streamlit" / "secrets.toml"
    try:
        text = toml_path.read_text(encoding="utf-8")
        m = re.search(rf'^{key}\s*=\s*"([^"]+)"\s*$', text, re.M)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _read_credentials(username: str, password: str):
    if not username or not password:
        cred_path = ROOT / "credentials.local.txt"
        try:
            text = cred_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                if k.strip() == "username":
                    username = v.strip()
                elif k.strip() == "password":
                    password = v.strip()
        except Exception:
            pass
    return username, password


# ---------- 本地计算 ----------

def _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs):
    from parking_opt.simulation.parking_lot import ParkingLot
    from parking_opt.optimization.cpsat_baseline import CPSatBaseline
    from parking_opt.simulation.arrival import generate_demand
    try:
        cps_vehs = (list(base_vehicles) if base_vehicles is not None
                    else generate_demand(seed=seed, **demand_kwargs))
        cps_lot = ParkingLot(spots)
        cps_res = CPSatBaseline(cps_lot, pe).solve(cps_vehs)
        if cps_res is not None:
            return round(len(cps_res) / len(cps_vehs), 6)
    except Exception:
        pass
    return None


def run_local_task(payload: dict) -> dict:
    """按任务参数在本机执行仿真，返回可 JSON 序列化的结果 dict。"""
    from ui.common import (LAYOUT_BUILDERS, BUILTIN_LAYOUT_KEYS,
                           build_layout_from_json, run_single, _avg_metrics,
                           _vehicle_to_dict)
    from parking_opt.routing.path_engine import PathEngine
    from parking_opt.simulation.arrival import generate_demand
    from parking_opt.io.demand_io import parse_demand_json
    from parking_opt.strategies import StrategyRegistry

    # 1. 布局
    layout = payload.get("layout") or {}
    if layout.get("source") == "custom":
        net, spots = build_layout_from_json(layout["custom_data"])
    else:
        key = layout.get("builtin_key") or "linear"
        net, spots = LAYOUT_BUILDERS[key](int(layout.get("n_spots", 15)),
                                          float(layout.get("tandem_ratio", 0.5)))
    pe = PathEngine(net)

    # 2. 需求
    demand = payload.get("demand") or {}
    base_vehicles = None
    demand_kwargs = {}
    demand_source = "generated"
    if demand.get("source") in ("imported", "real_gate"):
        vehs, meta = parse_demand_json(demand.get("json_str", ""))
        base_vehicles = list(vehs)
        demand_source = "real_gate" if (meta or {}).get("source") == "real_gate" else "imported"
    else:
        demand_kwargs = dict(demand.get("generator") or {})
        demand_kwargs["entry_ids"] = pe.entry_ids
        demand_kwargs["exit_ids"] = pe.exit_ids

    # 3. 策略与引擎参数
    strategy_name = (payload.get("strategy") or {}).get("name", "duration_greedy")
    strat_params = (payload.get("strategy") or {}).get("params") or {}
    eng = payload.get("engine") or {}
    wait_policy = eng.get("wait_policy", "fifo")
    car_speed = float(eng.get("car_speed", 1.39))
    max_wait_time = float(eng.get("max_wait_time", 1800))
    seed = int(eng.get("seed", 42))
    n_runs = int(eng.get("n_runs", 1))
    random_reps = int(eng.get("random_reps", 100))
    budget = float(eng.get("budget", 60.0))
    eng_kwargs = dict(car_speed=car_speed, max_wait_time=max_wait_time)

    def _n_runs_for(name: str) -> int:
        return random_reps if name == "random" else n_runs

    result = {"mode": strategy_name == "compare_all" and "compare_all" or "single"}

    if strategy_name == "compare_all":
        all_m, timed_out, failed = [], [], []
        events_by_strategy, vehicles_by_strategy = {}, {}
        main_events_raw = None
        all_strategies = StrategyRegistry.all()
        total = len(all_strategies)
        for idx, (nm, cls) in enumerate(all_strategies.items(), 1):
            label = getattr(cls, "label", nm)
            print(f"[⚙️] 算法 {idx}/{total}：{label}（{nm}）…", flush=True)
            seed_metrics = []
            strategy_timed_out = False
            strategy_error = None
            total_runs = _n_runs_for(nm)
            for r in range(total_runs):
                s = seed + r
                vehs = (list(base_vehicles) if base_vehicles is not None
                        else generate_demand(seed=s, **demand_kwargs))
                t0 = time.time()
                try:
                    m, ev, _ = run_single(net, spots, vehs, cls(), s, wait_policy, **eng_kwargs)
                except Exception as e:
                    strategy_error = f"{type(e).__name__}: {e}"
                    break
                if time.time() - t0 > budget:
                    strategy_timed_out = True
                seed_metrics.append(m)
                if total_runs > 1 and (total_runs <= 10 or (r + 1) % 10 == 0):
                    print(f"    ├─ {label}：第 {r + 1}/{total_runs} 次…", flush=True)
                if r == 0:
                    ev_raw = [{"time": e.time, "type": e.event_type.value,
                               "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                               "metadata": dict(e.metadata)} for e in ev]
                    events_by_strategy[nm] = ev_raw
                    vehicles_by_strategy[nm] = [_vehicle_to_dict(v) for v in vehs]
                    if nm == "duration_greedy":
                        main_events_raw = ev_raw
            if strategy_error:
                failed.append([nm, strategy_error])
            if strategy_timed_out:
                timed_out.append(nm)
            if seed_metrics:
                all_m.append(_avg_metrics(seed_metrics))
        result.update({
            "all_m": all_m,
            "metrics": next((m for m in all_m if m.get("strategy") == "duration_greedy"), None),
            "timed_out": timed_out,
            "failed": failed,
            "events_by_strategy": events_by_strategy,
            "vehicles_by_strategy": vehicles_by_strategy,
            "main_events": main_events_raw,
            "cpsat_rate": _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs),
        })
    else:
        cls = StrategyRegistry.get(strategy_name)
        if cls is None:
            raise ValueError(f"未知策略：{strategy_name}")
        label = getattr(cls, "label", strategy_name)
        print(f"[⚙️] 运行策略：{label}（{strategy_name}）…", flush=True)
        seed_metrics = []
        events_raw = None
        timed_out = False
        total_runs = _n_runs_for(strategy_name)
        for r in range(total_runs):
            s = seed + r
            vehs = (list(base_vehicles) if base_vehicles is not None
                    else generate_demand(seed=s, **demand_kwargs))
            strategy = StrategyRegistry.create(strategy_name, **strat_params)
            t0 = time.time()
            m, ev, _ = run_single(net, spots, vehs, strategy, s, wait_policy, **eng_kwargs)
            if time.time() - t0 > budget:
                timed_out = True
            seed_metrics.append(m)
            if total_runs > 1 and (total_runs <= 10 or (r + 1) % 10 == 0):
                print(f"    ├─ {label}：第 {r + 1}/{total_runs} 次…", flush=True)
            if r == 0:
                events_raw = [{"time": e.time, "type": e.event_type.value,
                               "vehicle_id": e.vehicle_id or "", "spot_id": e.spot_id or "",
                               "metadata": dict(e.metadata)} for e in ev]
                vehs_serialized = [_vehicle_to_dict(v) for v in vehs]
        result.update({
            "metrics": _avg_metrics(seed_metrics),
            "timed_out": [strategy_name] if timed_out else [],
            "failed": [],
            "events_by_strategy": {strategy_name: events_raw},
            "vehicles_by_strategy": {strategy_name: vehs_serialized},
            "main_events": events_raw,
            "cpsat_rate": _cpsat_rate(net, spots, pe, base_vehicles, seed, demand_kwargs),
        })
    return result


# ---------- 主循环 ----------

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
                sb.rpc("complete_compute_task", {
                    "p_token": token, "p_task_id": task_id, "p_status": "done",
                    "p_result": result, "p_error": None})
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

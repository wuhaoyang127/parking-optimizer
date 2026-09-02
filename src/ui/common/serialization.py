"""车辆序列化 / JSON 安全转换 / 仿真运行记录持久化。"""
from ui.common._imports import *


def vehicles_from_dicts(items) -> list:
    """dict 列表 → Vehicle 列表（本地计算结果载入云端界面用）。"""
    out = []
    for d in items or []:
        if not isinstance(d, dict):
            continue
        out.append(Vehicle(
            vehicle_id=d.get("vehicle_id", ""),
            arrival_time=float(d.get("arrival_time", 0.0) or 0.0),
            parking_duration=float(d.get("parking_duration", 0.0) or 0.0),
            estimated_duration=float(d.get("estimated_duration",
                                          d.get("parking_duration", 0.0) or 0.0)),
            assigned_spot=d.get("assigned_spot"),
            rejected=bool(d.get("rejected", False)),
            wait_start=d.get("wait_start"),
            wait_end=d.get("wait_end"),
            entry_id=d.get("entry_id"),
            exit_id=d.get("exit_id"),
        ))
    return out


def _json_safe(obj):
    """把参数/指标转成 JSON 原生类型（防 numpy/日期等脏类型导致 Supabase 写入失败）。"""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float, str)) or obj is None:
        return obj
    try:
        import numpy as _np
        if isinstance(obj, (_np.integer, _np.floating)):
            return obj.item()
    except Exception:
        pass
    return str(obj)


def persist_sim_run(strategy: str, params: dict, env: dict, metrics,
                    layout_key: str = None, demand_source: str = None) -> dict:
    """把一次仿真运行结果持久化到 Supabase sim_runs 表（登录用户，跨会话可查）。

    metrics 为 dict（单策略）或 list（全部对比）；同时写入一条审计日志。
    """
    token = st.session_state.get("token")
    if not token:
        return None
    payload = _json_safe(metrics)
    try:
        res = auth_save_sim_run(token, strategy, _json_safe(params or {}),
                                _json_safe(env or {}), payload,
                                layout_key, demand_source)
        try:
            auth_log_action(token, "sim_run", {
                "strategy": strategy, "layout_key": layout_key,
                "demand_source": demand_source})
        except Exception:
            pass
        return res
    except Exception:
        return None

from __future__ import annotations
"""需求序列 JSON 导入导出：同一批车辆到达/离场需求可导出为文件，下次仿真导入复用。

格式 schema_version=1，含元数据（种子/生成参数）与车辆列表。
只负责序列化与校验，不生成需求；生成见 simulation/arrival.py。
"""

import json
import math
from datetime import datetime
from typing import Any

from ..domain.spot import Vehicle

SCHEMA_VERSION = 1

# 允许出现在 generator_params 里的键（导出时保留；导入时仅记录，不强制）
_GENERATOR_PARAM_KEYS = (
    "total_vehicles", "sim_duration", "duration_min", "duration_max",
    "peak_ratio", "error_ratio",
)


def export_demand_json(vehicles: list[Vehicle], seed: int | None = None,
                       source: str = "generated",
                       generator_params: dict[str, Any] | None = None,
                       generated_at: str | None = None) -> str:
    """把车辆需求列表序列化为需求序列 JSON 字符串。

    参数:
        vehicles: 需求车辆列表（按到达时间排序由调用方保证）。
        seed: 生成该序列时使用的随机种子（如有）。
        source: 来源标记，默认 "generated"（生成）；导入再导出可写 "imported"。
        generator_params: 生成参数快照（可选，仅记录，导入时不用于重新生成）。
        generated_at: 生成时间 ISO 字符串，缺省用当前本地时间。
    """
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "seed": seed,
        "generator_params": {k: v for k, v in (generator_params or {}).items()
                             if k in _GENERATOR_PARAM_KEYS},
        "vehicles": [
            {
                "vehicle_id": v.vehicle_id,
                "arrival_time": v.arrival_time,
                "parking_duration": v.parking_duration,
                "estimated_duration": v.estimated_duration,
                **({"entry_id": v.entry_id} if v.entry_id else {}),
                **({"exit_id": v.exit_id} if v.exit_id else {}),
            }
            for v in vehicles
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _is_finite_nonneg(value: Any) -> bool:
    """是否为有限非负数字（int/float，bool 不算）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) >= 0.0


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def parse_demand_json(text: str) -> tuple[list[Vehicle], dict[str, Any]]:
    """解析需求序列 JSON，返回 (vehicles, metadata)。

    校验失败抛 ValueError，错误信息指出具体字段。车辆按 arrival_time 升序返回。
    """
    _require(isinstance(text, str) and text.strip(), "需求序列文件内容为空")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"需求序列文件不是合法 JSON：{exc}") from exc

    _require(isinstance(data, dict), "需求序列 JSON 顶层必须是对象")
    _require(data.get("schema_version") == SCHEMA_VERSION,
             f"schema_version 必须为 {SCHEMA_VERSION}，实际为 {data.get('schema_version')!r}")
    vehicles_raw = data.get("vehicles")
    _require(isinstance(vehicles_raw, list) and len(vehicles_raw) > 0,
             "vehicles 必须是非空数组")

    vehicles: list[Vehicle] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(vehicles_raw):
        prefix = f"vehicles[{i}]"
        _require(isinstance(item, dict), f"{prefix} 必须是对象")

        vid = item.get("vehicle_id")
        _require(isinstance(vid, str) and vid.strip(), f"{prefix}.vehicle_id 必须是非空字符串")
        vid = vid.strip()
        _require(vid not in seen_ids, f"{prefix}.vehicle_id={vid!r} 重复")
        seen_ids.add(vid)

        arr = item.get("arrival_time")
        _require(_is_finite_nonneg(arr), f"{prefix}.arrival_time 必须是非负数字，实际为 {arr!r}")
        park = item.get("parking_duration")
        _require(_is_finite_nonneg(park), f"{prefix}.parking_duration 必须是非负数字，实际为 {park!r}")

        est = item.get("estimated_duration")
        if est is None:
            est = park  # 缺省回退为真实时长（与「无预估信息」的最保守处理一致）
        _require(_is_finite_nonneg(est), f"{prefix}.estimated_duration 必须是非负数字，实际为 {est!r}")

        entry_id = item.get("entry_id")
        _require(entry_id is None or (isinstance(entry_id, str) and entry_id.strip()),
                 f"{prefix}.entry_id 必须是非空字符串或省略，实际为 {entry_id!r}")
        exit_id = item.get("exit_id")
        _require(exit_id is None or (isinstance(exit_id, str) and exit_id.strip()),
                 f"{prefix}.exit_id 必须是非空字符串或省略，实际为 {exit_id!r}")

        vehicles.append(Vehicle(
            vehicle_id=vid,
            arrival_time=float(arr),
            parking_duration=float(park),
            estimated_duration=float(est),
            entry_id=entry_id.strip() if entry_id else None,
            exit_id=exit_id.strip() if exit_id else None,
        ))

    vehicles.sort(key=lambda v: v.arrival_time)

    metadata: dict[str, Any] = {
        "schema_version": data.get("schema_version"),
        "generated_at": data.get("generated_at"),
        "source": data.get("source", "imported"),
        "seed": data.get("seed"),
        "generator_params": data.get("generator_params")
        if isinstance(data.get("generator_params"), dict) else {},
        "vehicle_count": len(vehicles),
    }
    return vehicles, metadata

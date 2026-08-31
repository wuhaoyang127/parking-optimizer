from __future__ import annotations
"""真实数据接口预留：道闸流水 / 车位状态 解析与转换。

设计目标（企业合作预留）：
  1. 定义版本化的真实数据字段规范（见 docs/data/03_真实数据接口规范_v1.md）；
  2. 把停车场常见导出格式（CSV：车牌识别 + 道闸进出时间）转换为
     内部需求序列（Vehicle 列表），直接复用现有仿真与评估流程；
  3. 支持车牌脱敏（企业数据合规）。

本模块只做「只读解析」，不控制任何真实设备；数据源可以是 CSV 文件，
也可以是后续接入的 HTTP/WebSocket 接口（同一字段规范）。
"""

import csv
import hashlib
import io
import math
import re
from datetime import datetime, timezone
from typing import Any

from ..domain.spot import Vehicle
from .demand_io import export_demand_json

# 道闸流水 CSV 列名（含中英文别名）
_GATE_COLUMN_ALIASES = {
    "plate": ["plate", "plate_no", "plate_number", "车牌", "车牌号", "车牌号码"],
    "entry_time": ["entry_time", "entryTime", "entry_at", "in_time", "入场时间", "进入时间", "进场时间"],
    "exit_time": ["exit_time", "exitTime", "exit_at", "out_time", "出场时间", "离开时间", "离场时间"],
    "entry_id": ["entry_id", "entryId", "entry", "入口", "入口编号"],
    "exit_id": ["exit_id", "exitId", "exit", "出口", "出口编号"],
}

# 车位状态 CSV 列名
_SPOT_COLUMN_ALIASES = {
    "spot_id": ["spot_id", "spotId", "车位", "车位号", "车位编号", "space_id"],
    "occupied": ["occupied", "is_occupied", "状态", "占用", "占用状态"],
}

# 车位状态值的常见写法
_TRUE_VALUES = {"1", "true", "yes", "y", "occupied", "占用", "有车", "已占用", "是"}
_FALSE_VALUES = {"0", "false", "no", "n", "free", "empty", "空闲", "无车", "未占用", "否", ""}


def _first_match(row: dict[str, str], aliases: dict[str, list[str]], key: str) -> str | None:
    """按别名表在 CSV 行中找列名（大小写不敏感）。"""
    lowered = {str(k).strip().lower(): k for k in row.keys()}
    for alias in aliases[key]:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    return None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _parse_time(value: Any, row_label: str, field: str) -> datetime:
    """解析时间：ISO 字符串或 epoch 秒（int/float），统一返回时区感知 datetime。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{row_label} 缺少 {field}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception as exc:
            raise ValueError(f"{row_label} 的 {field} epoch 时间无法解析：{value!r}") from exc
    text = str(value).strip()
    # 纯数字字符串按 epoch 秒处理（CSV 读取后所有值都是字符串）
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except Exception as exc:
            raise ValueError(f"{row_label} 的 {field} epoch 时间无法解析：{value!r}") from exc
    # 常见格式：2026-08-30 10:00:00 / 2026-08-30T10:00:00 / 2026-08-30 10:00
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{row_label} 的 {field} 时间格式无法解析：{value!r}") from exc


def _anonymize_plate(plate: str) -> str:
    """车牌脱敏：SHA-256 前 10 位（可复现、不可逆推原文）。"""
    return "P" + hashlib.sha256(plate.encode("utf-8")).hexdigest()[:10].upper()


def parse_gate_csv(text: str) -> list[dict[str, Any]]:
    """解析道闸流水 CSV，返回规范化记录列表。

    必需列：车牌、入场时间、出场时间；可选列：入口编号、出口编号。
    返回每条记录：{plate, entry_time(datetime), exit_time(datetime),
                   entry_id, exit_id}。
    校验失败抛 ValueError，错误信息包含行号。
    """
    _require(isinstance(text, str) and text.strip(), "道闸流水 CSV 内容为空")
    reader = csv.DictReader(io.StringIO(text))
    _require(reader.fieldnames, "道闸流水 CSV 缺少表头")

    plate_col = _first_match(dict(zip(reader.fieldnames, reader.fieldnames)),
                             _GATE_COLUMN_ALIASES, "plate")
    entry_col = _first_match(dict(zip(reader.fieldnames, reader.fieldnames)),
                             _GATE_COLUMN_ALIASES, "entry_time")
    exit_col = _first_match(dict(zip(reader.fieldnames, reader.fieldnames)),
                            _GATE_COLUMN_ALIASES, "exit_time")
    entry_id_col = _first_match(dict(zip(reader.fieldnames, reader.fieldnames)),
                                _GATE_COLUMN_ALIASES, "entry_id")
    exit_id_col = _first_match(dict(zip(reader.fieldnames, reader.fieldnames)),
                               _GATE_COLUMN_ALIASES, "exit_id")

    _require(plate_col, "道闸流水 CSV 缺少车牌列（plate / 车牌）")
    _require(entry_col, "道闸流水 CSV 缺少入场时间列（entry_time / 入场时间）")
    _require(exit_col, "道闸流水 CSV 缺少出场时间列（exit_time / 出场时间）")

    records: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=2):
        label = f"第 {i} 行"
        plate = (row.get(plate_col) or "").strip()
        _require(bool(plate), f"{label} 车牌为空")
        entry_dt = _parse_time(row.get(entry_col), label, "入场时间")
        exit_dt = _parse_time(row.get(exit_col), label, "出场时间")
        _require(exit_dt > entry_dt, f"{label} 出场时间必须晚于入场时间")
        records.append({
            "plate": plate,
            "entry_time": entry_dt,
            "exit_time": exit_dt,
            "entry_id": (row.get(entry_id_col) or "").strip() or None if entry_id_col else None,
            "exit_id": (row.get(exit_id_col) or "").strip() or None if exit_id_col else None,
        })
    _require(bool(records), "道闸流水 CSV 没有有效数据行")
    return records


def gate_records_to_vehicles(records: list[dict[str, Any]],
                             base_time: datetime | None = None,
                             error_ratio: float = 0.0,
                             anonymize: bool = True) -> list[Vehicle]:
    """把道闸流水记录转换为内部需求序列（Vehicle 列表，按到达时间升序）。

    参数:
        records: parse_gate_csv 的输出（或接口层按同一规范提供的记录）。
        base_time: 时间基准（仿真 0 时刻），缺省取最早入场时间。
        error_ratio: 预估时长误差比例（±），默认 0 = 用真实时长作为预估。
        anonymize: 是否对车牌脱敏（默认 True，企业合规建议开启）。
    """
    _require(isinstance(records, list) and records, "道闸流水记录为空")
    if base_time is None:
        base_time = min(r["entry_time"] for r in records)

    vehicles: list[Vehicle] = []
    for i, r in enumerate(records):
        entry = r["entry_time"]
        exit_dt = r["exit_time"]
        _require(exit_dt > entry, f"记录 {i + 1} 出场时间必须晚于入场时间")
        arrival = (entry - base_time).total_seconds()
        parking = (exit_dt - entry).total_seconds()
        _require(arrival >= 0 and parking > 0,
                 f"记录 {i + 1} 时间差无效（arrival={arrival:.0f}s, parking={parking:.0f}s）")
        plate = str(r.get("plate") or f"V{i+1:04d}")
        vid = _anonymize_plate(plate) if anonymize else plate
        vehicles.append(Vehicle(
            vehicle_id=vid,
            arrival_time=arrival,
            parking_duration=parking,
            estimated_duration=parking * (1 + error_ratio),
            entry_id=r.get("entry_id") or None,
            exit_id=r.get("exit_id") or None,
        ))
    vehicles.sort(key=lambda v: v.arrival_time)
    return vehicles


def gate_csv_to_demand_json(text: str, base_time: datetime | None = None,
                            error_ratio: float = 0.0, anonymize: bool = True) -> str:
    """道闸流水 CSV → 需求序列 JSON（schema v1，可直接走现有导入流程）。"""
    records = parse_gate_csv(text)
    vehicles = gate_records_to_vehicles(records, base_time=base_time,
                                        error_ratio=error_ratio, anonymize=anonymize)
    return export_demand_json(
        vehicles,
        seed=None,
        source="real_gate",
        generator_params={"error_ratio": error_ratio, "anonymized": anonymize},
    )


def parse_spot_status_csv(text: str) -> dict[str, bool]:
    """解析车位状态快照 CSV → {spot_id: occupied}。

    必需列：车位编号、占用状态（1/0、true/false、占用/空闲 等均可）。
    """
    _require(isinstance(text, str) and text.strip(), "车位状态 CSV 内容为空")
    reader = csv.DictReader(io.StringIO(text))
    _require(reader.fieldnames, "车位状态 CSV 缺少表头")
    header = dict(zip(reader.fieldnames, reader.fieldnames))
    spot_col = _first_match(header, _SPOT_COLUMN_ALIASES, "spot_id")
    occ_col = _first_match(header, _SPOT_COLUMN_ALIASES, "occupied")
    _require(spot_col, "车位状态 CSV 缺少车位编号列（spot_id / 车位号）")
    _require(occ_col, "车位状态 CSV 缺少占用状态列（occupied / 状态）")

    result: dict[str, bool] = {}
    for i, row in enumerate(reader, start=2):
        label = f"第 {i} 行"
        sid = (row.get(spot_col) or "").strip()
        _require(bool(sid), f"{label} 车位编号为空")
        _require(sid not in result, f"{label} 车位编号 {sid!r} 重复")
        raw = (row.get(occ_col) or "").strip().lower()
        if raw in _TRUE_VALUES:
            result[sid] = True
        elif raw in _FALSE_VALUES:
            result[sid] = False
        else:
            raise ValueError(f"{label} 占用状态无法识别：{row.get(occ_col)!r}（支持 1/0、占用/空闲 等）")
    _require(bool(result), "车位状态 CSV 没有有效数据行")
    return result


def _is_finite_nonneg(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) >= 0.0

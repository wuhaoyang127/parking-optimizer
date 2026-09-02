from __future__ import annotations
"""真实数据接口：道闸流水 CSV 解析与需求序列转换。"""

import csv
import io
from datetime import datetime
from typing import Any

from ..domain.spot import Vehicle
from .demand_io import export_demand_json
from ._realtime_helpers import (_GATE_COLUMN_ALIASES, _first_match, _require,
                                _parse_time, _anonymize_plate)


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

    header = dict(zip(reader.fieldnames, reader.fieldnames))
    plate_col = _first_match(header, _GATE_COLUMN_ALIASES, "plate")
    entry_col = _first_match(header, _GATE_COLUMN_ALIASES, "entry_time")
    exit_col = _first_match(header, _GATE_COLUMN_ALIASES, "exit_time")
    entry_id_col = _first_match(header, _GATE_COLUMN_ALIASES, "entry_id")
    exit_id_col = _first_match(header, _GATE_COLUMN_ALIASES, "exit_id")

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

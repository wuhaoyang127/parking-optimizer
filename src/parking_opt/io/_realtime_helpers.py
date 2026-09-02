from __future__ import annotations
"""真实数据接口：解析辅助（列名别名/校验/时间/车牌脱敏）。"""

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any

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


def _is_finite_nonneg(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) >= 0.0

# ruff: noqa: RUF001
"""Frozen D2 design tokens and non-colour status encodings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

FONT_FAMILY = (
    "Microsoft YaHei UI, PingFang SC, Noto Sans CJK SC, Source Han Sans SC, Arial, sans-serif"
)


class ScreenshotState(StrEnum):
    """Six visual-reference states frozen by D0."""

    INDEPENDENT_NORMAL = "independent_normal"
    MIXED_BLOCKED = "mixed_blocked"
    RELOCATION = "relocation"
    RESOURCE_WAIT = "resource_wait"
    FAILURE_UNKNOWN = "failure_unknown"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class ScreenshotStateSpec:
    label: str
    note: str
    algorithm_status: str
    evidence_status: str


SCREENSHOT_STATE_SPECS = MappingProxyType(
    {
        ScreenshotState.INDEPENDENT_NORMAL: ScreenshotStateSpec(
            "独立车位｜正常运行",
            "全部车位均为 depth=1；用于核对入口、出口、道路和普通位。",
            "规则策略｜已记录",
            "synthetic｜演示证据",
        ),
        ScreenshotState.MIXED_BLOCKED: ScreenshotStateSpec(
            "混合纵深｜阻挡成立",
            "同组 depth=1 靠近通道；浅位占用时，深位车辆被阻挡。",
            "规则策略｜已记录",
            "synthetic｜演示证据",
        ),
        ScreenshotState.RELOCATION: ScreenshotStateSpec(
            "移位事务｜执行中",
            "仅展示离散资源状态，不插值或伪造车辆轨迹。",
            "移位执行器｜忙碌",
            "synthetic｜静态规范态",
        ),
        ScreenshotState.RESOURCE_WAIT: ScreenshotStateSpec(
            "资源不足｜等待",
            "缓冲位或通道资源不可用时明确显示等待，不静默降级。",
            "降级策略｜等待",
            "synthetic｜失败案例",
        ),
        ScreenshotState.FAILURE_UNKNOWN: ScreenshotStateSpec(
            "失败与未知状态",
            "未知位置、不可用资源和失败状态必须保留并醒目呈现。",
            "执行结果｜失败",
            "synthetic｜失败案例",
        ),
        ScreenshotState.INSUFFICIENT_EVIDENCE: ScreenshotStateSpec(
            "证据不足｜禁止外推",
            "正式核心对照尚未完成，当前内容只支持开发验证，不形成算法优越性结论。",
            "算法比较｜未评估",
            "证据不足｜待正式对照",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class StatusSpec:
    """Colour plus redundant symbol/text encoding for one position status."""

    label: str
    color: str
    symbol: str
    glyph: str
    border: str


POSITION_STATUS_SPECS = MappingProxyType(
    {
        "free": StatusSpec("空闲", "#E2E8F0", "square-open", "□", "#475569"),
        "occupied": StatusSpec("占用", "#2563EB", "square", "■", "#1E3A8A"),
        "reserved": StatusSpec("预留", "#7C3AED", "diamond", "◆", "#4C1D95"),
        "locked": StatusSpec("锁定", "#F59E0B", "x", "×", "#92400E"),
        "blocked": StatusSpec("阻挡", "#DC2626", "square-dot", "▣", "#7F1D1D"),
        "moving": StatusSpec("移动中", "#0891B2", "triangle-up", "▲", "#164E63"),
        "unknown": StatusSpec("未知", "#64748B", "star", "★", "#1E293B"),
        "unavailable": StatusSpec("不可用", "#111827", "x-open", "⊠", "#000000"),
    }
)

SPACING_PX = (4, 8, 12, 16, 24, 32)
CONTENT_MAX_WIDTH_PX = 1440
GRID_COLUMNS = 12
BASE_RADIUS_PX = 10

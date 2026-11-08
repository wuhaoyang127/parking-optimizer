"""Type and specification constants for deterministic M4 public facilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from parking_opt.api.models import (
    DriverDemoProfile,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    PricingSummary,
    ScenarioBundle,
    VenueType,
)

PUBLISHED_AT = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FacilityScenarioSpec:
    scenario_id: str
    lot_id: str
    name: str
    region: str
    venue_type: VenueType
    spaces: int
    charging: int
    tandem_groups: int
    buffers: int
    occupied: int
    entrances: int
    exits: int
    ring_directed: bool
    seed: int
    pricing: PricingSummary


@dataclass(frozen=True, slots=True)
class PublishedFacilityScenario:
    layout: ParkingFacilityLayout
    base_state: ParkingFacilityStateSnapshot
    bundle: ScenarioBundle


@dataclass(frozen=True, slots=True)
class DriverDemoProfileSpec:
    profile_id: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class PublishedDriverDemoScenario:
    demo_profile: DriverDemoProfile
    layout: ParkingFacilityLayout
    base_state: ParkingFacilityStateSnapshot
    bundle: ScenarioBundle


DRIVER_DEMO_PROFILE_SPECS = (
    DriverDemoProfileSpec("normal-flow", "平峰通行", "空位分布较均衡。优先展示近端普通车位和合规备选。"),
    DriverDemoProfileSpec("peak-remote", "高峰远端", "近端车位接近饱和。系统需要跨区寻找较远的可行车位。"),
    DriverDemoProfileSpec("charging-tight", "充电紧张", "充电位暂时占满。充电需求会如实进入等待而不降级。"),
    DriverDemoProfileSpec("tandem-focus", "纵深协同", "普通独立位已满。外侧位已为后续车辆预留。系统会真实选择可恢复的内侧协同位。"),
)


PUBLIC_SPECS = (
    FacilityScenarioSpec(
        "commercial-full-v1",
        "lot-commercial",
        "中心商业广场停车场",
        "商业中心",
        "commercial",
        48,
        8,
        1,
        1,
        31,
        2,
        2,
        True,
        4101,
        PricingSummary(first_hour_yuan=6, additional_hour_yuan=4, daily_cap_yuan=40, note="模拟商业停车计费"),
    ),
    FacilityScenarioSpec(
        "school-full-v1",
        "lot-school",
        "大学创新园停车场",
        "学校",
        "school",
        28,
        4,
        4,
        2,
        14,
        1,
        1,
        False,
        4201,
        PricingSummary(first_hour_yuan=2, additional_hour_yuan=3, daily_cap_yuan=30, note="模拟校内首小时优惠"),
    ),
    FacilityScenarioSpec(
        "hospital-full-v1",
        "lot-hospital",
        "市立医院停车场",
        "医院",
        "hospital",
        32,
        6,
        1,
        1,
        22,
        2,
        2,
        False,
        4301,
        PricingSummary(first_hour_yuan=5, additional_hour_yuan=3, daily_cap_yuan=30, note="模拟就诊高峰动态通行成本"),
    ),
    FacilityScenarioSpec(
        "transport-hub-full-v1",
        "lot-transport-hub",
        "综合交通枢纽停车场",
        "交通枢纽",
        "transport_hub",
        52,
        10,
        1,
        1,
        31,
        2,
        2,
        True,
        4401,
        PricingSummary(first_hour_yuan=3, additional_hour_yuan=2, daily_cap_yuan=20, note="模拟交通枢纽停车计费"),
    ),
)

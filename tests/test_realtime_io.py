"""真实数据接口预留模块的单元测试（道闸流水 / 车位状态解析）。"""

import pytest

from src.parking_opt.io.realtime_io import (
    parse_gate_csv,
    gate_records_to_vehicles,
    gate_csv_to_demand_json,
    parse_spot_status_csv,
)
from src.parking_opt.io.demand_io import parse_demand_json


GATE_CSV = """plate,entry_time,exit_time,entry_id,exit_id
京A12345,2026-08-30 08:00:00,2026-08-30 09:30:00,entry_1,exit_1
京B67890,2026-08-30 08:05:00,2026-08-30 08:35:00,entry_1,exit_1
京C11111,2026-08-30 09:00:00,2026-08-30 10:00:00,entry_2,exit_1
"""

SPOT_CSV = """spot_id,occupied
S001,1
S002,0
S003,占用
S004,空闲
"""


def test_parse_gate_csv_basic():
    records = parse_gate_csv(GATE_CSV)
    assert len(records) == 3
    assert records[0]["plate"] == "京A12345"
    assert records[0]["entry_id"] == "entry_1"
    assert records[1]["entry_time"] < records[1]["exit_time"]


def test_parse_gate_csv_chinese_columns():
    csv_text = "车牌,入场时间,出场时间\n京A1,2026-08-30 08:00:00,2026-08-30 09:00:00\n"
    records = parse_gate_csv(csv_text)
    assert records[0]["plate"] == "京A1"


def test_parse_gate_csv_epoch_times():
    csv_text = "plate,entry_time,exit_time\n京A1,1753843200,1753846800\n"
    records = parse_gate_csv(csv_text)
    assert records[0]["entry_time"].timestamp() == 1753843200


def test_parse_gate_csv_rejects_bad_order():
    csv_text = "plate,entry_time,exit_time\n京A1,2026-08-30 09:00:00,2026-08-30 08:00:00\n"
    with pytest.raises(ValueError, match="晚于"):
        parse_gate_csv(csv_text)


def test_parse_gate_csv_rejects_missing_columns():
    with pytest.raises(ValueError, match="出场时间"):
        parse_gate_csv("plate,entry_time\n京A1,2026-08-30 08:00:00\n")


def test_gate_records_to_vehicles_anonymized():
    records = parse_gate_csv(GATE_CSV)
    vehicles = gate_records_to_vehicles(records)
    assert len(vehicles) == 3
    # 脱敏后不应包含原始车牌
    assert all("京" not in v.vehicle_id for v in vehicles)
    # 到达时间以最早入场为 0
    assert vehicles[0].arrival_time == 0.0
    # 停车时长 = 出场 - 入场
    assert vehicles[0].parking_duration == 5400.0
    # 默认 error_ratio=0 → 预估 = 真实
    assert vehicles[0].estimated_duration == vehicles[0].parking_duration
    # 按到达时间升序
    arrivals = [v.arrival_time for v in vehicles]
    assert arrivals == sorted(arrivals)


def test_gate_records_to_vehicles_keep_plate():
    records = parse_gate_csv(GATE_CSV)
    vehicles = gate_records_to_vehicles(records, anonymize=False)
    assert vehicles[0].vehicle_id == "京A12345"


def test_gate_csv_to_demand_json_roundtrip():
    text = gate_csv_to_demand_json(GATE_CSV)
    vehicles, meta = parse_demand_json(text)
    assert meta["source"] == "real_gate"
    assert meta["vehicle_count"] == 3
    assert len(vehicles) == 3


def test_parse_spot_status_csv():
    status = parse_spot_status_csv(SPOT_CSV)
    assert status == {"S001": True, "S002": False, "S003": True, "S004": False}


def test_parse_spot_status_csv_rejects_unknown_value():
    with pytest.raises(ValueError, match="无法识别"):
        parse_spot_status_csv("spot_id,occupied\nS001,maybe\n")

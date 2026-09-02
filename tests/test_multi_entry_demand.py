"""需求生成与 JSON 往返的多入口/多出口测试。"""

import json

from src.parking_opt.simulation.arrival import generate_demand
from src.parking_opt.io.demand_io import export_demand_json, parse_demand_json

from tests._multi_entry_helpers import make_veh


def test_generate_demand_entry_exit_assignment_reproducible_and_inscope():
    entries = ["E1", "E2"]
    exits = ["X1", "X2"]
    v1 = generate_demand(total_vehicles=60, seed=42, entry_ids=entries, exit_ids=exits)
    v2 = generate_demand(total_vehicles=60, seed=42, entry_ids=entries, exit_ids=exits)
    assert [v.entry_id for v in v1] == [v.entry_id for v in v2]
    assert [v.exit_id for v in v1] == [v.exit_id for v in v2]
    for v in v1:
        assert v.entry_id in entries
        assert v.exit_id in exits
    # 两个口都至少被分配到（60 辆车等概率，几乎必然）
    assert len({v.entry_id for v in v1}) == 2
    assert len({v.exit_id for v in v1}) == 2


def test_generate_demand_single_entry_keeps_old_sequence():
    """单入口（旧行为）：同 seed 生成的需求序列与不传口列表完全一致。"""
    old = generate_demand(total_vehicles=50, seed=7)
    new = generate_demand(total_vehicles=50, seed=7, entry_ids=["ENTRY"], exit_ids=[])
    assert [v.arrival_time for v in old] == [v.arrival_time for v in new]
    assert [v.parking_duration for v in old] == [v.parking_duration for v in new]
    assert all(v.entry_id is None and v.exit_id is None for v in new)


def test_demand_json_roundtrip_with_entry_exit():
    vehicles = [make_veh("V1", entry="E1", exit_="X2"),
                make_veh("V2", entry=None, exit_=None)]
    text = export_demand_json(vehicles, seed=42)
    data = json.loads(text)
    assert data["vehicles"][0]["entry_id"] == "E1"
    assert data["vehicles"][0]["exit_id"] == "X2"
    assert "entry_id" not in data["vehicles"][1]  # None 不输出
    back, meta = parse_demand_json(text)
    assert back[0].entry_id == "E1" and back[0].exit_id == "X2"
    assert back[1].entry_id is None and back[1].exit_id is None


def test_demand_json_old_file_without_entry_exit_still_parses():
    text = json.dumps({
        "schema_version": 1,
        "vehicles": [
            {"vehicle_id": "V1", "arrival_time": 0, "parking_duration": 100,
             "estimated_duration": 100},
        ],
    }, ensure_ascii=False)
    vehicles, meta = parse_demand_json(text)
    assert vehicles[0].entry_id is None and vehicles[0].exit_id is None

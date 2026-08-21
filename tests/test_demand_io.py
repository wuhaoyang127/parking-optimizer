"""需求序列 JSON 导入导出测试"""

import json

import pytest

from src.parking_opt.domain.spot import Vehicle
from src.parking_opt.io.demand_io import SCHEMA_VERSION, export_demand_json, parse_demand_json


def make_vehicles(n=3):
    return [
        Vehicle(vehicle_id=f"V{i:04d}",
                arrival_time=float(i * 10),
                parking_duration=1000.0 + i,
                estimated_duration=900.0 + i)
        for i in range(1, n + 1)
    ]


class TestRoundTrip:
    def test_export_then_import_preserves_vehicles(self):
        vehicles = make_vehicles()
        text = export_demand_json(vehicles, seed=42,
                                  generator_params={"total_vehicles": 3, "sim_duration": 21600})
        parsed, meta = parse_demand_json(text)

        assert meta["schema_version"] == SCHEMA_VERSION
        assert meta["seed"] == 42
        assert meta["vehicle_count"] == 3
        assert [v.vehicle_id for v in parsed] == [v.vehicle_id for v in vehicles]
        for a, b in zip(parsed, vehicles):
            assert a.arrival_time == pytest.approx(b.arrival_time)
            assert a.parking_duration == pytest.approx(b.parking_duration)
            assert a.estimated_duration == pytest.approx(b.estimated_duration)

    def test_import_sorts_by_arrival_time(self):
        vehicles = [
            Vehicle("V3", 30.0, 100.0, 100.0),
            Vehicle("V1", 10.0, 100.0, 100.0),
            Vehicle("V2", 20.0, 100.0, 100.0),
        ]
        text = export_demand_json(vehicles)
        parsed, _ = parse_demand_json(text)
        assert [v.vehicle_id for v in parsed] == ["V1", "V2", "V3"]

    def test_estimated_duration_missing_falls_back_to_parking_duration(self):
        payload = {
            "schema_version": 1,
            "vehicles": [
                {"vehicle_id": "V1", "arrival_time": 0, "parking_duration": 3600}
            ],
        }
        parsed, _ = parse_demand_json(json.dumps(payload))
        assert parsed[0].estimated_duration == pytest.approx(3600.0)


class TestValidation:
    def _wrap(self, vehicles):
        return json.dumps({"schema_version": 1, "vehicles": vehicles})

    def test_empty_text_rejected(self):
        with pytest.raises(ValueError, match="内容为空"):
            parse_demand_json("")

    def test_invalid_json_rejected(self):
        with pytest.raises(ValueError, match="合法 JSON"):
            parse_demand_json("{not json")

    def test_wrong_schema_version_rejected(self):
        with pytest.raises(ValueError, match="schema_version"):
            parse_demand_json(json.dumps({"schema_version": 2, "vehicles": []}))

    def test_empty_vehicles_rejected(self):
        with pytest.raises(ValueError, match="非空数组"):
            parse_demand_json(json.dumps({"schema_version": 1, "vehicles": []}))

    def test_missing_vehicle_id_rejected(self):
        with pytest.raises(ValueError, match="vehicle_id"):
            parse_demand_json(self._wrap([
                {"arrival_time": 1, "parking_duration": 2, "estimated_duration": 2},
            ]))

    def test_negative_arrival_rejected(self):
        with pytest.raises(ValueError, match="arrival_time"):
            parse_demand_json(self._wrap([
                {"vehicle_id": "V1", "arrival_time": -5, "parking_duration": 2,
                 "estimated_duration": 2},
            ]))

    def test_non_numeric_parking_duration_rejected(self):
        with pytest.raises(ValueError, match="parking_duration"):
            parse_demand_json(self._wrap([
                {"vehicle_id": "V1", "arrival_time": 1, "parking_duration": "long",
                 "estimated_duration": 2},
            ]))

    def test_duplicate_vehicle_id_rejected(self):
        with pytest.raises(ValueError, match="重复"):
            parse_demand_json(self._wrap([
                {"vehicle_id": "V1", "arrival_time": 1, "parking_duration": 2,
                 "estimated_duration": 2},
                {"vehicle_id": "V1", "arrival_time": 3, "parking_duration": 2,
                 "estimated_duration": 2},
            ]))

    def test_bool_values_rejected(self):
        with pytest.raises(ValueError, match="arrival_time"):
            parse_demand_json(self._wrap([
                {"vehicle_id": "V1", "arrival_time": True, "parking_duration": 2,
                 "estimated_duration": 2},
            ]))

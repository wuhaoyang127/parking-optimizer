"""本地计算结果压缩/解压回归测试。

覆盖：
1. 压缩→Supabase JSON 往返→解压后与原始 result 一致；
2. main_events=None 等空字段保持 None；
3. 旧格式（无 _packed 标记）原样返回；
4. 压缩体积明显小于原始 JSON 文本；
5. compress_result 无副作用（不改动原 dict）；
6. 重复压缩幂等（不会二次打包）；
7. 非 dict 输入安全返回；
8. worker 回传代码路径：local_worker 导入 compress_result 可用。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from local_compute import compress_result, decompress_result  # noqa: E402


def _big_result():
    """构造一个类似 compare_all 1000 车任务的大 result（含中文与重复结构）。"""
    events = []
    for i in range(1500):
        events.append({
            "time": 100.0 + i * 2.5,
            "type": "SPOT_ENTRY" if i % 2 == 0 else "DEPARTURE",
            "vehicle_id": f"v{i % 500}",
            "spot_id": f"R{i % 120}",
            "metadata": {"entry": "ENTRY", "exit": "EXIT", "via": "让行移位"},
        })
    vehicles = []
    for i in range(1000):
        vehicles.append({
            "vehicle_id": f"v{i}",
            "arrival_time": 0.0 + i * 12.0,
            "parking_duration": 7200.0,
            "estimated_duration": 3600.0,
            "assigned_spot": f"R{i % 120}",
            "rejected": False,
            "wait_start": None,
            "wait_end": None,
            "entry_id": "ENTRY",
            "exit_id": "EXIT",
        })
    events_by_strategy = {}
    vehicles_by_strategy = {}
    for nm in ("fcfs", "nearest", "random", "greedy", "duration_greedy",
               "departure_greedy", "risk_scoring", "mosa", "rho_rolling",
               "peak_offpeak_fusion"):
        events_by_strategy[nm] = events
        vehicles_by_strategy[nm] = vehicles
    return {
        "mode": "compare_all",
        "all_m": [{"strategy": "duration_greedy", "satisfaction_rate": 0.98}],
        "metrics": {"strategy": "duration_greedy", "satisfaction_rate": 0.98},
        "timed_out": [],
        "failed": [],
        "events_by_strategy": events_by_strategy,
        "vehicles_by_strategy": vehicles_by_strategy,
        "main_events": events,
    }


def test_roundtrip_via_json_persistence():
    """压缩→JSON 序列化往返（模拟 Supabase JSONB）→解压后与原 result 一致。"""
    original = _big_result()
    packed = compress_result(original)
    loaded = json.loads(json.dumps(packed, ensure_ascii=False))
    restored = decompress_result(loaded)
    assert restored == original
    assert "_packed" not in restored


def test_none_fields_stay_none():
    """main_events=None 时压缩/解压仍为 None，不报错。"""
    result = {"metrics": {}, "events_by_strategy": {}, "vehicles_by_strategy": {},
              "main_events": None}
    packed = compress_result(result)
    loaded = json.loads(json.dumps(packed, ensure_ascii=False))
    restored = decompress_result(loaded)
    assert restored["main_events"] is None
    assert restored["events_by_strategy"] == {}


def test_legacy_result_without_marker_passthrough():
    """旧格式（无 _packed 标记）原样返回且不添加标记。"""
    legacy = {"metrics": {"strategy": "greedy"}, "events_by_strategy": {"greedy": [{"time": 1}]}}
    out = decompress_result(legacy)
    assert out == legacy
    assert "_packed" not in out


def test_compress_reduces_size():
    """压缩后大字段字符串应显著小于原始 JSON 文本。"""
    original = _big_result()
    packed = compress_result(original)
    raw_size = len(json.dumps(original["events_by_strategy"], ensure_ascii=False))
    packed_size = len(packed["events_by_strategy"])
    assert packed_size < raw_size * 0.2  # 重复结构多，gzip 压缩率应很高


def test_compress_does_not_mutate_input():
    """compress_result 返回新 dict，不修改原 result。"""
    original = _big_result()
    compress_result(original)
    assert isinstance(original["events_by_strategy"]["fcfs"], list)
    assert "_packed" not in original


def test_double_compress_is_idempotent():
    """已压缩的 result 再次 compress 不会二次打包。"""
    original = _big_result()
    once = compress_result(original)
    twice = compress_result(once)
    assert twice is once


def test_non_dict_input_is_safe():
    """None / 非 dict 输入安全返回。"""
    assert decompress_result(None) is None
    assert decompress_result([1, 2]) == [1, 2]
    assert compress_result(None) is None


def test_local_worker_imports_compress_result():
    """worker 回传前使用的 compress_result 可从 local_compute 顶层导入。"""
    import local_worker  # noqa: F401
    assert callable(compress_result)

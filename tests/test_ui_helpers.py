"""UI 小工具单元测试（不启动 Streamlit，只测纯函数）。"""

import sys
from pathlib import Path

# app.py 运行时会注入 src；测试环境手动注入后即可导入 ui 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.pages import _vehicle_sort_key, _worker_bat  # noqa: E402
from ui.pages import _worker_operator_bat, _worker_package_bytes  # noqa: E402
from ui.pages import _worker_package_data_url  # noqa: E402
from ui.common import build_local_task_context  # noqa: E402


def test_vehicle_sort_key_handles_mixed_ids():
    """带下划线数字后缀与无下划线 ID 混用时排序不得抛 TypeError。"""
    ids = ["V0002", "car_10", "V0001", "car_2", "P1A2B3C4D5"]
    out = sorted(ids, key=_vehicle_sort_key)
    # 带下划线数字后缀的排前，且按数值序（2 < 10）
    assert out[0] == "car_2"
    assert out[1] == "car_10"
    assert set(out) == set(ids)


def test_vehicle_sort_key_non_numeric_suffix_falls_back():
    """下划线后缀非数字时回退字典序，不崩溃。"""
    ids = ["car_x", "V0001", "bus_3"]
    out = sorted(ids, key=_vehicle_sort_key)
    assert out[0] == "bus_3"
    assert set(out) == set(ids)


def test_vehicle_sort_key_generated_ids_order():
    """生成器 ID（V0001 零填充）保持字典序即数值序。"""
    ids = ["V0002", "V0010", "V0001"]
    assert sorted(ids, key=_vehicle_sort_key) == ["V0001", "V0002", "V0010"]


def test_worker_bat_run_script():
    """一键启动脚本：定位项目目录并运行 local_worker.py。"""
    bat = _worker_bat("run")
    assert "cd /d %~dp0" in bat
    assert "py local_worker.py --poll 1" in bat


def test_worker_bat_autostart_script():
    """开机自启安装脚本：注册/运行 Windows 计划任务。"""
    bat = _worker_bat("install_autostart")
    assert "schtasks /Create" in bat
    assert "ParkingOptLocalWorker" in bat
    assert "schtasks /Run" in bat
    assert "py local_worker.py --poll 1" in bat


def _base_local_task_payload():
    return {
        "layout": {"source": "builtin", "builtin_key": "linear",
                   "n_spots": 12, "tandem_ratio": 0.4},
        "demand": {"source": "generated", "generator": {
            "total_vehicles": 50, "sim_duration": 21600, "duration_min": 1800,
            "duration_max": 7200, "peak_ratio": 0.3, "error_ratio": 0.1}},
        "strategy": {"name": "compare_all", "params": {}},
        "engine": {"wait_policy": "shortest", "car_speed": 1.5,
                   "max_wait_time": 900, "seed": 37, "n_runs": 1,
                   "random_reps": 100},
    }


def test_build_local_task_context_builtin_generated():
    """内置布局 + 自动生成需求：从 payload 完整恢复页面上下文。"""
    ctx = build_local_task_context(_base_local_task_payload())
    assert ctx["layout"] == "linear"
    assert ctx["layout_category"] == "builtin"
    assert ctx["custom_layout"] is None
    assert ctx["n_spots"] == 12
    assert len(ctx["spots"]) == 12
    assert ctx["strategy_name"] == "compare_all"
    assert ctx["seed"] == 37
    assert ctx["wait_policy"] == "shortest"
    assert ctx["env_params"]["car_speed"] == 1.5
    assert ctx["env_params"]["sim_duration"] == 21600
    assert ctx["demand_source"] == "generated"
    assert ctx["base_vehicles"] is None
    assert ctx["n_vehicles"] == 50


def test_build_local_task_context_custom_layout():
    """自定义真实布局：重建布局并注册 custom_layout，车位数取自 JSON。"""
    payload = _base_local_task_payload()
    payload["layout"] = {"source": "custom", "custom_data": {
        "name": "测试真实布局",
        "nodes": [
            {"id": "E1", "type": "entry", "x": 0, "y": 0},
            {"id": "S1", "type": "spot", "x": 5, "y": 0,
             "spot_type": "standalone", "group": "S1", "depth": 1},
            {"id": "S2", "type": "spot", "x": 10, "y": 0,
             "spot_type": "standalone", "group": "S2", "depth": 1},
        ],
        "edges": [
            {"from": "E1", "to": "S1", "distance": 5},
            {"from": "S1", "to": "E1", "distance": 5},
            {"from": "E1", "to": "S2", "distance": 10},
            {"from": "S2", "to": "E1", "distance": 10},
        ],
    }}
    ctx = build_local_task_context(payload)
    assert ctx["layout_category"] == "real"
    assert ctx["n_spots"] == 2
    assert ctx["layout"] == "测试真实布局"
    assert ctx["custom_layout"] is not None
    assert "测试真实布局" in ctx["custom_layout"]


def test_build_local_task_context_imported_demand():
    """导入需求序列：恢复车辆列表与来源标记。"""
    from parking_opt.simulation.arrival import generate_demand
    from parking_opt.io.demand_io import export_demand_json
    vehs = generate_demand(total_vehicles=5, seed=1)
    payload = _base_local_task_payload()
    payload["demand"] = {"source": "imported",
                         "json_str": export_demand_json(vehs, seed=1, source="imported")}
    ctx = build_local_task_context(payload)
    assert ctx["demand_source"] == "imported"
    assert ctx["base_vehicles"] is not None
    assert ctx["n_vehicles"] == 5
    assert ctx["imported_meta"]


def test_worker_operator_bat_installs_deps_and_runs():
    """操作员启动脚本：检测 Python → 安装精简依赖 → 启动 worker。"""
    bat = _worker_operator_bat()
    assert "where py" in bat
    assert "py -m pip install -r requirements_worker.txt" in bat
    assert "py local_worker.py --poll 1" in bat


def test_worker_package_zip_contains_operator_kit():
    """操作员本地计算包：含 worker/核心算法/精简依赖/启动脚本/连接配置。"""
    from io import BytesIO
    from zipfile import ZipFile
    data = _worker_package_bytes("https://example.supabase.co", "anon-key")
    zf = ZipFile(BytesIO(data))
    names = set(zf.namelist())
    for need in ("local_worker.py", "src/local_compute.py",
                 "requirements_worker.txt", "start_local_worker.bat",
                 "worker_config.toml"):
        assert need in names
    assert any(n.startswith("src/parking_opt/") and n.endswith(".py") for n in names)
    cfg = zf.read("worker_config.toml").decode("utf-8")
    assert 'SUPABASE_URL = "https://example.supabase.co"' in cfg
    assert 'SUPABASE_ANON_KEY = "anon-key"' in cfg


def test_worker_package_data_url_is_zip_bytes():
    """zip 下载走 data URL：前端无需服务器连接即可下载（修复 not connected 报错）。"""
    import base64
    url = _worker_package_data_url()
    assert url.startswith("data:application/zip;base64,")
    data = base64.b64decode(url.split(",", 1)[1])
    assert data[:4] == b"PK\x03\x04"  # zip 魔数

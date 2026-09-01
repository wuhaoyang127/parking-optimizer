"""UI 小工具单元测试（不启动 Streamlit，只测纯函数）。"""

import sys
from pathlib import Path

# app.py 运行时会注入 src；测试环境手动注入后即可导入 ui 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.pages import _vehicle_sort_key, _worker_bat  # noqa: E402


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

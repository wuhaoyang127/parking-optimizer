"""内置布局连通性回归：每个车位必须能返回入口（离场路径可用）。"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_compute._layouts import LAYOUT_BUILDERS  # noqa: E402
from parking_opt.routing.path_engine import PathEngine  # noqa: E402


def test_builtin_layouts_have_return_path_from_every_spot():
    """内置布局必须双向连通：每个车位都能回到入口（否则离场动画无路可画）。"""
    for name, fn in LAYOUT_BUILDERS.items():
        net, spots = fn(20, 0.3)
        pe = PathEngine(net)
        bad = [s.spot_id for s in spots
               if not math.isfinite(pe.shortest_distance(s.node_id, pe.entry_id))]
        assert not bad, f"{name} 布局存在无法返回入口的车位: {bad}"

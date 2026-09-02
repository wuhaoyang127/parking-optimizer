"""ui.common 包：常量 + 工具 + auth 封装 + check_login。

对外保持与原 src/ui/common.py 完全相同的导入面：
- `from ui.common import *` 可用；
- `from ui.common import _avg_metrics, _plot_radar, ...` 等显式导入可用。
"""
from ui.common._imports import *  # noqa: F401,F403
from ui.common.constants import *  # noqa: F401,F403
from ui.common.demand_save import *  # noqa: F401,F403
from ui.common.ranking_ui import *  # noqa: F401,F403
from ui.common.events_ui import *  # noqa: F401,F403
from ui.common.timeline import *  # noqa: F401,F403
from ui.common.interp import *  # noqa: F401,F403
from ui.common.vehicle_phases import *  # noqa: F401,F403
from ui.common.task_context import *  # noqa: F401,F403
from ui.common.prefs import *  # noqa: F401,F403
from ui.common.serialization import *  # noqa: F401,F403
from ui.common.custom_layouts import *  # noqa: F401,F403
from ui.common.login import *  # noqa: F401,F403
from ui.common.param_widgets import *  # noqa: F401,F403

# 显式导出 _ 前缀名字（`import *` 不会自动携带）
from ui.common._imports import _avg_metrics, _vehicle_to_dict  # noqa: F401
from ui.common.ranking_ui import _plot_radar  # noqa: F401
from ui.common.events_ui import _fmt_clock, _finite_time  # noqa: F401
from ui.common.interp import _interp_path, _est_path_duration  # noqa: F401
from ui.common.custom_layouts import (_sync_custom_layouts_to_globals,  # noqa: F401
                                     _build_customs_from_items,
                                     _load_layout_items_from_local_backup,
                                     _write_local_layout_backup)
from ui.common.serialization import _json_safe  # noqa: F401
from ui.common.prefs import _load_priority_preference, _load_run_history, _load_last_params  # noqa: F401
from ui.common.param_widgets import (_coerce_int, _coerce_float,  # noqa: F401
                                    _render_param_widget)
from ui.common.vehicle_phases import _helper_shift_paths  # noqa: F401

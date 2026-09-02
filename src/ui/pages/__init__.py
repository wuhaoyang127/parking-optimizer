"""ui.pages 包：各页面渲染函数 + worker 工具。

对外保持与原 src/ui/pages.py 相同的导入面：
- app.py 的 `from ui.pages import render_settings, ...` 可用；
- tests 的 `from ui.pages import _worker_bat, _resolve_delete_task_id, ...` 可用。
"""
from ui.pages.worker_kit import (_worker_bat, WORKER_REQUIREMENTS_TXT,  # noqa: F401
                                 _worker_operator_bat, _worker_package_bytes,
                                 _worker_package_data_url, _resolve_delete_task_id,
                                 _WORKER_PACKAGE_VERSION, _cached_worker_package_bytes)
from ui.pages.settings_page import render_settings  # noqa: F401
from ui.pages.system_page import render_system  # noqa: F401
from ui.pages.layout_page import render_layout_page  # noqa: F401
from ui.pages.path_page import render_path_page, _vehicle_sort_key  # noqa: F401
from ui.pages.metrics_page import render_metrics_page  # noqa: F401
from ui.pages.history_page import render_history_page  # noqa: F401
from ui.pages.algo_import_page import render_algo_import_page  # noqa: F401
from ui.pages.status_page import render_status_page  # noqa: F401
from ui.pages.feedback_page import render_feedback_page  # noqa: F401

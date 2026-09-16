"""local_compute 包：本地计算纯函数（不依赖 Streamlit/Pandas/Plotly）。

供 local_worker.py（本机计算 worker）与 ui/common.py 共用：
worker 只需核心算法库（networkx/simpy/ortools/supabase），
不必安装界面库即可在本机跑仿真。
"""
from local_compute._layouts import (LAYOUT_BUILDERS, LAYOUTS, BUILTIN_LAYOUT_KEYS,  # noqa: F401
                                    build_linear, build_rectangle, build_lshape,
                                    build_triangle, build_circle, build_layout_from_json)
from local_compute._run import (run_single, COUNT_FIELDS, _avg_metrics,  # noqa: F401
                                _vehicle_to_dict)
from local_compute._tuning import (TUNE_TRIALS_DEFAULT, TUNE_TRIALS_MIN,  # noqa: F401
                                   TUNE_BATCH_SIZE, run_tuning,
                                   sample_params, best_trial, tunable_specs,
                                   resolve_strategy_flags)
from local_compute._groups import run_group, tune_all_strategies  # noqa: F401
from local_compute._compress import compress_result, decompress_result  # noqa: F401

"""ui.common 包公共导入：所有子模块通过 `from ui.common._imports import *` 获得
streamlit/pandas/plotly、auth 封装、local_compute 与 parking_opt 符号。"""
from __future__ import annotations

import sys, hashlib, json, math, os, time
from pathlib import Path
# 本文件位于 src/ui/common/_imports.py，三级父目录是 src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from auth import login as auth_login, register as auth_register
from auth import logout as auth_logout, list_users as auth_list_users
from auth import update_user_role as auth_update_role, delete_user as auth_delete_user
from auth import change_password as auth_change_pw, reset_user_password as auth_reset_pw
from auth import export_users as auth_export_users, import_users as auth_import_users
from auth import set_session_token, clear_session_token, restore_session
from auth import get_preference as auth_get_pref, set_preference as auth_set_pref
try:
    from auth import get_custom_sections as auth_get_custom_sections
    from auth import save_custom_sections as auth_save_custom_sections
except ImportError:
    def auth_get_custom_sections(*_a, **_k):
        return []

    def auth_save_custom_sections(*_a, **_k):
        return {"success": False, "error": "自定义角色权限未加载：后端代码未同步，请重新部署应用"}
# 本地计算纯函数（布局构建/仿真运行/车辆序列化）统一从 local_compute 导入：
# ui 与 local_worker 共用同一实现，worker 无需安装 Streamlit/Pandas/Plotly。
from local_compute import (LAYOUT_BUILDERS, LAYOUTS, BUILTIN_LAYOUT_KEYS,
                           build_linear, build_rectangle, build_lshape,
                           build_triangle, build_circle,
                           run_single, COUNT_FIELDS, _avg_metrics,
                           build_layout_from_json, _vehicle_to_dict)
# 以下新增函数做容错导入：若部署缓存导致 auth.py 未同步到最新，
# 用 stub 降级，避免整个 app 因单个函数缺失而崩溃（登录等核心功能不受影响）。
try:
    from auth import check_supabase_health
except ImportError:
    def check_supabase_health():
        return {"online": False, "api_key_valid": False, "status": "error",
                "message": "功能未加载：后端代码未同步，请在 Streamlit Cloud 重新部署",
                "latency_ms": None, "checked_at": ""}

try:
    from auth import submit_feedback as auth_submit_feedback
    from auth import list_my_feedbacks as auth_list_my_feedbacks
    from auth import list_feedbacks as auth_list_feedbacks
    from auth import update_feedback_status as auth_update_feedback_status
    from auth import reply_feedback as auth_reply_feedback
    from auth import delete_feedback as auth_delete_feedback
    from auth import update_feedback_display_time as auth_update_feedback_display_time
except ImportError:
    def _fb_unavailable(*_a, **_k):
        return {"success": False, "error": "反馈功能未加载：后端代码未同步，请重新部署应用"}

    auth_submit_feedback = _fb_unavailable
    auth_list_my_feedbacks = lambda *_a, **_k: []
    auth_list_feedbacks = lambda *_a, **_k: []
    auth_update_feedback_status = _fb_unavailable
    auth_reply_feedback = _fb_unavailable
    auth_delete_feedback = _fb_unavailable
    auth_update_feedback_display_time = _fb_unavailable

try:
    from auth import save_sim_run as auth_save_sim_run
    from auth import list_sim_runs as auth_list_sim_runs
    from auth import delete_sim_run as auth_delete_sim_run
    from auth import log_action as auth_log_action
except ImportError:
    def _sim_runs_unavailable(*_a, **_k):
        return {"success": False, "error": "运行记录功能未加载：后端代码未同步，请重新部署应用"}

    auth_save_sim_run = _sim_runs_unavailable
    auth_list_sim_runs = lambda *_a, **_k: []
    auth_delete_sim_run = _sim_runs_unavailable
    auth_log_action = _sim_runs_unavailable

try:
    from auth import create_compute_task as auth_create_compute_task
    from auth import get_compute_task as auth_get_compute_task
    from auth import requeue_compute_task as auth_requeue_compute_task
    from auth import get_latest_compute_task as auth_get_latest_compute_task
    from auth import delete_compute_task as auth_delete_compute_task
    from auth import get_latest_compute_task_any as auth_get_latest_compute_task_any
except ImportError:
    def _compute_tasks_unavailable(*_a, **_k):
        return {"success": False, "error": "本地计算任务功能未加载：请先执行 migrations/07_compute_tasks.sql"}

    auth_create_compute_task = _compute_tasks_unavailable
    auth_get_compute_task = _compute_tasks_unavailable
    auth_requeue_compute_task = _compute_tasks_unavailable
    auth_get_latest_compute_task = _compute_tasks_unavailable
    auth_delete_compute_task = _compute_tasks_unavailable
    auth_get_latest_compute_task_any = _compute_tasks_unavailable

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, Spot, SpotType, Vehicle
from parking_opt.routing.path_engine import PathEngine
from parking_opt.simulation.parking_lot import ParkingLot
from parking_opt.simulation.engine import SimulationEngine
from parking_opt.simulation.arrival import generate_demand
from parking_opt.simulation.defaults import (CAR_SPEED, MAX_WAIT_TIME, SIM_DURATION,
                                             DURATION_MIN, DURATION_MAX, PEAK_RATIO, ERROR_RATIO)
from parking_opt.strategies import StrategyRegistry
from parking_opt.strategies.mosa import estimate_scene as estimate_mosa_scene
from parking_opt.strategies.mosa import resolve_scene as resolve_mosa_scene
from parking_opt.strategies.mosa import SCENE_LABELS as MOSA_SCENE_LABELS
from parking_opt.evaluation.metrics import compute_metrics
from parking_opt.evaluation.ranking import (weighted_rank, below_significance_fields,
                                            DEFAULT_WEIGHTS as RANK_DEFAULT_WEIGHTS)
from parking_opt.io.demand_io import export_demand_json, parse_demand_json
from parking_opt.optimization.cpsat_baseline import CPSatBaseline
from viz import draw_parking_layout

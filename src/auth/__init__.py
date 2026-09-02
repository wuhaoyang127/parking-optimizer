"""Supabase 认证模块（auth 包聚合入口）。

对外保持与原 src/auth.py 相同的导入面。
"""
from auth._base import (SUPABASE_URL, SUPABASE_ANON_KEY, get_supabase,  # noqa: F401
                        _read_secret, _rpc, _rpc_with_retry, _is_transient_net)
from auth.users import (login, register, validate_session, logout,  # noqa: F401
                        list_users, update_user_role, delete_user,
                        change_password, reset_user_password,
                        export_users, import_users, get_preference, set_preference)
from auth.session import (set_session_token, get_session_token,  # noqa: F401
                          clear_session_token, restore_session,
                          _cookie_token, _set_cookie_js, _clear_cookie_js)
from auth.health import check_supabase_health  # noqa: F401
from auth.feedback import (submit_feedback, list_my_feedbacks, list_feedbacks,  # noqa: F401
                           update_feedback_status, reply_feedback, delete_feedback,
                           update_feedback_display_time, _normalize_list)
from auth.audit_runs import (log_action, save_sim_run, list_sim_runs,  # noqa: F401
                             delete_sim_run)
from auth.tasks import (create_compute_task, claim_compute_task,  # noqa: F401
                        complete_compute_task, get_compute_task,
                        get_latest_compute_task, requeue_compute_task,
                        delete_compute_task, get_latest_compute_task_any)

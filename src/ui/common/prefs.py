"""用户偏好加载/持久化（优先级、调参历史、最近参数、计算位置）。"""
from ui.common._imports import *
from ui.common.constants import PRIORITY_METRICS, DEFAULT_PRIORITY


def _load_priority_preference():
    """登录/恢复会话后，从 Supabase 加载用户的算法优先级设置"""
    token = st.session_state.get("token")
    if not token:
        return
    try:
        val = auth_get_pref(token, "algorithm_priority")
        if val:
            order = json.loads(val)
            order = [n for n in order if n in PRIORITY_METRICS]
            # 补充缺失的指标（按默认顺序追加），兼容旧版本保存的配置
            for n in DEFAULT_PRIORITY:
                if n not in order:
                    order.append(n)
            if order:
                st.session_state.priority_order = order
    except Exception:
        pass


def _load_run_history():
    """登录/恢复会话后，从 Supabase 加载用户的调参历史（每策略最近5次）"""
    token = st.session_state.get("token")
    if not token:
        return
    try:
        val = auth_get_pref(token, "run_history")
        if val:
            history = json.loads(val)
            if isinstance(history, dict):
                st.session_state.run_history = history
    except Exception:
        pass


LAST_PARAMS_PREF_KEY = "last_params_v1"


def _load_last_params():
    """登录/恢复会话后，从 Supabase 加载各策略最近一次使用的参数（用于回填控件）。"""
    token = st.session_state.get("token")
    if not token:
        return
    try:
        val = auth_get_pref(token, LAST_PARAMS_PREF_KEY)
        if val:
            last = json.loads(val)
            if isinstance(last, dict):
                st.session_state.last_params = {
                    k: v for k, v in last.items() if isinstance(v, dict)}
    except Exception:
        pass


def persist_last_params(strategy_name: str, params: dict):
    """保存某策略最近一次使用的参数（内存 + Supabase 用户偏好），reboot 后回填控件。"""
    last = st.session_state.setdefault("last_params", {})
    last[strategy_name] = dict(params or {})
    token = st.session_state.get("token")
    if not token:
        return
    try:
        auth_set_pref(token, LAST_PARAMS_PREF_KEY,
                      json.dumps(last, ensure_ascii=False))
    except Exception:
        pass


# 计算位置偏好：cloud = 云端 CPU；local = 本机 worker（云 UI + 本地算力）
COMPUTE_MODE_PREF_KEY = "compute_mode_v1"
COMPUTE_MODE_CLOUD = "cloud"
COMPUTE_MODE_LOCAL = "local"


def load_compute_mode():
    """登录/恢复会话后，从 Supabase 读取计算位置偏好（cloud / local）。"""
    mode = COMPUTE_MODE_CLOUD
    token = st.session_state.get("token")
    if token:
        try:
            val = auth_get_pref(token, COMPUTE_MODE_PREF_KEY)
            if val == COMPUTE_MODE_LOCAL:
                mode = COMPUTE_MODE_LOCAL
        except Exception:
            pass
    st.session_state.compute_mode = mode


def persist_compute_mode(mode: str):
    """保存计算位置偏好（内存 + Supabase 用户偏好）。"""
    mode = COMPUTE_MODE_LOCAL if mode == COMPUTE_MODE_LOCAL else COMPUTE_MODE_CLOUD
    st.session_state.compute_mode = mode
    token = st.session_state.get("token")
    if not token:
        return
    try:
        auth_set_pref(token, COMPUTE_MODE_PREF_KEY, mode)
    except Exception:
        pass

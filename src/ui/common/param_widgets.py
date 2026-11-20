"""参数控件渲染：策略参数 / 环境参数声明与动态控件。"""
from ui.common._imports import *

# 环境参数（引擎 + 需求生成）声明：与策略参数一样，网页渲染为可调控件
ENV_PARAM_SPECS = [
    {"key": "car_speed", "label": "车速(m/s)", "type": "float",
     "min": 0.5, "max": 5.0, "step": 0.1, "default": CAR_SPEED,
     "help": "车辆行驶速度，影响行驶/移位时间"},
    {"key": "max_wait_time", "label": "排队等待上限(秒)", "type": "int",
     "min": 60, "max": 7200, "step": 60, "default": MAX_WAIT_TIME,
     "help": "车位满时车辆排队等待的最长时间"},
    {"key": "sim_duration", "label": "仿真时长(秒)", "type": "int",
     "min": 3600, "max": 86400, "step": 600, "default": int(SIM_DURATION),
     "help": "仿真总时长（默认6小时）"},
    {"key": "duration_min", "label": "停车时长下限(秒)", "type": "int",
     "min": 60, "max": 7200, "step": 60, "default": int(DURATION_MIN),
     "help": "车辆停车时长范围下限"},
    {"key": "duration_max", "label": "停车时长上限(秒)", "type": "int",
     "min": 600, "max": 14400, "step": 300, "default": int(DURATION_MAX),
     "help": "车辆停车时长范围上限"},
    {"key": "peak_ratio", "label": "高峰车辆占比", "type": "float",
     "min": 0.0, "max": 1.0, "step": 0.05, "default": PEAK_RATIO,
     "help": "高峰时段到达的车辆占比"},
    {"key": "error_ratio", "label": "时长预估误差(±)", "type": "float",
     "min": 0.0, "max": 0.9, "step": 0.05, "default": ERROR_RATIO,
     "help": "预估停车时长相较真实时长的误差比例"},
    {"key": "buffer_w_distance", "label": "缓冲位-距离权重 w_d", "type": "float",
     "min": 0.0, "max": 3.0, "step": 0.1, "default": 1.0,
     "help": "移位选缓冲位时，距离越近代价越低（越小越优先选近的）"},
    {"key": "buffer_w_idle", "label": "缓冲位-空闲时间权重 w_t", "type": "float",
     "min": 0.0, "max": 3.0, "step": 0.1, "default": 1.0,
     "help": "移位选缓冲位时，车位空闲时间越短代价越高（刚空出的车位不适合做缓冲位）"},
    {"key": "buffer_w_secondary", "label": "缓冲位-二次移位惩罚 w_q", "type": "float",
     "min": 0.0, "max": 5.0, "step": 0.1, "default": 2.0,
     "help": "候选缓冲位会挡住其他车（可能引发二次移位）时的惩罚，越大越回避"},
    {"key": "buffer_idle_half_life", "label": "缓冲位-空闲半衰 τ(秒)", "type": "int",
     "min": 60, "max": 1800, "step": 60, "default": 300,
     "help": "空闲时间代价的半衰阈值：已空闲 τ 秒时代价=0.5，空闲越久代价越低"},
]


def _coerce_int(value, default, lo, hi):
    """把持久化的参数值安全转成 int 并夹在 [lo, hi] 内。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        try:
            return int(default)
        except (TypeError, ValueError):
            return int(lo)
    return max(int(lo), min(int(hi), v))


def _coerce_float(value, default, lo, hi):
    """把持久化的参数值安全转成 float 并夹在 [lo, hi] 内。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        try:
            return float(default)
        except (TypeError, ValueError):
            return float(lo)
    return max(float(lo), min(float(hi), v))


def leaf_strategy_names():
    """返回可作为子策略的「叶子」策略名（与车主端 catalog 的 CHILDREN 一致）。

    排除机器学习策略、自身带子策略的复合策略（rho_rolling / peak_offpeak_fusion），
    以及离线研究算法 mosa（读未来真值，不能作为在线子策略）。
    """
    return [
        n for n in StrategyRegistry.all().keys()
        if n != "mosa"
        and getattr(StrategyRegistry.get(n), "category", "classic") != "ml"
        and not any(p.get("type") == "strategy" for p in StrategyRegistry.specs(n))
    ]


def check_upload_size(uploaded, max_mb: int = 10, label: str = "文件") -> bool:
    """拒绝超大上传，防止超大文件拖垮内存/解析（上传不做 zip 解压，无 zip bomb 风险）。"""
    if uploaded is not None and uploaded.size > max_mb * 1024 * 1024:
        st.error(f"❌ {label}过大（{uploaded.size / 1048576:.1f}MB），上限 {max_mb}MB")
        return False
    return True


def normalize_strategy_params(algo, params):
    """把子策略参数归一化到合法叶子策略，防止历史脏数据导致车主端校验失败。"""
    leaf = leaf_strategy_names()
    clean = dict(params)
    for spec in StrategyRegistry.specs(algo):
        if spec.get("type") == "strategy" and clean.get(spec["key"]) not in leaf:
            clean[spec["key"]] = spec.get("default")
    return clean


def _render_param_widget(p, prefix, disabled, initial=None):
    """按单个参数声明渲染控件，返回参数值。prefix 用于生成唯一 widget key。

    p 里可带 "locked": True —— 该参数由系统自动判定/绑定，渲染为灰色不可调
    （如 MOSA 的场景模式由车位数/车辆数/时间自动判定）。

    initial: 可选 {key: value}，优先作为控件初始值（用于 reboot 后回填上次参数）。
    """
    key = p["key"]
    label = p.get("label", key)
    help_text = p.get("help")
    ptype = p.get("type", "float")
    default = p.get("default")
    dis = disabled or bool(p.get("locked", False))
    wkey = f"{prefix}_{key}"
    initial = initial or {}
    if ptype == "int":
        lo, hi = int(p.get("min", 0)), int(p.get("max", 100))
        init_val = _coerce_int(initial.get(key), default, lo, hi)
        return st.slider(label, lo, hi, init_val,
                         int(p.get("step", 1)), key=wkey, disabled=dis, help=help_text)
    if ptype == "float":
        lo, hi = float(p.get("min", 0.0)), float(p.get("max", 1.0))
        init_val = _coerce_float(initial.get(key), default, lo, hi)
        return st.slider(label, lo, hi, init_val,
                         float(p.get("step", 0.1)), key=wkey, disabled=dis, help=help_text)
    if ptype == "choice":
        options = p.get("options", [])
        opts = [o[0] for o in options] if options else []
        fmt = {o[0]: o[1] for o in options} if options else {}
        iv = initial.get(key)
        idx = opts.index(iv) if iv in opts else (opts.index(default) if default in opts else 0)
        return st.selectbox(label, opts, index=idx, format_func=lambda v: fmt.get(v, v),
                            key=wkey, disabled=dis, help=help_text)
    if ptype == "bool":
        iv = initial.get(key)
        val = iv if isinstance(iv, bool) else bool(default)
        return st.checkbox(label, val, key=wkey, disabled=dis, help=help_text)
    if ptype == "strategy":
        names = leaf_strategy_names()
        fmt = {n: StrategyRegistry.get(n).label for n in names}
        iv = initial.get(key)
        idx = names.index(iv) if iv in names else (names.index(default) if default in names else 0)
        return st.selectbox(label, names, index=idx, format_func=lambda v: fmt.get(v, v),
                            key=wkey, disabled=dis, help=help_text)
    return None


def render_strategy_params(strategy_name, disabled=False, initial=None):
    """渲染某策略的全部参数控件，返回 {key: value}。initial 用于回填上次参数。"""
    params = {}
    for p in StrategyRegistry.specs(strategy_name):
        params[p["key"]] = _render_param_widget(p, f"sp_{strategy_name}", disabled,
                                                initial=initial)
    return params


# 导入需求序列后不再起作用的「需求生成」环境参数（导入模式将变灰）
DEMAND_GEN_ENV_KEYS = {"sim_duration", "duration_min", "duration_max",
                       "peak_ratio", "error_ratio"}


def render_env_params(disabled=False, disabled_keys=None):
    """渲染环境参数（引擎 + 需求）控件，返回 {key: value}。

    disabled_keys: 需要额外禁用的参数 key 集合（如导入需求序列后，需求生成参数变灰）。
    """
    params = {}
    for p in ENV_PARAM_SPECS:
        key = p["key"]
        dis = disabled or (disabled_keys is not None and key in disabled_keys)
        params[key] = _render_param_widget(p, "env", dis)
    return params

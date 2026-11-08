"""Reviewed online adapters and parameter ranges; independent of Streamlit imports."""
BASE = ("fcfs", "nearest", "random", "greedy", "departure_greedy")
CHILDREN = BASE + ("duration_greedy", "risk_scoring")
SUPPORTED = CHILDREN + ("peak_offpeak_fusion", "rho_rolling", "ml_duration_tree")
SPECS = {
    "duration_greedy": {"threshold": (600, 7200, "number"), "warmup": (1, 100, "int")},
    "risk_scoring": {k: (0, 3, "number") for k in ("w_distance", "w_risk", "w_depth")},
    "peak_offpeak_fusion": {"peak_strategy": CHILDREN, "offpeak_strategy": CHILDREN,
                            "peak_threshold": (0, 1, "number")},
    "rho_rolling": {"roll_step": (1, 30, "int"), "window_min": (10, 120, "int"),
        "mild_threshold": (0.05, 0.4, "number"), "severe_threshold": (0.3, 1, "number"),
        "burst_threshold": (3, 30, "int"), **{key: CHILDREN for key in
            ("plan_strategy", "high_load_strategy", "low_load_strategy", "fallback_strategy")}},
    "ml_duration_tree": {"max_depth": (2, 8, "int"), "min_samples_leaf": (1, 20, "int"),
                         "use_entry": ("bool",)},
}
REQUIREMENTS = {"duration_greedy": "用户预计停留；相关占用车辆的预计离场",
    "risk_scoring": "相关占用车辆预计离场；完整静态车位结构",
    "peak_offpeak_fusion": "已知占用状态；所选子策略的输入",
    "rho_rolling": "同会话已发生入场观测（无历史时为冷启动）；子策略输入",
    "ml_duration_tree": "已完成历史样本训练的JSON模型；相关占用车辆的在线特征"}


def validate_params(algorithm, params):
    """严格校验：拒绝未知参数、类型不符、范围越界和非有限数值。"""
    import math
    specs = SPECS.get(algorithm, {})
    for key, value in params.items():
        rule = specs.get(key)
        if rule is None:
            raise ValueError("INVALID_ALGORITHM_PARAMETER:" + key)
        if rule == ("bool",):
            if type(value) is not bool:
                raise ValueError("INVALID_ALGORITHM_PARAMETER:" + key)
            continue
        if isinstance(rule, tuple) and len(rule) == 3 and rule[2] in ("number", "int"):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("INVALID_ALGORITHM_PARAMETER:" + key)
            if rule[2] == "int" and type(value) is not int:
                raise ValueError("INVALID_ALGORITHM_PARAMETER:" + key)
            if not (rule[0] <= value <= rule[1]):
                raise ValueError("INVALID_ALGORITHM_PARAMETER:" + key)
            continue
        if value not in rule:
            raise ValueError("INVALID_ALGORITHM_PARAMETER:" + key)
    return params


def catalog(names=None):
    _names = names if names is not None else SUPPORTED
    return [{"algorithm_id": name, "status": "online_adapter",
             "required_inputs": REQUIREMENTS.get(name, "当前可行候选与有向路网距离"),
             "params": SPECS.get(name, {})} for name in _names] + [{
        "algorithm_id": "mosa", "status": "research_only",
        "reason": "原实现prepare读取未来完整需求与真实停车时长，仅供研究站离线实验"}]

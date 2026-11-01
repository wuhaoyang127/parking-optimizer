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
    import math
    if algorithm not in SUPPORTED:
        raise ValueError("ALGORITHM_NOT_ONLINE")
    specs = SPECS.get(algorithm, {})
    if set(params) - set(specs):
        raise ValueError("UNKNOWN_ALGORITHM_PARAMETER")
    for key, value in params.items():
        rule = specs[key]
        if rule == ("bool",):
            valid = type(value) is bool
        elif len(rule) == 3 and rule[2] in ("number", "int"):
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and rule[0] <= value <= rule[1]
                     and (rule[2] != "int" or type(value) is int))
        else:
            valid = value in rule
        if not valid:
            raise ValueError("INVALID_ALGORITHM_PARAMETER:" + key)
    if algorithm == "rho_rolling" and params.get("mild_threshold", .2) >= params.get("severe_threshold", .5):
        raise ValueError("RHO_THRESHOLDS_NOT_ORDERED")
    return params


def catalog():
    return [{"algorithm_id": name, "status": "online_adapter",
             "required_inputs": REQUIREMENTS.get(name, "当前可行候选与有向路网距离"),
             "params": SPECS.get(name, {})} for name in SUPPORTED] + [{
        "algorithm_id": "mosa", "status": "research_only",
        "reason": "原实现prepare读取未来完整需求与真实停车时长，仅供研究站离线实验"}]

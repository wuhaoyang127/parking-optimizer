"""板块与功能权限矩阵：四角色默认值 + 自定义角色解析。

板块权限：控制导航是否显示该页面；
功能权限：控制页面内各关键按钮（每个关键按钮一个开关）。
自定义角色（custom）的板块/功能开关由管理员在系统设置中勾选，
存 Supabase users.permissions（{sections: [...], features: {...}}）。
"""

# ── 板块（页面）权限 ──
SECTION_KEYS = ["settings", "system", "layout", "path", "metrics",
                "history", "algo_import", "status", "feedback"]
SECTION_LABELS = {
    "settings": "⚙️ 仿真设置", "system": "🔧 系统设置", "layout": "🅿️ 停车场布局图",
    "path": "🚗 动态路径", "metrics": "📊 指标分析", "history": "📜 历史运行",
    "algo_import": "🧩 新算法接入", "status": "🚨 系统状态", "feedback": "💬 反馈",
}
DEFAULT_CUSTOM_SECTIONS = ["settings", "layout", "path", "metrics", "history", "feedback"]

# ── 功能权限（每个关键按钮一个开关）──
FEATURE_KEYS = [
    "can_configure",       # 编辑仿真参数
    "can_import_demand",   # 导入需求数据
    "can_export_demand",   # 导出需求序列
    "can_run_simulation",  # 云端运行仿真
    "can_local_compute",   # 本地计算
    "can_delete_local_task",  # 删除本地任务（叫停）
    "can_export_results",  # 导出指标结果
    "can_delete_history",  # 删除历史记录
    "can_manage_users",    # 用户管理
    "can_manage_data",     # 数据管理
    "can_import_algo",     # 上传新算法
    "can_debug",           # 查看系统状态
    "can_submit_feedback",  # 提交反馈
    "can_manage_feedback",  # 反馈管理
]
FEATURE_LABELS = {
    "can_configure": ("编辑仿真参数", "布局/策略/权重/环境参数"),
    "can_import_demand": ("导入需求数据", "上传 JSON/道闸 CSV/项目文件夹选择"),
    "can_export_demand": ("导出需求序列", "下载需求示例与转换后的需求 JSON"),
    "can_run_simulation": ("云端运行仿真", "在公网云端执行仿真"),
    "can_local_compute": ("本地计算", "下载脚本/操作员包、下发任务、检查/载入结果"),
    "can_delete_local_task": ("删除本地任务", "叫停排队/计算中的本地任务"),
    "can_export_results": ("导出指标结果", "下载指标 CSV/对比表"),
    "can_delete_history": ("删除历史记录", "删除历史运行记录"),
    "can_manage_users": ("用户管理", "角色/重置密码/删除用户/自定义角色面板"),
    "can_manage_data": ("数据管理", "导出/导入用户备份、导入布局"),
    "can_import_algo": ("上传新算法", "新算法接入页上传 zip"),
    "can_debug": ("查看系统状态", "系统状态页（连接/版本检查）"),
    "can_submit_feedback": ("提交反馈", "意见箱提交与查看我的反馈"),
    "can_manage_feedback": ("反馈管理", "查看全部反馈/回复/删除/改状态"),
}

FEATURES_ALL = {k: True for k in FEATURE_KEYS}
FEATURES_OPERATOR = {
    "can_configure": True, "can_import_demand": True, "can_export_demand": True,
    "can_run_simulation": True, "can_local_compute": True, "can_delete_local_task": True,
    "can_export_results": True, "can_delete_history": True, "can_manage_users": False,
    "can_manage_data": False, "can_import_algo": False, "can_debug": True,
    "can_submit_feedback": True, "can_manage_feedback": False,
}
FEATURES_VIEWER = {
    "can_configure": False, "can_import_demand": False, "can_export_demand": False,
    "can_run_simulation": True, "can_local_compute": False, "can_delete_local_task": False,
    "can_export_results": False, "can_delete_history": False, "can_manage_users": False,
    "can_manage_data": False, "can_import_algo": False, "can_debug": False,
    "can_submit_feedback": True, "can_manage_feedback": False,
}


def _role(name: str, label: str, features: dict, sections: list) -> dict:
    return {**features, "label": label, "sections": sections}


ROLES = {
    "admin": _role("admin", "管理员", FEATURES_ALL, SECTION_KEYS),
    "operator": _role("operator", "操作员", FEATURES_OPERATOR,
                      [k for k in SECTION_KEYS if k != "system"]),
    "viewer": _role("viewer", "访客", FEATURES_VIEWER,
                    ["settings", "layout", "path", "metrics", "history", "feedback"]),
    # 自定义角色：功能权限默认与操作员一致，管理员可勾选板块 + 功能开关
    "custom": _role("custom", "自定义", dict(FEATURES_OPERATOR), DEFAULT_CUSTOM_SECTIONS),
}


def resolve_role(role_name: str, permissions=None) -> dict:
    """把 session 里的角色名解析为完整权限 dict（平铺 can_* + label + sections）。

    内置角色直接返回其默认权限表；custom 角色用数据库 permissions
    （{sections: [...], features: {...}}）覆盖默认值。
    兼容旧格式：permissions 为板块数组（list）时只用其作为 sections。
    """
    base = ROLES.get(role_name, ROLES["viewer"]).copy()
    if role_name != "custom":
        return base

    if isinstance(permissions, list):
        sections, features = permissions, {}
    elif isinstance(permissions, dict):
        sections = permissions.get("sections") or DEFAULT_CUSTOM_SECTIONS
        features = permissions.get("features") or {}
    else:
        sections, features = DEFAULT_CUSTOM_SECTIONS, {}

    base["sections"] = [s for s in SECTION_KEYS if s in sections]
    for key in FEATURE_KEYS:
        if isinstance(features.get(key), bool):
            base[key] = features[key]
    return base

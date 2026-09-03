"""板块级 + 功能级权限：角色解析与自定义角色模板测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.common.permissions import (ROLES, SECTION_KEYS, SECTION_LABELS,  # noqa: E402
                                   DEFAULT_CUSTOM_SECTIONS, FEATURE_KEYS,
                                   FEATURE_LABELS, resolve_role)


def test_section_keys_cover_all_nav_pages():
    """9 个板块 key 与 label 一一对应，且无重复。"""
    assert len(SECTION_KEYS) == len(SECTION_LABELS) == 9
    assert set(SECTION_KEYS) == set(SECTION_LABELS)


def test_builtin_roles_have_valid_sections_and_features():
    """内置三角色 sections/features 必须完整且合法。"""
    for name in ("admin", "operator", "viewer"):
        secs = ROLES[name]["sections"]
        assert secs, f"{name} 板块不能为空"
        assert set(secs).issubset(SECTION_KEYS)
        assert len(secs) == len(set(secs)), f"{name} 板块重复"
        for key in FEATURE_KEYS:
            assert isinstance(ROLES[name].get(key), bool), f"{name} 缺少功能权限 {key}"


def test_all_features_have_labels():
    assert set(FEATURE_KEYS) == set(FEATURE_LABELS)
    for key in FEATURE_KEYS:
        assert len(FEATURE_LABELS[key]) == 2


def test_admin_all_operator_no_system_viewer_readonly():
    assert ROLES["admin"]["sections"] == SECTION_KEYS
    assert ROLES["admin"]["can_manage_users"] is True
    assert "system" not in ROLES["operator"]["sections"]
    assert "system" not in ROLES["viewer"]["sections"]
    # 访客只能运行仿真 + 提交反馈
    assert ROLES["viewer"]["can_run_simulation"] is True
    assert ROLES["viewer"]["can_submit_feedback"] is True
    assert ROLES["viewer"]["can_configure"] is False
    assert ROLES["viewer"]["can_local_compute"] is False
    assert ROLES["viewer"]["can_delete_local_task"] is False
    assert ROLES["viewer"]["can_export_results"] is False
    # 操作员可本地计算 + 删除历史 + 删除本地任务
    assert ROLES["operator"]["can_local_compute"] is True
    assert ROLES["operator"]["can_delete_local_task"] is True
    assert ROLES["operator"]["can_delete_history"] is True
    assert ROLES["operator"]["can_manage_feedback"] is False
    assert ROLES["operator"]["can_manage_users"] is False


def test_resolve_role_returns_copy_and_keeps_features():
    role = resolve_role("admin")
    assert role["sections"] == SECTION_KEYS
    assert role["can_manage_users"] is True
    # 返回的是副本，改 sections 不影响常量
    role["sections"] = ["settings"]
    assert ROLES["admin"]["sections"] == SECTION_KEYS


def test_resolve_role_custom_uses_object_permissions():
    perm = {"sections": ["settings", "feedback"],
            "features": {"can_local_compute": True, "can_manage_users": False}}
    role = resolve_role("custom", permissions=perm)
    assert role["sections"] == ["settings", "feedback"]
    assert role["can_local_compute"] is True
    # 未在 features 中指定的 key 保持 custom 默认（操作员级）
    assert role["can_configure"] is True
    assert role["can_manage_feedback"] is False


def test_resolve_role_custom_fallback_on_missing_permissions():
    role = resolve_role("custom", permissions=None)
    assert role["sections"] == DEFAULT_CUSTOM_SECTIONS
    assert role["can_local_compute"] is True  # 默认操作员级


def test_resolve_role_custom_compat_with_legacy_list():
    """旧格式：permissions 是板块数组 → sections 用之，features 用默认。"""
    role = resolve_role("custom", permissions=["settings", "history"])
    assert role["sections"] == ["settings", "history"]
    assert role["can_local_compute"] is True


def test_resolve_role_custom_filters_unknown_sections():
    role = resolve_role("custom", permissions={"sections": ["settings", "not_exist", "feedback"],
                                               "features": {}})
    assert role["sections"] == ["settings", "feedback"]


def test_resolve_role_unknown_role_falls_back_to_viewer():
    role = resolve_role("superadmin")
    assert role["label"] == "访客"
    assert role["can_manage_users"] is False


def test_default_custom_sections_valid():
    assert set(DEFAULT_CUSTOM_SECTIONS).issubset(SECTION_KEYS)
    assert "settings" in DEFAULT_CUSTOM_SECTIONS


def test_restore_session_keeps_custom_permissions(monkeypatch):
    """刷新恢复会话必须带回 permissions，否则 custom 用户权限会回退默认。"""
    import types
    import auth.session as session_mod

    perm = {"sections": ["settings", "feedback"],
            "features": {"can_local_compute": False}}
    dummy_st = types.SimpleNamespace(query_params={"token": "tok"})
    monkeypatch.setattr(session_mod, "st", dummy_st)
    monkeypatch.setattr(session_mod, "get_session_token", lambda: "tok")
    monkeypatch.setattr(session_mod, "_cookie_token", lambda: "tok")
    monkeypatch.setattr(session_mod, "validate_session",
                        lambda t: {"success": True, "username": "u", "role": "custom",
                                   "permissions": perm})

    out = session_mod.restore_session()
    assert out["permissions"] == perm
    assert out["role"] == "custom"

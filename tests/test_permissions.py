"""板块级权限：角色解析与自定义角色模板测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.common.constants import (ROLES, SECTION_KEYS, SECTION_LABELS,  # noqa: E402
                                 DEFAULT_CUSTOM_SECTIONS, resolve_role)


def test_section_keys_cover_all_nav_pages():
    """9 个板块 key 与 label 一一对应，且无重复。"""
    assert len(SECTION_KEYS) == len(SECTION_LABELS) == 9
    assert set(SECTION_KEYS) == set(SECTION_LABELS)


def test_builtin_roles_have_valid_sections():
    """内置三角色 sections 必须是 SECTION_KEYS 的子集且非空。"""
    for name in ("admin", "operator", "viewer"):
        secs = ROLES[name]["sections"]
        assert secs, f"{name} 板块不能为空"
        assert set(secs).issubset(SECTION_KEYS)
        assert len(secs) == len(set(secs)), f"{name} 板块重复"


def test_admin_sees_all_operator_loses_system_viewer_readonly():
    assert ROLES["admin"]["sections"] == SECTION_KEYS
    assert "system" not in ROLES["operator"]["sections"]
    assert "system" not in ROLES["viewer"]["sections"]
    assert "algo_import" not in ROLES["viewer"]["sections"]
    assert "status" not in ROLES["viewer"]["sections"]
    # 功能权限向后兼容：访客可跑仿真但不能配置/导出
    assert ROLES["viewer"]["can_run_simulation"] is True
    assert ROLES["viewer"]["can_configure"] is False
    assert ROLES["viewer"]["can_export"] is False


def test_resolve_role_returns_copy_and_keeps_can_flags():
    role = resolve_role("admin")
    assert role["sections"] == SECTION_KEYS
    assert role["can_manage_users"] is True
    # 返回的是副本，改 sections 不影响常量
    role["sections"] = ["settings"]
    assert ROLES["admin"]["sections"] == SECTION_KEYS


def test_resolve_role_custom_uses_permissions():
    perms = ["settings", "feedback"]
    role = resolve_role("custom", permissions=perms)
    assert role["sections"] == perms
    # 功能权限与操作员一致
    assert role["can_configure"] is True
    assert role["can_manage_users"] is False
    assert role["can_import_algo"] is False


def test_resolve_role_custom_fallback_on_missing_permissions():
    role = resolve_role("custom", permissions=None)
    assert role["sections"] == DEFAULT_CUSTOM_SECTIONS


def test_resolve_role_custom_filters_unknown_sections():
    role = resolve_role("custom", permissions=["settings", "not_exist", "feedback"])
    assert role["sections"] == ["settings", "feedback"]


def test_resolve_role_unknown_role_falls_back_to_viewer():
    role = resolve_role("superadmin")
    assert role["label"] == "访客"
    assert role["can_manage_users"] is False


def test_default_custom_sections_valid_and_sane():
    assert DEFAULT_CUSTOM_SECTIONS == ["settings", "layout", "path", "metrics", "history", "feedback"]
    assert set(DEFAULT_CUSTOM_SECTIONS).issubset(SECTION_KEYS)

"""用户名修改：预处理纯函数与包装层存在性测试（不启动 Streamlit）。"""

import sys
from pathlib import Path

# app.py 运行时会注入 src；测试环境手动注入后即可导入 auth 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from auth.users import _clean_username  # noqa: E402
from auth.users import change_username, admin_rename_user  # noqa: E402


def test_clean_username_strips_whitespace():
    """用户名预处理：去首尾空白，空值安全。"""
    assert _clean_username("  alice  ") == "alice"
    assert _clean_username("bob") == "bob"
    assert _clean_username("") == ""
    assert _clean_username(None) == ""


def test_clean_username_preserves_inner_spaces():
    """只去首尾，保留中间内容（中文用户名等）。"""
    assert _clean_username("  车主 一号  ") == "车主 一号"


def test_username_change_wrappers_exist():
    """迁移 16 的两个 RPC 包装层已注册且可调用。"""
    assert callable(change_username)
    assert callable(admin_rename_user)

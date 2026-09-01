"""local_worker.py 输出编码兜底回归测试。

背景：Windows 控制台/重定向输出默认使用 GBK（cp936）编码，
local_worker 启动时打印的 ✓/✗/▶ 等 Unicode 符号会触发
UnicodeEncodeError，导致 worker 起不来。修复后模块导入时会为
stdout/stderr 设置 errors="replace"，不可编码符号降级为 ? 而不是崩溃。
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_worker_unicode_print_survives_gbk_stdout():
    """在 GBK stdout 下导入 local_worker 并打印 ✓，进程不得崩溃。"""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import local_worker\n"
        "print('✓ ok')\n"
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "gbk"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="gbk",
        timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "ok" in proc.stdout

"""校验项目中所有 .py 文件不超过 200 行（AGENTS.md 3.2.1 强制规则）。

用法：py scripts/check_file_lines.py
退出码：0=全部合规；1=存在超限文件。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_LINES = 200
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def main() -> int:
    offenders = []
    for p in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        n = sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
        if n > MAX_LINES:
            offenders.append((p.relative_to(ROOT).as_posix(), n))
    if offenders:
        print(f"[FAIL] {len(offenders)} 个文件超过 {MAX_LINES} 行：")
        for name, n in offenders:
            print(f"  {n:5d}  {name}")
        return 1
    print(f"[OK] 所有 .py 文件均不超过 {MAX_LINES} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Validate starter-package structure and ongoing project-state consistency.

Default behavior is read-only. Use --write-report only when an explicit JSON
snapshot is needed. Passing the structural check does not prove that future
models, algorithms, citations, code, or experimental conclusions are correct.
"""

try:
    from .starter_checks._main import main  # 作为 scripts 包成员被导入时
except ImportError:
    from starter_checks._main import main  # 直接 python scripts/... 运行时

if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations
"""自检基础：常量、front matter 解析、DOCX 校验、文件系统遍历。"""

import json
import os
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "docs" / "启动包自动检查结果.json"
CHECK_VERSION = "3.0"

ALLOWED_STAGE_STATUS = {
    "not_started", "in_progress", "awaiting_review", "approved", "blocked", "superseded",
}
ALLOWED_STAGES = {"A", "B", "C", "D"}

PRUNED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".ipynb_checkpoints", ".idea", ".vscode", "build", "dist",
    "htmlcov", "tmp", "temp", "logs",
}
RUNTIME_PREFIXES = {
    "outputs", "data/raw", "data/interim", "data/processed", "data/synthetic/generated",
}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无效 JSON 风格 YAML 值：{value}: {exc}") from exc
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无效字符串：{value}: {exc}") from exc
    return value


def parse_front_matter(path: Path) -> dict[str, Any]:
    text = read_text(path)
    if not text.startswith("---\n"):
        raise ValueError(f"{path.relative_to(ROOT)} 缺少 YAML front matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"{path.relative_to(ROOT)} front matter 未闭合")

    result: dict[str, Any] = {}
    for line_no, raw in enumerate(text[4:end].splitlines(), start=2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")):
            raise ValueError(
                f"{path.relative_to(ROOT)}:{line_no} 使用了缩进嵌套 YAML；"
                "本项目状态 front matter 必须保持扁平，复杂列表使用单行 JSON"
            )
        if ":" not in raw:
            raise ValueError(f"{path.relative_to(ROOT)}:{line_no} 不是有效的 key: value")
        key, value = raw.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"{path.relative_to(ROOT)}:{line_no} 键名为空")
        if key in result:
            raise ValueError(f"{path.relative_to(ROOT)}:{line_no} 键重复：{key}")
        result[key] = parse_scalar(value)
    return result


def check_docx(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"DOCX 损坏：{path.name}，首个坏成员：{bad}")
        required = {"[Content_Types].xml", "word/document.xml"}
        missing = required.difference(archive.namelist())
        if missing:
            raise ValueError(f"DOCX 缺少必要成员：{path.name}: {sorted(missing)}")


def is_runtime_path(relative: Path) -> bool:
    posix = relative.as_posix()
    if any(part in PRUNED_DIRS for part in relative.parts):
        return True
    if relative.suffix.lower() in IGNORED_SUFFIXES:
        return True
    for prefix in RUNTIME_PREFIXES:
        if posix == prefix:
            return True
        if posix.startswith(prefix + "/") and relative.name != ".gitkeep":
            return True
    return False


def iter_controlled_files() -> Iterable[Path]:
    for directory, dirnames, filenames in os.walk(ROOT):
        dir_path = Path(directory)
        rel_dir = dir_path.relative_to(ROOT)
        dirnames[:] = [
            name for name in dirnames
            if name not in PRUNED_DIRS and not is_runtime_path(rel_dir / name)
        ]
        for filename in filenames:
            path = dir_path / filename
            relative = path.relative_to(ROOT)
            if not is_runtime_path(relative):
                yield path


def git_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)


def detect_git_state() -> tuple[bool, str | None, str | None]:
    inside = git_command("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False, None, None
    branch_result = git_command("branch", "--show-current")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    commit_result = git_command("rev-parse", "HEAD")
    commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
    return True, branch or None, commit

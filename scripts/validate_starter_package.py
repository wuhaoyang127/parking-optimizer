"""Validate starter-package structure and ongoing project-state consistency.

Default behavior is read-only. Use --write-report only when an explicit JSON
snapshot is needed. Passing the structural check does not prove that future
models, algorithms, citations, code, or experimental conclusions are correct.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "启动包自动检查结果.json"
CHECK_VERSION = "3.0"

ALLOWED_STAGE_STATUS = {
    "not_started",
    "in_progress",
    "awaiting_review",
    "approved",
    "blocked",
    "superseded",
}
ALLOWED_STAGES = {"A", "B", "C", "D"}

PRUNED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".ipynb_checkpoints",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "htmlcov",
    "tmp",
    "temp",
    "logs",
}
RUNTIME_PREFIXES = {
    "outputs",
    "data/raw",
    "data/interim",
    "data/processed",
    "data/synthetic/generated",
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
            raise ValueError(
                f"{path.relative_to(ROOT)}:{line_no} 不是有效的 key: value"
            )
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
            name
            for name in dirnames
            if name not in PRUNED_DIRS
            and not is_runtime_path(rel_dir / name)
        ]
        for filename in filenames:
            path = dir_path / filename
            relative = path.relative_to(ROOT)
            if not is_runtime_path(relative):
                yield path


def git_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def detect_git_state() -> tuple[bool, str | None, str | None]:
    inside = git_command("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False, None, None

    branch_result = git_command("branch", "--show-current")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    branch_value = branch or None

    commit_result = git_command("rev-parse", "HEAD")
    commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
    return True, branch_value, commit


def validate_blockers(status: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    current = status.get("current_stage_blockers")
    if not isinstance(current, list) or any(
        not isinstance(item, str) or not item.strip() for item in current
    ):
        errors.append("current_stage_blockers 必须是字符串组成的 JSON 数组")

    downstream = status.get("downstream_blockers")
    if not isinstance(downstream, list):
        errors.append("downstream_blockers 必须是 JSON 对象数组")
        return errors

    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(downstream):
        if not isinstance(item, dict):
            errors.append(f"downstream_blockers[{index}] 必须是对象")
            continue
        extra = set(item).difference({"target_stage", "issue"})
        missing = {"target_stage", "issue"}.difference(item)
        if missing:
            errors.append(
                f"downstream_blockers[{index}] 缺少字段：{sorted(missing)}"
            )
        if extra:
            errors.append(
                f"downstream_blockers[{index}] 存在未定义字段：{sorted(extra)}"
            )
        target = item.get("target_stage")
        issue = item.get("issue")
        if target not in ALLOWED_STAGES:
            errors.append(
                f"downstream_blockers[{index}].target_stage 必须是 A/B/C/D"
            )
        if not isinstance(issue, str) or not issue.strip():
            errors.append(
                f"downstream_blockers[{index}].issue 必须是非空字符串"
            )
        if isinstance(target, str) and isinstance(issue, str):
            key = (target, issue.strip())
            if key in seen:
                errors.append(f"downstream_blockers[{index}] 与前项重复")
            seen.add(key)
    return errors


def validate_status(
    status: dict[str, Any],
    mode: str,
    actual_git_initialized: bool,
    actual_branch: str | None,
) -> list[str]:
    errors: list[str] = []

    required_keys = {
        "project",
        "status_version",
        "last_updated",
        "current_stage",
        "stage_status",
        "current_milestone",
        "git_initialized",
        "current_branch",
        "current_exec_plan",
        "latest_handoff",
        "next_prompt",
        "current_stage_blockers",
        "downstream_blockers",
    }
    missing = sorted(required_keys.difference(status))
    if missing:
        errors.append(f"PROJECT_STATUS 缺少必要字段：{missing}")

    stage = status.get("current_stage")
    if stage not in ALLOWED_STAGES:
        errors.append("current_stage 必须是 A/B/C/D")

    stage_status = status.get("stage_status")
    if stage_status not in ALLOWED_STAGE_STATUS:
        errors.append(
            "stage_status 必须是：" + ", ".join(sorted(ALLOWED_STAGE_STATUS))
        )

    errors.extend(validate_blockers(status))

    for key in ("next_prompt", "current_exec_plan", "latest_handoff"):
        value = status.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{key} 必须是 null 或非空相对路径")
            continue
        candidate = ROOT / value
        try:
            candidate.resolve().relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{key} 不能指向项目目录外：{value}")
            continue
        if not candidate.exists():
            errors.append(f"{key} 指向的文件不存在：{value}")

    declared_initialized = status.get("git_initialized")
    declared_branch = status.get("current_branch")

    if not isinstance(declared_initialized, bool):
        errors.append("git_initialized 必须是 true 或 false")

    if declared_branch is not None and (
        not isinstance(declared_branch, str) or not declared_branch.strip()
    ):
        errors.append("current_branch 必须是 null 或非空字符串")

    if mode == "initial":
        if actual_git_initialized:
            errors.append("--initial 模式要求项目尚未初始化 Git")
        if declared_initialized is not False:
            errors.append("--initial 模式要求 git_initialized: false")
        if declared_branch is not None:
            errors.append("--initial 模式要求 current_branch: null")
    else:
        if declared_initialized != actual_git_initialized:
            errors.append(
                "PROJECT_STATUS 的 git_initialized 与实际 Git 状态不一致："
                f"声明={declared_initialized}，实际={actual_git_initialized}"
            )
        if actual_git_initialized:
            if declared_branch != actual_branch:
                errors.append(
                    "PROJECT_STATUS 的 current_branch 与实际分支不一致："
                    f"声明={declared_branch!r}，实际={actual_branch!r}"
                )
        elif declared_branch is not None:
            errors.append("未初始化 Git 时 current_branch 必须为 null")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查智能停车场项目启动包和持续项目状态的一致性。"
    )
    parser.add_argument(
        "--initial",
        action="store_true",
        help="强制按刚解压、尚未初始化 Git 的初始包状态检查。",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="显式更新 docs/启动包自动检查结果.json；默认只读。",
    )
    args = parser.parse_args()

    mode = "initial" if args.initial else "project"
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    required = [
        "AGENTS.md",
        "PROJECT_STATUS.md",
        "README.md",
        ".gitignore",
        ".agent/PLANS.md",
        "docs/候选算法路线.md",
        "docs/ChatGPT桌面端Codex使用指南.md",
        "docs/Git工作流.md",
        "docs/handoffs/TEMPLATE.md",
        "docs/archive/README.md",
        "prompts/A_研究与路线决策.md",
        "prompts/B_数学模型与工程设计.md",
        "prompts/C/C0_阶段C总控.md",
        "prompts/D/D0_阶段D总控.md",
        "prompts/D/D2_交互演示系统.md",
        "prompts/阶段验收与复核.md",
        "prompts/项目状态更新与新对话交接.md",
        "references/original/大创项目申请书(修改) (1).docx",
        "references/original/停车场Dijkstra-SA算法说明文档_含变量表 (1).docx",
    ]
    missing = [rel for rel in required if not (ROOT / rel).exists()]
    checks["required_files"] = {"missing": missing}
    if missing:
        errors.append(f"缺少必要文件：{missing}")

    obsolete_files = [
        "docs/Windows_Codex使用指南.md",
        "prompts/D/D2_Streamlit演示.md",
    ]
    present_obsolete = [rel for rel in obsolete_files if (ROOT / rel).exists()]
    checks["obsolete_files"] = {"present": present_obsolete}
    if present_obsolete:
        errors.append(f"仍存在过期文件：{present_obsolete}")

    controlled_files = sorted(iter_controlled_files())
    md_files = [path for path in controlled_files if path.suffix.lower() == ".md"]
    json_files = [path for path in controlled_files if path.suffix.lower() == ".json"]

    fence_errors: list[str] = []
    for path in md_files:
        try:
            text = read_text(path)
        except UnicodeDecodeError as exc:
            errors.append(f"UTF-8 读取失败：{path.relative_to(ROOT)}: {exc}")
            continue
        if text.count("```") % 2 != 0:
            fence_errors.append(str(path.relative_to(ROOT)))
    checks["markdown"] = {
        "controlled_markdown_count": len(md_files),
        "unbalanced_fences": fence_errors,
    }
    if fence_errors:
        errors.append(f"Markdown 代码块未闭合：{fence_errors}")

    json_errors: list[str] = []
    for path in json_files:
        try:
            json.loads(read_text(path))
        except json.JSONDecodeError as exc:
            json_errors.append(f"{path.relative_to(ROOT)}: {exc}")
    checks["json"] = {"errors": json_errors}
    if json_errors:
        errors.extend(json_errors)

    actual_git_initialized, actual_branch, actual_commit = detect_git_state()
    try:
        status = parse_front_matter(ROOT / "PROJECT_STATUS.md")
        status_errors = validate_status(
            status=status,
            mode=mode,
            actual_git_initialized=actual_git_initialized,
            actual_branch=actual_branch,
        )
        checks["project_status"] = {
            "mode": mode,
            "actual_git_initialized": actual_git_initialized,
            "actual_branch": actual_branch,
            "actual_commit": actual_commit,
            "errors": status_errors,
        }
        errors.extend(status_errors)
    except Exception as exc:
        errors.append(f"PROJECT_STATUS 检查失败：{exc}")

    docx_errors: list[str] = []
    for rel in required[-2:]:
        path = ROOT / rel
        if path.exists():
            try:
                check_docx(path)
            except Exception as exc:
                docx_errors.append(str(exc))
    checks["docx"] = {"errors": docx_errors}
    errors.extend(docx_errors)

    obsolete_terms = [
        "docs/算法路线研究结论.md",
        "docs/Windows_Codex使用指南.md",
        "D2_Streamlit演示.md",
    ]
    obsolete_refs: list[str] = []
    for path in md_files:
        text = read_text(path)
        for term in obsolete_terms:
            if term in text:
                obsolete_refs.append(f"{path.relative_to(ROOT)} -> {term}")
    checks["obsolete_references"] = obsolete_refs
    if obsolete_refs:
        errors.append(f"存在过期引用：{obsolete_refs}")

    old_product_phrases = ["Windows Codex App", "Codex App for Windows"]
    old_product_refs: list[str] = []
    for path in md_files:
        text = read_text(path)
        for phrase in old_product_phrases:
            if phrase in text:
                old_product_refs.append(f"{path.relative_to(ROOT)} -> {phrase}")
    checks["old_product_wording"] = old_product_refs
    if old_product_refs:
        errors.append(f"存在过期产品表述：{old_product_refs}")

    git_issues: list[str] = []
    for rel in [
        "README.md",
        "docs/ChatGPT桌面端Codex使用指南.md",
        "docs/Git工作流.md",
    ]:
        text = read_text(ROOT / rel)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.strip() == "git init":
                git_issues.append(f"{rel}:{line_no} 使用未指定主分支的 git init")
            if line.strip() == "git pull":
                git_issues.append(f"{rel}:{line_no} 对无远程初始仓库直接 git pull")
    checks["git_commands"] = git_issues
    errors.extend(git_issues)

    a_text = read_text(ROOT / "prompts/A_研究与路线决策.md")
    a_forbidden = ["离线、在线、滚动时域各自用途", "- 主求解器；"]
    a_hits = [item for item in a_forbidden if item in a_text]
    checks["stage_a_route_neutrality"] = a_hits
    if a_hits:
        errors.append(f"阶段 A 最终决策仍有路线诱导：{a_hits}")

    b_text = read_text(ROOT / "prompts/B_数学模型与工程设计.md")
    b_forbidden = [
        "滚动窗口；",
        "线性化或 CP-SAT 表达",
        "3. 滚动时域模型",
        "CP-SAT 验证脚本",
        "- 离线 CP-SAT；",
        "- 滚动时域 CP-SAT；",
        "窗口长度和求解时限实验",
        "04_离线在线滚动时域.md",
    ]
    b_hits = [item for item in b_forbidden if item in b_text]
    checks["stage_b_route_neutrality"] = b_hits
    if b_hits:
        errors.append(f"阶段 B 仍预设具体路线：{b_hits}")

    d1_text = read_text(ROOT / "prompts/D/D1_CLI与服务接口.md")
    d_issues: list[str] = []
    if "供 Streamlit 调用" in d1_text:
        d_issues.append("D1 服务接口仍绑定 Streamlit")
    if (ROOT / "prompts/D/D2_Streamlit演示.md").exists():
        d_issues.append("D2 仍以 Streamlit 固定命名")
    checks["stage_d_framework_neutrality"] = d_issues
    errors.extend(d_issues)

    checks["controlled_file_count"] = len(controlled_files)
    checks["excluded_runtime_examples"] = [
        ".git/",
        ".venv/",
        "Python caches",
        "outputs/ except .gitkeep",
        "ignored raw/interim/processed/generated data except .gitkeep",
    ]

    report = {
        "check_version": CHECK_VERSION,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "result": "passed" if not errors else "failed",
        "scope": [
            "required files and state pointers",
            "current/downstream blocker schema",
            "actual Git initialization and branch consistency",
            "DOCX container integrity",
            "UTF-8, Markdown fences, and JSON syntax",
            "obsolete references and product wording",
            "Git initialization commands",
            "A/B/D prompt neutrality",
            "controlled project file count excluding runtime directories",
        ],
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "limitations": [
            "The check does not prove future mathematical models are correct.",
            "The check does not prove an algorithm is optimal, useful, or deployable.",
            "The check does not validate future citations or experimental results.",
        ],
    }

    if args.write_report:
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if errors:
        print(f"项目结构与一致性检查失败（模式：{mode}）：")
        for error in errors:
            print(f"- {error}")
        if not args.write_report:
            print("本次检查未修改任何文件。")
        return 1

    print(
        f"项目结构与一致性检查通过（模式：{mode}，"
        f"受控文件：{len(controlled_files)} 个）。"
    )
    if not args.write_report:
        print("本次检查为只读，未修改任何文件。")
    else:
        print(f"已显式更新报告：{REPORT_PATH.relative_to(ROOT)}")
    print("注意：通过不代表未来算法、数学模型或实验结论必然正确。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

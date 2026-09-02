from __future__ import annotations
"""自检：文件存在性、Markdown/JSON/DOCX、过期引用、Git 命令。"""

import json
from typing import Any

from ._base import (ROOT, read_text, check_docx, iter_controlled_files,
                    detect_git_state, parse_front_matter)
from ._status import validate_status


def run_checks(mode: str) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    required = [
        "AGENTS.md", "PROJECT_STATUS.md", "README.md", ".gitignore",
        ".agent/PLANS.md", "docs/候选算法路线.md", "docs/ChatGPT桌面端Codex使用指南.md",
        "docs/Git工作流.md", "docs/handoffs/TEMPLATE.md", "docs/archive/README.md",
        "prompts/A_研究与路线决策.md", "prompts/B_数学模型与工程设计.md",
        "prompts/C/C0_阶段C总控.md", "prompts/D/D0_阶段D总控.md",
        "prompts/D/D2_交互演示系统.md", "prompts/阶段验收与复核.md",
        "prompts/项目状态更新与新对话交接.md",
        "references/original/大创项目申请书(修改) (1).docx",
        "references/original/停车场Dijkstra-SA算法说明文档_含变量表 (1).docx",
    ]
    missing = [rel for rel in required if not (ROOT / rel).exists()]
    checks["required_files"] = {"missing": missing}
    if missing:
        errors.append(f"缺少必要文件：{missing}")

    obsolete_files = [
        "docs/Windows_Codex使用指南.md", "prompts/D/D2_Streamlit演示.md",
    ]
    present_obsolete = [rel for rel in obsolete_files if (ROOT / rel).exists()]
    checks["obsolete_files"] = {"present": present_obsolete}
    if present_obsolete:
        errors.append(f"仍存在过期文件：{present_obsolete}")

    controlled_files = sorted(iter_controlled_files())
    md_files = [p for p in controlled_files if p.suffix.lower() == ".md"]
    json_files = [p for p in controlled_files if p.suffix.lower() == ".json"]

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
            status=status, mode=mode,
            actual_git_initialized=actual_git_initialized, actual_branch=actual_branch,
        )
        checks["project_status"] = {
            "mode": mode, "actual_git_initialized": actual_git_initialized,
            "actual_branch": actual_branch, "actual_commit": actual_commit,
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
        "docs/算法路线研究结论.md", "docs/Windows_Codex使用指南.md", "D2_Streamlit演示.md",
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
    for rel in ["README.md", "docs/ChatGPT桌面端Codex使用指南.md", "docs/Git工作流.md"]:
        text = read_text(ROOT / rel)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.strip() == "git init":
                git_issues.append(f"{rel}:{line_no} 使用未指定主分支的 git init")
            if line.strip() == "git pull":
                git_issues.append(f"{rel}:{line_no} 对无远程初始仓库直接 git pull")
    checks["git_commands"] = git_issues
    errors.extend(git_issues)

    checks["controlled_file_count"] = len(controlled_files)
    checks["excluded_runtime_examples"] = [
        ".git/", ".venv/", "Python caches", "outputs/ except .gitkeep",
        "ignored raw/interim/processed/generated data except .gitkeep",
    ]
    return errors, warnings, checks

from __future__ import annotations
"""自检：PROJECT_STATUS front matter 校验。"""

from typing import Any

from ._base import ROOT, ALLOWED_STAGES, ALLOWED_STAGE_STATUS


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
            errors.append(f"downstream_blockers[{index}] 缺少字段：{sorted(missing)}")
        if extra:
            errors.append(f"downstream_blockers[{index}] 存在未定义字段：{sorted(extra)}")
        target = item.get("target_stage")
        issue = item.get("issue")
        if target not in ALLOWED_STAGES:
            errors.append(f"downstream_blockers[{index}].target_stage 必须是 A/B/C/D")
        if not isinstance(issue, str) or not issue.strip():
            errors.append(f"downstream_blockers[{index}].issue 必须是非空字符串")
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
        "project", "status_version", "last_updated", "current_stage", "stage_status",
        "current_milestone", "git_initialized", "current_branch", "current_exec_plan",
        "latest_handoff", "next_prompt", "current_stage_blockers", "downstream_blockers",
    }
    missing = sorted(required_keys.difference(status))
    if missing:
        errors.append(f"PROJECT_STATUS 缺少必要字段：{missing}")

    stage = status.get("current_stage")
    if stage not in ALLOWED_STAGES:
        errors.append("current_stage 必须是 A/B/C/D")

    stage_status = status.get("stage_status")
    if stage_status not in ALLOWED_STAGE_STATUS:
        errors.append("stage_status 必须是：" + ", ".join(sorted(ALLOWED_STAGE_STATUS)))

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

from __future__ import annotations
"""自检：A/B/D 提示词路线中性检查。"""

from ._base import ROOT, read_text


def run_prompt_neutrality_checks() -> list[str]:
    errors: list[str] = []

    a_text = read_text(ROOT / "prompts/A_研究与路线决策.md")
    a_forbidden = ["离线、在线、滚动时域各自用途", "- 主求解器；"]
    a_hits = [item for item in a_forbidden if item in a_text]
    if a_hits:
        errors.append(f"阶段 A 最终决策仍有路线诱导：{a_hits}")

    b_text = read_text(ROOT / "prompts/B_数学模型与工程设计.md")
    b_forbidden = [
        "滚动窗口；", "线性化或 CP-SAT 表达", "3. 滚动时域模型", "CP-SAT 验证脚本",
        "- 离线 CP-SAT；", "- 滚动时域 CP-SAT；", "窗口长度和求解时限实验",
        "04_离线在线滚动时域.md",
    ]
    b_hits = [item for item in b_forbidden if item in b_text]
    if b_hits:
        errors.append(f"阶段 B 仍预设具体路线：{b_hits}")

    d1_text = read_text(ROOT / "prompts/D/D1_CLI与服务接口.md")
    d_issues: list[str] = []
    if "供 Streamlit 调用" in d1_text:
        d_issues.append("D1 服务接口仍绑定 Streamlit")
    if (ROOT / "prompts/D/D2_Streamlit演示.md").exists():
        d_issues.append("D2 仍以 Streamlit 固定命名")
    errors.extend(d_issues)
    return errors

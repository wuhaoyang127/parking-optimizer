from __future__ import annotations
"""自检入口：组装 checks 并输出报告。"""

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from ._base import ROOT, REPORT_PATH, CHECK_VERSION
from ._checks import run_checks
from ._prompt_checks import run_prompt_neutrality_checks


def main() -> int:
    parser = argparse.ArgumentParser(description="检查智能停车场项目启动包和持续项目状态的一致性。")
    parser.add_argument("--initial", action="store_true",
                        help="强制按刚解压、尚未初始化 Git 的初始包状态检查。")
    parser.add_argument("--write-report", action="store_true",
                        help="显式更新 docs/启动包自动检查结果.json；默认只读。")
    args = parser.parse_args()

    mode = "initial" if args.initial else "project"
    errors, warnings, checks = run_checks(mode)
    errors.extend(run_prompt_neutrality_checks())

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
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if errors:
        print(f"项目结构与一致性检查失败（模式：{mode}）：")
        for error in errors:
            print(f"- {error}")
        if not args.write_report:
            print("本次检查未修改任何文件。")
        return 1

    controlled = checks.get("controlled_file_count", 0)
    print(f"项目结构与一致性检查通过（模式：{mode}，受控文件：{controlled} 个）。")
    if not args.write_report:
        print("本次检查为只读，未修改任何文件。")
    else:
        print(f"已显式更新报告：{REPORT_PATH.relative_to(ROOT)}")
    print("注意：通过不代表未来算法、数学模型或实验结论必然正确。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

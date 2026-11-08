# ruff: noqa: RUF001
"""D5 data adaptation quality-report page."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from parking_opt.app.data import load_builtin_adaptation_report


def render_data_page(repository_root: Path) -> None:
    """Render the D5 sanitized quality report for the committed synthetic example."""

    st.title("数据导入与校验")
    st.caption("外部字段 → 显式映射 → 冻结 v1 Schema → 语义/可达性 → 新迁移副本")
    try:
        report = load_builtin_adaptation_report(repository_root)
    except (OSError, TypeError, ValueError) as exc:
        st.error("D5 示例包无法读取；页面已失败关闭，且不会回显输入内容或绝对路径。")
        st.stop()
        raise AssertionError("st.stop() must interrupt execution") from exc
    source_col, privacy_col, status_col = st.columns(3)
    with source_col:
        st.badge("SYNTHETIC｜非实测", color="blue", icon=":material/science:")
        st.caption(f"机器标签：{report.source_kind}")
    with privacy_col:
        st.badge("ANONYMOUS", color="green", icon=":material/shield:")
        st.caption(f"隐私标签：{report.privacy_classification}")
    with status_col:
        if report.accepted:
            st.badge("接口校验通过", color="green", icon=":material/verified:")
        else:
            st.badge("失败关闭", color="red", icon=":material/block:")
        st.caption(f"目标契约：v{report.target_schema_version}")
    st.warning("当前只验证适配接口和 synthetic 示例，现实校准尚未完成；不得把本页描述为真实停车场验证。脱敏映射必须在仓库外完成。")
    if not report.accepted:
        st.error("导入被安全拒绝。错误仅显示稳定代码：" + "、".join(item.code for item in report.failures))
    st.subheader("导入摘要")
    file_col, event_col, mapping_col, warning_col = st.columns(4)
    file_col.metric("来源文件", report.file_count, border=True)
    event_col.metric("匿名事件", report.event_count, border=True)
    mapping_col.metric("显式映射字段", report.mapped_layout_field_count + report.mapped_event_field_count, border=True)
    warning_col.metric("数据缺口/警告", len(report.warnings), border=True)
    st.caption(f"模式：{report.mode}｜总字节：{report.total_bytes:,}｜原始输入只读；需要迁移时写入新的独立目录。")
    report_tab, provenance_tab, gap_tab = st.tabs(("分层质量报告", "来源 SHA-256", "未识别与未校准"))
    with report_tab:
        st.dataframe(
            [{"阶段": item.stage, "状态": {"passed": "通过", "warning": "警告", "failed": "拒绝"}.get(item.status, item.status), "代码": item.code, "文件": item.artifact or "包级", "说明": item.message, "定位": item.json_pointer or "—", "修复建议": item.fix_hint or "—"} for item in report.checks],
            width="stretch",
            hide_index=True,
        )
        st.caption("检查包含路径、大小、UTF-8/JSON、PII、单位、时区、字段映射、v1 Schema、重复 ID、引用、纵深连续性和入口—位置—出口可达性。")
    with provenance_tab:
        st.dataframe([{"来源文件": item.artifact, "字节": item.size_bytes, "SHA-256": item.sha256} for item in report.source_digests], width="stretch", hide_index=True)
        st.info("迁移副本会保存这些来源哈希；不会保存仓库外的脱敏映射表。")
    with gap_tab:
        if report.unrecognized_fields:
            st.dataframe([{"未映射字段名": item} for item in report.unrecognized_fields], width="stretch", hide_index=True)
        else:
            st.success("示例包没有未映射的顶层字段。")
        st.dataframe([{"参数": item.parameter, "状态": item.status, "原因": item.reason} for item in report.calibration_gaps], width="stretch", hide_index=True)
        st.caption("参数值即使提供，也只标记“已提供、未验证”，不会自动生成校准结论。")
    with st.expander("实际匿名数据接入步骤", expanded=False):
        st.markdown("1. 在仓库外删除车牌、姓名、电话、邮箱、证件号和可逆映射；\n2. 复制 D5 模板并填写局部米制布局、匿名事件和显式字段映射；\n3. 先运行只读检查，再将通过的数据写入新的 `data/interim/` 目录；\n4. 保留来源 SHA-256 和质量报告，原始文件始终不覆盖。")

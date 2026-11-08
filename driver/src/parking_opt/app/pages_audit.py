# ruff: noqa: RUF001
"""D4 saved-decision audit rendering."""

from __future__ import annotations

import streamlit as st

from parking_opt.application.presentation import ValidatedDemoBundle, decision_audit


def _render_decision_audit(bundle: ValidatedDemoBundle) -> None:
    decision_id = st.selectbox("保存决策", bundle.decision_ids, key="d4_decision_id")
    audit = decision_audit(bundle, decision_id)
    st.caption(f"决策 `{audit.decision_id}`｜目标请求 `{audit.target_request_id}`｜匿名车辆 `{audit.target_anonymous_vehicle_id}`")
    primary, solver, validation, incumbent = st.columns(4)
    primary.metric("即时主决定", {"WAIT": "等待", "REJECT": "拒绝", "RECOMMEND_ACTIONS": "推荐动作", "REQUEST_MANUAL_INTERVENTION": "请求人工"}.get(audit.primary_decision, audit.primary_decision), border=True)
    solver.metric("原求解状态", {"TIME_LIMIT_NO_FEASIBLE": "限时无解", "TIME_LIMIT_FEASIBLE": "限时可行", "OPTIMAL": "已证最优", "NOT_RUN": "未运行求解器"}.get(audit.solver_status, audit.solver_status), border=True)
    validation.metric("结果校验", {"VALID": "有效", "INVALID": "无效"}.get(audit.validation_status, audit.validation_status), border=True)
    incumbent.metric("incumbent 证据", {"NO_FEASIBLE_INCUMBENT": "无可行值", "SAVED_VALIDATED_INCUMBENT": "已保存并校验", "NOT_APPLICABLE_OPTIMAL": "最优解，无需区分", "NOT_REPORTED_BY_SAVED_RESULT": "保存结果未报告"}.get(audit.incumbent_status, audit.incumbent_status), border=True)
    st.caption(f"机器状态：primary={audit.primary_decision}｜solver={audit.solver_status}｜validation={audit.validation_status}｜incumbent={audit.incumbent_status}")
    st.subheader("触发事件与可见信息证据")
    trigger_rows = [
        {"字段": "trigger_event_id", "保存值": audit.trigger_event_id or "未关联"},
        {"字段": "trigger_event_type", "保存值": audit.trigger_event_type or "未关联"},
        {"字段": "trigger_sim_time_s", "保存值": "未关联" if audit.trigger_sim_time_s is None else f"{audit.trigger_sim_time_s} s"},
        {"字段": "visible_snapshot_sha256", "保存值": audit.visible_snapshot_sha256},
        {"字段": "snapshot_content_status", "保存值": audit.snapshot_content_status},
    ]
    st.dataframe(trigger_rows, width="stretch", hide_index=True)
    st.warning("阶段 C 运行包保存了可见快照 SHA-256，但未持久化完整 ObservedSnapshot 内容。D4 只展示可核验哈希与触发事件，不重建或推测快照字段。")
    result_tab, timing_tab, evidence_tab = st.tabs(("结果与降级链", "预算与用时", "完整性证据"))
    with result_tab:
        if audit.actions:
            st.dataframe([{"动作": item.action_type, "匿名车辆": item.anonymous_vehicle_id, "起点": item.origin_position_id or "入口/当前状态", "终点": item.destination_position_id or item.destination_exit_id or "—", "距离": f"{item.distance_m:.2f} m", "建模时长": f"{item.modeled_duration_s} s"} for item in audit.actions], width="stretch", hide_index=True)
        else:
            st.info("该保存结果没有推荐动作；即时主决定本身仍保留。")
        st.caption("解释码：" + ("、".join(audit.explanation_codes) or "无"))
        if audit.used_fallback:
            st.warning(f"已记录 fallback：{audit.fallback_original_method} / {audit.fallback_original_solver_status} → {audit.fallback_strategy}；原因：{audit.fallback_reason}；耗时 {audit.fallback_elapsed_s:.3f} s。")
        else:
            st.success("该保存决策没有 fallback 记录。")
        if audit.candidate_generation:
            st.dataframe([{"候选计数": key, "保存值": value} for key, value in audit.candidate_generation], width="stretch", hide_index=True)
        if audit.candidate_truncation_reasons:
            st.caption("候选截断原因：" + "、".join(audit.candidate_truncation_reasons))
    with timing_tab:
        st.dataframe(
            [
                {"阶段": "校验与建模", "保存用时（秒）": audit.validation_and_modeling_s},
                {"阶段": "求解", "保存用时（秒）": audit.solver_s},
                {"阶段": "后验校验", "保存用时（秒）": audit.postsolve_validation_s},
                {"阶段": "最小日志预留", "保存用时（秒）": audit.minimum_logging_s},
                {"阶段": "求解器时间上限", "保存用时（秒）": audit.solver_time_limit_s},
                {"阶段": "端到端", "保存用时（秒）": audit.end_to_end_s},
            ],
            width="stretch",
            hide_index=True,
        )
        st.caption("这些是该决策的保存值，不是生产环境实时 SLA 测量。")
    with evidence_tab:
        st.dataframe(
            [
                {"证据": "config_sha256", "SHA-256": audit.config_sha256},
                {"证据": "layout_sha256", "SHA-256": audit.layout_sha256},
                {"证据": "visible_snapshot_sha256", "SHA-256": audit.visible_snapshot_sha256},
                {"证据": "input_model_sha256", "SHA-256": audit.input_model_sha256 or "NOT_APPLICABLE"},
            ],
            width="stretch",
            hide_index=True,
        )

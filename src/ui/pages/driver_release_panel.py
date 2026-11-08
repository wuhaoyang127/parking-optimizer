"""Explicit staged release and server validation/activation controls."""
import streamlit as st
import json
from driver_bridge.client import call, publish


def publish_from_existing_button(token, algo_name, params, note=None):
    # Existing page already enforces can_push_algo and login. Backend uses its
    # separate service credential, not the research user's session token.
    try:
        model = st.session_state.get("driver_trained_model") if algo_name == "ml_duration_tree" else None
        release = publish(algo_name, params, note, model=model,
                          seed=int(st.session_state.get("driver_release_seed", 0)))
        st.session_state.driver_pending_release = release["release_id"]
        return {"success": True, "release_id": release["release_id"]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def render_driver_releases():
    with st.container(border=True):
        st.subheader("车主端发布、校验与启用")
        st.caption("发布仅暂存；通过车主端校验后另行启用。存量行程保留原版本。")
        try:
            capability = call("/api/research/v1/capabilities")
            st.info("车主端已连接 · 支持：" + "、".join(capability["supported"]))
            st.dataframe([{"算法": row["algorithm_id"], "状态": row["status"],
                "输入要求": row.get("required_inputs", row.get("reason", "")),
                "参数": json.dumps(row.get("params", {}), ensure_ascii=False)}
                for row in capability.get("catalog", [])], hide_index=True)
            from ui.pages.driver_inputs_panel import render_driver_inputs
            render_driver_inputs()
            releases = call("/api/research/v1/releases")
            active = call("/api/admin/v1/driver-algorithm-activations/active", admin=True)["active"]
            active_hash = active["release_hash"] if active else None
            st.write("当前算法：", active["algorithm_id"] if active else "在线规则推荐（默认）")
            ids = [r["release_id"] for r in releases]
            pending = st.session_state.pop("driver_pending_release", None)
            if pending in ids:
                st.session_state.driver_release_selection = pending
                st.success("新版本已暂存，请校验后启用")
            if ids:
                selected = st.selectbox("待操作版本", ids, key="driver_release_selection")
                release = next(r for r in releases if r["release_id"] == selected)
                st.json(release)
                if st.button("运行车主端校验", key="driver_validate"):
                    result = call(f"/api/research/v1/releases/{selected}/validate", {}, admin=True)
                    st.json(result["validation"])
                    st.rerun()
                source_matches = release["source_hash"] == capability["source_hash"]
                if not source_matches:
                    st.warning("此版本属于旧源码，需重新发布和校验后才能启用")
                passed = bool(source_matches and release.get("validation") and release["validation"]["passed"])
                if st.button("启用此版本（影响新请求）", disabled=not passed, key="driver_activate"):
                    call("/api/admin/v1/driver-algorithm-activations", {
                        "release_id": selected, "expected_active_hash": active_hash}, admin=True)
                    st.success("版本已启用")
                    st.rerun()
            if st.button("回滚到默认在线规则", disabled=active is None, key="driver_rollback"):
                call("/api/admin/v1/driver-algorithm-activations", {
                    "release_id": None, "expected_active_hash": active_hash}, admin=True)
                st.rerun()
            render_trial_controls()
            render_backup_controls()
            if st.checkbox("显示最近执行与降级回执", key="driver_receipts"):
                st.json(call("/api/admin/v1/execution-receipts", admin=True))
        except Exception as exc:
            st.error(str(exc))


def render_trial_controls():
    """试用（按比例分流）与晋升/丢弃决策控制。"""
    st.subheader("试用（按比例分流）")
    st.caption("把已验证版本设为试用并分流到车主请求，观察回执后决定晋升或丢弃。")
    current = call("/api/admin/v1/algorithms/current", admin=True)
    trial = current.get("trial")
    stats = current.get("trial_stats", {})
    if trial:
        st.write("试用中：", trial["algorithm_id"], "｜比例", trial.get("trial_ratio"))
        st.write(f"试用回执：{stats.get('trial_request_count', 0)} 次请求，"
                 f"{stats.get('trial_success_count', 0)} 成功，"
                 f"{stats.get('trial_fallback_count', 0)} 降级")
        ratio_col, stop_col = st.columns(2)
        with ratio_col:
            new_ratio = st.number_input("试用比例", min_value=0.01, max_value=1.0,
                value=float(trial.get("trial_ratio") or 0.33), step=0.01, key="trial_ratio_input")
            if st.button("调整比例", key="trial_set_ratio"):
                call("/api/admin/v1/trials/ratio", {"ratio": new_ratio}, admin=True)
                st.rerun()
        with stop_col:
            if st.button("停止试用", key="trial_stop"):
                call("/api/admin/v1/trials/stop", admin=True)
                st.rerun()
    else:
        releases = call("/api/research/v1/releases")
        validated = [r for r in releases if r.get("validation")
                     and r["validation"]["passed"] and r.get("status") == "staged"]
        if validated:
            trial_id = st.selectbox("选择要试用的版本",
                [r["release_id"] for r in validated], key="trial_release_select")
            trial_ratio = st.number_input("试用比例", min_value=0.01, max_value=1.0,
                value=0.33, step=0.01, key="trial_ratio_start")
            research_score = st.number_input("研究评分", min_value=0.0, max_value=100.0,
                value=80.0, step=1.0, key="trial_score")
            if st.button("开始试用", key="trial_start"):
                call("/api/admin/v1/trials/start", {
                    "release_id": trial_id, "ratio": trial_ratio,
                    "research_score": research_score}, admin=True)
                st.rerun()
        else:
            st.info("暂无可试用的已验证版本")
    decisions = call("/api/research/v1/releases")
    awaiting = [r for r in decisions if r.get("status") == "awaiting_decision"]
    if awaiting:
        st.subheader("试用决策")
        for r in awaiting:
            promote_col, discard_col = st.columns(2)
            with promote_col:
                if st.button(f"晋升 {r['release_id']}", key=f"promote_{r['release_id']}"):
                    call("/api/admin/v1/trials/decide",
                         {"release_id": r["release_id"], "decision": "promote"}, admin=True)
                    st.rerun()
            with discard_col:
                confirm = st.checkbox("确认丢弃", key=f"confirm_discard_{r['release_id']}")
                if st.button(f"丢弃 {r['release_id']}", disabled=not confirm,
                             key=f"discard_{r['release_id']}"):
                    call("/api/admin/v1/trials/decide",
                         {"release_id": r["release_id"], "decision": "discard"}, admin=True)
                    st.rerun()


def render_backup_controls():
    """备选区：恢复或删除晋升时自动备份的旧正式版本。"""
    st.subheader("备选区（回滚）")
    st.caption("晋升时自动备份旧正式版本；可恢复或删除。")
    backups = call("/api/admin/v1/backups", admin=True)
    if not backups:
        st.info("暂无备选")
        return
    for backup in backups:
        with st.container(border=True):
            st.write(f"备份：{backup['release_id']}｜过期：{backup.get('expires_at')}")
            restore_col, delete_col = st.columns(2)
            with restore_col:
                if st.button(f"恢复 {backup['release_id']}", key=f"restore_{backup['release_id']}"):
                    call("/api/admin/v1/backups/restore",
                         {"release_id": backup["release_id"], "decision": "promote"}, admin=True)
                    st.rerun()
            with delete_col:
                confirm = st.checkbox("确认删除", key=f"confirm_delete_{backup['release_id']}")
                if st.button("删除备份", disabled=not confirm,
                             key=f"delete_{backup['release_id']}"):
                    call("/api/admin/v1/backups/delete",
                         {"release_id": backup["release_id"], "decision": "discard"}, admin=True)
                    st.rerun()


def eligible_test_runs(runs, supported):
    """Exclude offline or currently unpublishable strategies from automatic selection."""
    allowed = set(supported)
    if not st.session_state.get("driver_trained_model"):
        allowed.discard("ml_duration_tree")
    result = []
    for run in runs:
        metrics = run.get("metrics")
        if isinstance(metrics, list):
            filtered = [m for m in metrics if isinstance(m, dict) and m.get("strategy") in allowed]
            if filtered:
                result.append({**run, "metrics": filtered})
        elif isinstance(metrics, dict) and metrics.get("strategy") in allowed:
            result.append(run)
    return result

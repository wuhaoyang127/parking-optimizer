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
            if st.checkbox("显示最近执行与降级回执", key="driver_receipts"):
                st.json(call("/api/admin/v1/execution-receipts", admin=True))
        except Exception as exc:
            st.error(str(exc))


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

"""Historical training and scoped visible-observation import controls."""
import csv
import io
import json
import streamlit as st
from driver_bridge.client import call
from driver_bridge.training import train_history


def render_driver_inputs():
    with st.expander("查看本机车主会话与导出已完成历史"):
        try:
            sessions = call("/api/admin/v1/driver-sessions", admin=True)
            if sessions:
                labels = [s["session_id"] + " · " + s["parking_lot_id"] for s in sessions]
                selection = st.selectbox("车主会话", labels, key="driver_observed_session")
                scope = sessions[labels.index(selection)]
                from urllib.parse import urlencode
                query = urlencode({k: scope[k] for k in ("session_id", "parking_lot_id")})
                if st.button("读取当前输入与数据缺口", key="driver_read_context"):
                    st.json(call("/api/admin/v1/driver-input-context?" + query, admin=True))
                if st.button("准备已结束停车历史CSV", key="driver_export_history"):
                    st.session_state.driver_completed_csv = call(
                        "/api/admin/v1/completed-history.csv?" + query, admin=True, raw=True)
                    st.session_state.driver_completed_csv_scope = query
                if st.session_state.get("driver_completed_csv") and st.session_state.get("driver_completed_csv_scope") == query:
                    st.download_button("下载已完成历史CSV", st.session_state.driver_completed_csv,
                                       "completed-history.csv", "text/csv")
            else:
                st.caption("暂无车主会话；请先在车主端创建停车请求。")
        except Exception as exc:
            st.error(str(exc))
    st.number_input("发布随机种子（用于复现）", min_value=0, max_value=4294967295,
                    value=0, step=1, key="driver_release_seed")
    with st.expander("ML：训练已结束的历史停车样本"):
        st.caption("CSV列：record_id, arrival_at, departed_at, entrance_node_id；时间必须含时区，所有停车已结束。最新20%按时间留作验证，不参与训练。")
        history = st.file_uploader("历史停车CSV", type=["csv"], key="driver_history_csv")
        source = st.selectbox("历史来源", ["synthetic", "observed"], key="driver_model_source")
        depth = st.number_input("树最大深度", 2, 8, 4, key="driver_tree_depth")
        leaf = st.number_input("叶最小样本数", 1, 20, 5, key="driver_tree_leaf")
        entry = st.checkbox("使用入口特征", value=True, key="driver_tree_entry")
        if st.button("训练并暂存JSON模型", disabled=history is None, key="driver_train_model"):
            try:
                if history.size > 2_000_000:
                    raise ValueError("历史CSV最多2MB")
                rows = list(csv.DictReader(io.StringIO(history.getvalue().decode("utf-8-sig"))))
                params = {"max_depth": int(depth), "min_samples_leaf": int(leaf), "use_entry": entry}
                model = train_history(rows, params, source)
                st.session_state.driver_trained_model = model
                st.session_state.driver_trained_params = params
                st.success("历史模型已训练；发布ML时绑定此JSON模型，不上传Python或pickle")
            except Exception as exc:
                st.error(str(exc))
        model = st.session_state.get("driver_trained_model")
        if model:
            st.write({k: v for k, v in model.items() if k != "tree"})
            st.download_button("下载模型JSON", json.dumps(model, ensure_ascii=False, indent=2),
                               "duration-model.json", "application/json")
    with st.expander("RHO / 风险 / 时长：导入当前可见观测"):
        st.caption("JSON需含session_id、parking_lot_id、layout_hash、observed_at、source，以及已发生arrivals和带来源的occupants。按车主会话隔离；未知时间留空，不用未来真值补齐。")
        snapshot = st.file_uploader("当前可见观测JSON", type=["json"], key="driver_observation_json")
        if st.button("导入观测（不会改写车位占用）", disabled=snapshot is None, key="driver_import_observations"):
            try:
                if snapshot.size > 131072:
                    raise ValueError("观测JSON最多128KB")
                result = call("/api/admin/v1/visible-observations",
                              json.loads(snapshot.getvalue()), admin=True)
                st.success("已保存观测：" + result["input_hash"])
            except Exception as exc:
                st.error(str(exc))

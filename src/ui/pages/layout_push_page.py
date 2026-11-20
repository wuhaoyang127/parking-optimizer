"""页面：布局推送（把自定义布局推到车主端，作为新增停车场）。"""
from ui.common import *
from ui.common.custom_layouts import ensure_custom_layouts_loaded


_VENUE_LABELS = {"commercial": "商场", "school": "学校",
                 "hospital": "医院", "transport_hub": "交通枢纽"}


def render_layout_push(role):
    st.subheader("📤 布局推送")
    if not role.get("can_push_algo"):
        st.info("仅管理员或已开启「推送到车主端」权限的角色可操作。")
        return
    ensure_custom_layouts_loaded()
    customs = st.session_state.get("custom_layouts", {}) or {}
    if not customs:
        st.info("暂无自定义布局。请先在「停车场布局图」页导入或创建布局。")
        return
    labels = {lid: str(v.get("name", lid)) for lid, v in customs.items()}
    selected = st.selectbox("选择要推送的布局", list(labels), format_func=lambda x: labels[x])
    venue = st.selectbox("停车场类型", list(_VENUE_LABELS),
                         format_func=lambda x: _VENUE_LABELS[x])
    st.caption("推送后，车主端需重新部署/重启才会加载新布局。")
    if st.button("🚀 推送到车主端", type="primary"):
        data = customs[selected].get("data")
        if not isinstance(data, dict):
            st.error("布局数据无效，无法推送")
        else:
            lot_id = "lot-" + selected
            try:
                from auth.driver_layouts import push_driver_layout
                push_driver_layout({"id": lot_id, "name": labels[selected],
                                    "venue_type": venue, "data": data})
                st.success(f"已推送「{labels[selected]}」到车主端（lot_id={lot_id}）。"
                           "车主端重新部署后即可在停车场列表看到。")
            except Exception as e:
                st.error(f"推送失败：{e}")

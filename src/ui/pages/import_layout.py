"""系统设置页：布局导入（文档/上传校验/预览/添加/删除）。"""
from ui.common import *


def _load_layout_doc() -> str:
    """读取布局导入格式说明文档内容（网页内嵌展示，避免相对链接打不开）"""
    doc_path = Path(__file__).resolve().parents[2] / "docs" / "布局导入格式说明.md"
    try:
        return doc_path.read_text(encoding="utf-8")
    except Exception:
        return "说明文档加载失败，请查看 `docs/布局导入格式说明.md`"


def _build_custom(data):
    """lambda 包装：从预存 data 构建自定义布局"""
    net, spots = build_layout_from_json(data)
    return net, spots


def _render_import_layout():
    """上传自定义停车场布局（仅管理员调用；说明文档在 tab3 公共区展示）"""
    ensure_custom_layouts_loaded()
    if st.session_state.get("layout_restore_error"):
        st.warning(f"⚠️ 上次从云端恢复布局失败：{st.session_state.layout_restore_error}")
        if st.button("🔄 重试加载云端布局", key="retry_layout_restore"):
            st.session_state.pop("layout_restore_error", None)
            st.session_state.pop("layout_restore_retry_at", None)
            st.session_state.pop("custom_layouts", None)
            restore_custom_layouts()
            st.rerun()
    if "custom_layouts" not in st.session_state:
        st.session_state.custom_layouts = {}

    uploaded = st.file_uploader("📤 上传布局 JSON", type=["json"], key="import_layout")
    if uploaded is not None:
        try:
            data = json.loads(uploaded.read().decode("utf-8"))
            if "name" not in data or "nodes" not in data or "edges" not in data:
                st.error("JSON 格式不正确，需包含 name/nodes/edges 字段")
                st.stop()
            # 校验
            node_ids = {nd["id"] for nd in data["nodes"]}
            entry_ids = [nd["id"] for nd in data["nodes"] if nd.get("type") == "entry"]
            if not entry_ids:
                st.error("节点中必须至少包含一个 type='entry' 的入口节点")
                st.stop()
            for ed in data["edges"]:
                if ed["from"] not in node_ids or ed["to"] not in node_ids:
                    st.error(f"边 {ed['from']}→{ed['to']} 引用了不存在的节点")
                    st.stop()
            # 测试构建 + 连通性校验（每个车位必须从入口可达且能返回入口）
            net, spots = build_layout_from_json(data)
            pe_check = PathEngine(net)
            bad_in = [s.spot_id for s in spots
                      if not math.isfinite(pe_check.distance_to_spot(s.node_id))]
            bad_out = [s.spot_id for s in spots
                       if not math.isfinite(pe_check.shortest_distance(s.node_id, pe_check.entry_id))]
            if bad_in or bad_out:
                problems = list(dict.fromkeys(bad_in + bad_out))
                st.error("布局校验失败：以下车位与入口不连通（请检查 edges 是否双向完整、有无遗漏）："
                         + "、".join(problems[:12]) + ("…" if len(problems) > 12 else ""))
                st.stop()
            name = data["name"]
            layout_id = name.lower().replace(" ", "_")

            st.success(f"✅ 布局 `{name}` 校验通过！")
            st.caption(f"节点: {len(data['nodes'])} | 边: {len(data['edges'])} | 车位: {len(spots)}")

            # 预览图
            fig = draw_parking_layout(net, spots, height=280)
            st.plotly_chart(fig, use_container_width=True)

            if st.button("✅ 添加到布局列表", type="primary"):
                st.session_state.custom_layouts[layout_id] = {
                    "name": name, "data": data,
                    "net": net, "spots": spots
                }
                LAYOUT_BUILDERS[layout_id] = lambda ns=len(spots), tr=0.0, d=data: _build_custom(d)
                LAYOUTS[layout_id] = name
                ok, err = persist_custom_layouts()
                if ok:
                    st.success(f"✅ `{name}` 已添加并保存！在仿真设置中可选")
                else:
                    st.warning(f"⚠️ 布局已在本会话生效，但云端保存失败：{err}"
                               f"（重新登录/重启后可能丢失）")
                # 清除 uploader
                st.rerun()
        except json.JSONDecodeError:
            st.error("不是有效的 JSON 文件")
        except Exception as e:
            st.error(f"校验失败: {e}")

    # 已导入的布局列表
    if st.session_state.custom_layouts:
        st.divider()
        st.caption("**已导入的布局（管理）：**")
        for lid, linfo in st.session_state.custom_layouts.items():
            c1, c2 = st.columns([4, 1])
            c1.write(f"📐 **{linfo['name']}** ({len(linfo['spots'])}车位)")
            confirm_key = f"confirm_del_{lid}"
            if not st.session_state.get(confirm_key):
                if c2.button("🗑 删除", key=f"del_layout_{lid}",
                             help=f"删除布局「{linfo['name']}」", type="primary"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                with c2:
                    st.warning(f"确认删除「{linfo['name']}」？")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("✅ 确认", key=f"del_ok_{lid}", type="primary"):
                        st.session_state.custom_layouts.pop(lid, None)
                        LAYOUT_BUILDERS.pop(lid, None)
                        LAYOUTS.pop(lid, None)
                        st.session_state.pop(confirm_key, None)
                        ok, err = persist_custom_layouts()
                        if ok:
                            st.success(f"已删除布局「{linfo['name']}」")
                        else:
                            st.warning(f"⚠️ 已在本会话删除，但云端同步失败：{err}")
                        st.rerun()
                    if cc2.button("取消", key=f"del_cancel_{lid}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()

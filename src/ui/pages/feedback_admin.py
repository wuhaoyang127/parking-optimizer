"""反馈页：管理员全部反馈（筛选/分页/编辑显示时间/回复/删除/导出）。"""
from ui.common import *
from ui.pages.feedback_helpers import (sort_feedbacks, _feedback_display_time,
                                       _feedback_to_csv)


def _render_admin_feedbacks(reverse=False):
    """管理员查看全部反馈、筛选、标记状态、回复、删除、导出"""
    items = sort_feedbacks(auth_list_feedbacks(st.session_state.token), reverse=reverse)
    if not items:
        st.caption("暂无反馈")
        return

    # 筛选 + 导出
    c_f1, c_f2, c_f3 = st.columns([1, 1, 1.4])
    with c_f1:
        status_filter = st.selectbox("状态筛选", ["全部", "待处理", "已处理"], key="fb_status_filter")
    with c_f2:
        cat_filter = st.selectbox("类型筛选", ["全部", "通用", "仿真"], key="fb_cat_filter")
    with c_f3:
        st.download_button("📥 导出反馈 CSV", _feedback_to_csv(items, reverse=reverse),
                           "feedback.csv", "text/csv", use_container_width=True)

    status_map = {"待处理": "pending", "已处理": "resolved"}
    cat_map = {"通用": "general", "仿真": "simulation"}
    filtered = [f for f in items
                if (status_filter == "全部" or f.get("status") == status_map[status_filter])
                and (cat_filter == "全部" or f.get("category") == cat_map[cat_filter])]

    if not filtered:
        st.caption("无符合条件的反馈")
        return

    # 分页（每页 10 条）
    PAGE_SIZE = 10
    total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    if "fb_page" not in st.session_state:
        st.session_state.fb_page = 0
    if st.session_state.fb_page >= total_pages:
        st.session_state.fb_page = 0
    start = st.session_state.fb_page * PAGE_SIZE
    page_items = filtered[start:start + PAGE_SIZE]

    # 分页控件
    c_pg1, c_pg2, c_pg3 = st.columns([1, 2, 1])
    with c_pg1:
        if st.button("← 上一页", disabled=st.session_state.fb_page == 0, key="fb_prev"):
            st.session_state.fb_page -= 1
            st.rerun()
    with c_pg2:
        st.caption(f"第 {st.session_state.fb_page + 1} / {total_pages} 页，共 {len(filtered)} 条")
    with c_pg3:
        if st.button("下一页 →", disabled=st.session_state.fb_page >= total_pages - 1, key="fb_next"):
            st.session_state.fb_page += 1
            st.rerun()

    for f in page_items:
        fid = str(f.get("id", ""))
        cat = "仿真" if f.get("category") == "simulation" else "通用"
        status = f.get("status", "pending")
        st.markdown(f"**{f.get('title', '')}**  `[{cat}]` — {f.get('username', '')}({f.get('role', '')})")
        disp_time = _feedback_display_time(f)
        status_label = "已处理" if status == "resolved" else "待处理"
        time_txt = f"时间：{disp_time} | 状态：{status_label}"
        c_time, c_edit = st.columns([12, 1])
        with c_time:
            st.caption(time_txt)
        with c_edit:
            open_key = f"fb_dt_open_{fid}"
            if st.button("✎", key=f"fb_dt_btn_{fid}"):
                st.session_state[open_key] = not st.session_state.get(open_key, False)
                st.rerun()
        if f.get("related_run"):
            with st.expander("关联仿真信息"):
                st.code(f.get("related_run"))
        st.write(f.get("content", ""))
        if f.get("reply"):
            st.info(f"💬 已回复：{f['reply']}")

        if st.session_state.get(open_key):
            new_dt = st.text_input(
                "显示时间", value=f.get("display_time") or "",
                key=f"fb_dt_{fid}",
                placeholder="例：2026-08-27 15:30",
                label_visibility="collapsed",
            )
            cb1, cb3 = st.columns([1, 2])
            with cb1:
                if st.button("保存", key=f"fb_dt_save_{fid}"):
                    res = auth_update_feedback_display_time(
                        st.session_state.token, fid, new_dt.strip())
                    if isinstance(res, dict) and res.get("success"):
                        st.session_state[open_key] = False
                        st.success("✅ 已保存")
                    else:
                        st.error((res or {}).get("error", "保存失败"))
                    st.rerun()
            with cb3:
                if st.button("取消", key=f"fb_dt_cancel_{fid}"):
                    st.session_state[open_key] = False
                    st.rerun()

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if status == "pending":
                if st.button("标记已处理", key=f"fb_done_{fid}"):
                    auth_update_feedback_status(st.session_state.token, fid, "resolved")
                    st.rerun()
            else:
                if st.button("标记未处理", key=f"fb_undo_{fid}"):
                    auth_update_feedback_status(st.session_state.token, fid, "pending")
                    st.rerun()
        with c2:
            if st.button("🗑 删除", key=f"fb_del_{fid}"):
                auth_delete_feedback(st.session_state.token, fid)
                st.rerun()
        with c3:
            reply = st.text_area("回复", key=f"fb_reply_{fid}", placeholder="输入回复...")
            if st.button("提交回复", key=f"fb_reply_btn_{fid}"):
                if reply.strip():
                    auth_reply_feedback(st.session_state.token, fid, reply.strip())
                    st.rerun()
        st.divider()

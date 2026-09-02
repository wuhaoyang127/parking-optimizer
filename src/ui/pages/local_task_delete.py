"""本地计算：删除任务（叫停）按钮与二次确认。"""
from ui.common import *
from ui.pages.worker_kit import _resolve_delete_task_id


def _delete_local_task_with_confirm(role):
    """删除本地计算任务（下发错了叫停用），带二次确认。

    优先删本会话下发的 task_id；刷新/重开浏览器后 session 丢失 task_id 时，
    自动查询该用户最近一条任务（任意状态）来删，按钮不再因刷新而失效。
    """
    can_delete = bool(role.get("can_delete_local_task"))
    token = st.session_state.get("token")
    if not token:
        st.info("未登录，无法删除本地计算任务")
        return
    if not can_delete:
        st.button("🗑 删除该任务", use_container_width=True, disabled=True,
                  help="当前角色无权删除本地计算任务")
        return
    task_id = st.session_state.get("local_task_id")
    task_status = None
    if not task_id:
        res = auth_get_latest_compute_task_any(token)
        if isinstance(res, dict) and not res.get("success"):
            st.error(f"❌ 查询最近任务失败：{(res or {}).get('error', '未知错误')}")
            return
        task_id, task_status, task_source = _resolve_delete_task_id(None, res)
    else:
        task_source = "本会话任务"
    if not task_id:
        st.button("🗑 删除该任务", use_container_width=True, disabled=True,
                  help="暂无本地计算任务可删除：下发任务后（或刷新页面后）这里即可叫停")
        return
    status_cn = {"pending": "排队中", "running": "计算中",
                 "done": "已完成", "failed": "失败"}.get(task_status, task_status or "未知")
    confirm_key = f"confirm_delete_task_{task_id}"
    if st.session_state.get(confirm_key):
        st.warning(f"将删除{task_source}：`{str(task_id)[:8]}…`（状态：{status_cn}）。\n\n"
                   "若本机 worker 正在计算，回传时会自动丢弃结果。")
        c_yes, c_no = st.columns(2)
        with c_yes:
            if st.button("⚠️ 确认删除", use_container_width=True):
                res = auth_delete_compute_task(token, task_id)
                if isinstance(res, dict) and res.get("success"):
                    st.session_state.pop("local_task_id", None)
                    st.session_state.pop("local_task_notice", None)
                    st.session_state.pop(confirm_key, None)
                    st.success("🗑 任务已删除。若本机 worker 正在计算，回传时会自动丢弃结果。")
                    st.rerun()
                else:
                    st.error(f"❌ 删除失败：{(res or {}).get('error', '未知错误')}")
        with c_no:
            if st.button("取消", use_container_width=True):
                st.session_state.pop(confirm_key, None)
                st.rerun()
    else:
        if st.button("🗑 删除该任务", use_container_width=True,
                     help="下发错了想叫停：优先删本会话任务；刷新丢失任务 ID 后自动定位最近一条任务删除"
                          "（排队/计算中/已完成均可删，worker 若正在计算回传时自动丢弃结果）"):
            st.session_state[confirm_key] = True
            st.rerun()

"""反馈页：排序/时间解析/CSV 工具 + 我的反馈。"""
from datetime import datetime

from ui.common import *


def _feedback_display_time(f: dict) -> str:
    """反馈显示时间：管理员可覆盖 display_time，未覆盖时用原始 created_at。"""
    return f.get("display_time") or f.get("created_at", "")


def _parse_feedback_time(value):
    """把反馈时间解析为无时区的墙上时间；无法解析返回 None。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _feedback_sort_key(f: dict):
    """排序键：按显示时间升序（早→晚）；时间无法解析的排在有时间的后面。"""
    disp = _feedback_display_time(f)
    disp_dt = _parse_feedback_time(disp)
    if disp_dt is not None:
        return (0, disp_dt, str(disp))
    created_dt = _parse_feedback_time(f.get("created_at", ""))
    if created_dt is not None:
        return (1, created_dt, str(disp))
    return (2, None, str(disp))


def sort_feedbacks(items, reverse=False):
    """反馈列表按显示时间排序（display_time 优先，回退 created_at）；reverse=True 为倒序（晚→早）。"""
    return sorted(items or [], key=_feedback_sort_key, reverse=reverse)


def _render_my_feedbacks(reverse=False):
    """展示当前用户自己提交的反馈及管理员回复"""
    items = sort_feedbacks(auth_list_my_feedbacks(st.session_state.token), reverse=reverse)
    if not items:
        st.caption("暂无反馈记录")
        return
    for f in items:
        cat = "仿真" if f.get("category") == "simulation" else "通用"
        status = f.get("status", "pending")
        icon = "✅" if status == "resolved" else "⏳"
        st.markdown(f"**{f.get('title', '')}**  `[{cat}]` {icon} `{status}`")
        st.caption(f"提交时间：{_feedback_display_time(f)}")
        st.write(f.get("content", ""))
        if f.get("reply"):
            st.info(f"💬 管理员回复：{f['reply']}")
        st.divider()


def _feedback_to_csv(items, reverse=False):
    """把反馈列表转为 UTF-8 BOM 的 CSV 字节（Excel 可直接打开中文）"""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["标题", "类型", "提交人", "角色", "状态", "内容", "回复", "时间"])
    for f in sort_feedbacks(items, reverse=reverse):
        w.writerow([f.get("title", ""), f.get("category", ""), f.get("username", ""),
                    f.get("role", ""), f.get("status", ""), f.get("content", ""),
                    f.get("reply", ""), _feedback_display_time(f)])
    return buf.getvalue().encode("utf-8-sig")

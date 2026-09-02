"""auth 包：用户反馈 RPC。"""
from auth._base import _rpc


def _normalize_list(res) -> list:
    """把 RPC 返回值归一化为 list（处理 _rpc 对单元素 list 的误判）。"""
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        if res.get("success") is False:
            return []
        return [res]
    return []


def submit_feedback(token: str, category: str, title: str, content: str,
                    related_run: str = None) -> dict:
    return _rpc("submit_feedback", {"p_token": token, "p_category": category,
                                    "p_title": title, "p_content": content,
                                    "p_related_run": related_run})


def list_my_feedbacks(token: str) -> list:
    return _normalize_list(_rpc("list_my_feedbacks", {"p_token": token}))


def list_feedbacks(token: str) -> list:
    return _normalize_list(_rpc("list_feedbacks", {"p_token": token}))


def update_feedback_status(token: str, feedback_id: str, status: str) -> dict:
    return _rpc("update_feedback_status", {"p_token": token, "p_id": feedback_id,
                                           "p_status": status})


def reply_feedback(token: str, feedback_id: str, reply: str) -> dict:
    return _rpc("reply_feedback", {"p_token": token, "p_id": feedback_id,
                                   "p_reply": reply})


def delete_feedback(token: str, feedback_id: str) -> dict:
    return _rpc("delete_feedback", {"p_token": token, "p_id": feedback_id})


def update_feedback_display_time(token: str, feedback_id: str, display_time: str) -> dict:
    """管理员修改反馈的显示时间（display_time 为空表示恢复原始时间）。"""
    return _rpc("update_feedback_display_time", {
        "p_token": token, "p_id": feedback_id, "p_display_time": display_time})

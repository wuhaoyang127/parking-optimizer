"""auth 包：本地计算任务队列 RPC。"""
from auth._base import _rpc, _rpc_with_retry


def create_compute_task(token: str, payload: dict) -> dict:
    """云端 UI 下发本地计算任务，返回 {success, task_id}。"""
    return _rpc("create_compute_task", {
        "p_token": token, "p_payload": payload or {}})


def claim_compute_task(token: str) -> dict:
    """本机 worker 领取该用户最早的 pending 任务，返回 {success, task}。"""
    return _rpc("claim_compute_task", {"p_token": token})


def complete_compute_task(token: str, task_id: str, status: str,
                          result: dict = None, error: str = None) -> dict:
    """本机 worker 回写任务结果（status: done / failed）。"""
    return _rpc("complete_compute_task", {
        "p_token": token, "p_task_id": task_id, "p_status": status,
        "p_result": result if result is not None else {},
        "p_error": error})


def get_compute_task(token: str, task_id: str) -> dict:
    """云端 UI 查询任务状态，返回 {success, status, result, error}。"""
    return _rpc_with_retry("get_compute_task", {
        "p_token": token, "p_task_id": task_id})


def get_latest_compute_task(token: str) -> dict:
    """云端 UI 载入该用户最近一次已完成的本地计算任务。

    返回 {success, task}，task 含 id/status/payload/result/error/时间戳；
    无已完成任务时 task 为 null。
    """
    return _rpc_with_retry("get_latest_compute_task", {"p_token": token})


def requeue_compute_task(token: str, task_id: str) -> dict:
    """把卡在 running 的任务重新置为 pending（worker 被关/崩溃后恢复用）。"""
    return _rpc("requeue_compute_task", {
        "p_token": token, "p_task_id": task_id})


def delete_compute_task(token: str, task_id: str) -> dict:
    """删除本地计算任务（下发错了叫停用；任意状态均可删）。"""
    return _rpc("delete_compute_task", {
        "p_token": token, "p_task_id": task_id})


def get_latest_compute_task_any(token: str) -> dict:
    """查询该用户最近一条本地计算任务（任意状态），供「删除该任务」按钮
    在浏览器 session 丢失 task_id（刷新/重开）后自动定位要删的任务。

    返回 {success, task}，task 含 id/status/error/时间戳；无任务时 task 为 null。
    """
    return _rpc_with_retry("get_latest_compute_task_any", {"p_token": token})

"""auth 包：算法发布到车主端 RPC（发布快照 / 发布历史 / 实验列表）。"""
from auth._base import _rpc, _rpc_with_retry


def publish_algorithm(token: str, algo_name: str, params: dict,
                      note: str = None) -> dict:
    """发布一个算法快照到车主端（仅管理员，SQL 层二次校验）。"""
    return _rpc("publish_algorithm", {
        "p_token": token, "p_algo_name": algo_name,
        "p_params": params or {}, "p_note": note})


def list_algorithm_releases(token: str, limit: int = 50) -> list:
    """查询发布历史（仅管理员；无权限/未登录返回空列表）。"""
    res = _rpc_with_retry("list_algorithm_releases",
                          {"p_token": token, "p_limit": int(limit)})
    if isinstance(res, list):
        return res
    return []


def list_experiments(token: str, limit: int = 20) -> list:
    """查询实验列表（仅管理员；无权限/未登录返回空列表）。"""
    res = _rpc_with_retry("list_experiments",
                          {"p_token": token, "p_limit": int(limit)})
    if isinstance(res, list):
        return res
    return []

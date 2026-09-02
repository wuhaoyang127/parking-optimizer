"""auth 包：操作审计 + 仿真运行记录 RPC。"""
from auth._base import _rpc


def log_action(token: str, action: str, detail: dict = None) -> dict:
    """写入操作审计日志（audit_log 表，由 migrations/05 创建）。

    供应用层记录仿真运行、数据导入导出等非认证类事件；
    登录/角色变更/反馈处理等关键操作已在 SQL RPC 内自动审计。
    """
    return _rpc("log_action", {
        "p_token": token, "p_action": action, "p_detail": detail or {}})


def save_sim_run(token: str, strategy: str, params: dict, env: dict,
                 metrics, layout_key: str = None, demand_source: str = None) -> dict:
    """持久化一次仿真运行结果（metrics 可为 dict 或 list）。"""
    return _rpc("save_sim_run", {
        "p_token": token, "p_strategy": strategy,
        "p_params": params or {}, "p_env": env or {},
        "p_metrics": metrics if metrics is not None else {},
        "p_layout_key": layout_key, "p_demand_source": demand_source})


def list_sim_runs(token: str, all_users: bool = False, limit: int = 200) -> list:
    """查询仿真运行记录：本人记录；管理员 all_users=True 时查全部。"""
    res = _rpc("list_sim_runs", {
        "p_token": token, "p_all": bool(all_users), "p_limit": int(limit)})
    if isinstance(res, list):
        return res
    return []


def delete_sim_run(token: str, run_id: str) -> dict:
    """删除运行记录（管理员可删任意；本人只能删自己的）。"""
    return _rpc("delete_sim_run", {"p_token": token, "p_id": run_id})

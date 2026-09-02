"""本地计算：检查/下发任务与本地计算模式下载区渲染。"""
from ui.common import *
from ui.pages.worker_kit import _worker_bat, _worker_package_data_url
from ui.pages.local_task_actions import (_apply_local_result, _build_settings_ctx,
                                        _load_latest_local_task)
from ui.pages.local_task_delete import _delete_local_task_with_confirm


def _check_local_task_once(ctx_kwargs):
    """按本会话任务 ID 查询状态；done 后自动载入结果。"""
    token = st.session_state.get("token")
    task_id = st.session_state.get("local_task_id")
    if not token or not task_id:
        st.info("浏览器里没有本会话的任务 ID（可能刷新过页面）。\n\n"
                "若刚下发过任务，本机 worker 会自动领取计算，完成后点「📂 载入最近一次结果」找回；\n\n"
                "要叫停，点「🗑 删除该任务」。")
        return
    stt = auth_get_compute_task(token, task_id)
    if isinstance(stt, dict) and stt.get("success"):
        s = stt.get("status")
        if s == "done":
            st.success("✅ 本机计算完成，正在载入结果…")
            ctx = _build_settings_ctx(**ctx_kwargs)
            _apply_local_result(stt.get("result") or {}, ctx)
        elif s == "failed":
            st.error(f"❌ 本机计算失败：{stt.get('error')}")
        elif s == "running":
            st.warning("⚙️ 任务仍在计算中。若本机 worker 已关闭或崩溃，可把任务重新排队，"
                       "重启 worker 后继续计算。")
            if st.button("♻️ 重新排队该任务（worker 已关闭时用）"):
                rq = auth_requeue_compute_task(token, task_id)
                if isinstance(rq, dict) and rq.get("success"):
                    st.success("✅ 已重新排队。请启动本机 worker（双击 start_local_worker.bat），"
                               "稍后再点「🔄 检查本地计算结果」。")
                else:
                    st.error(f"❌ 重新排队失败：{(rq or {}).get('error', '未知错误')}")
        else:
            st.info(f"任务状态：{s}。请确认本机 `py local_worker.py` 正在运行。")
    else:
        st.info("暂无任务状态。请先运行 `py local_worker.py`，再下发任务。")


def _submit_local_task_and_wait(layout, n_spots, tandem_ratio, strategy_name, strat_params,
                                env_params, wait_policy, seed, n_runs, random_reps,
                                base_vehicles, demand_source_used, n_vehicles, ctx_kwargs):
    """下发本地计算任务并轮询状态（最多 120 秒），完成后自动载入结果。"""
    token = st.session_state.get("token")
    if not token:
        st.error("未登录，无法下发本地计算任务")
        st.stop()
    if layout in BUILTIN_LAYOUT_KEYS:
        layout_payload = {"source": "builtin", "builtin_key": layout,
                          "n_spots": int(n_spots), "tandem_ratio": float(tandem_ratio)}
    else:
        linfo = (st.session_state.get("custom_layouts") or {}).get(layout) or {}
        layout_payload = {"source": "custom", "custom_data": linfo.get("data")}
    if base_vehicles is not None:
        demand_payload = {"source": demand_source_used,
                          "json_str": export_demand_json(base_vehicles, source=demand_source_used)}
    else:
        demand_payload = {"source": "generated", "generator": {
            "total_vehicles": int(n_vehicles),
            "sim_duration": env_params["sim_duration"],
            "duration_min": env_params["duration_min"],
            "duration_max": env_params["duration_max"],
            "peak_ratio": env_params["peak_ratio"],
            "error_ratio": env_params["error_ratio"]}}
    payload = {
        "layout": layout_payload,
        "demand": demand_payload,
        "strategy": {"name": strategy_name, "params": strat_params},
        "engine": {"wait_policy": wait_policy,
                   "car_speed": env_params["car_speed"],
                   "max_wait_time": env_params["max_wait_time"],
                   "seed": int(seed), "n_runs": int(n_runs),
                   "random_reps": int(random_reps),
                   "budget": float(STRATEGY_TIME_BUDGET)},
    }
    res = auth_create_compute_task(token, _json_safe(payload))
    if not (isinstance(res, dict) and res.get("success")):
        st.error(f"❌ 下发本地计算任务失败：{(res or {}).get('error', '未知错误')}\n\n"
                 "请确认：① Supabase 已执行 migrations/07_compute_tasks.sql；"
                 "② 本机 worker 正在运行（项目根目录双击 `start_local_worker.bat`，"
                 "或命令行 `py local_worker.py`）。")
        st.stop()
    task_id = res["task_id"]
    st.session_state.local_task_id = task_id
    status_box = st.empty()
    for i in range(60):
        time.sleep(2)
        stt = auth_get_compute_task(token, task_id)
        if not (isinstance(stt, dict) and stt.get("success")):
            status_box.info(f"⏳ 任务已下发（{str(task_id)[:8]}…），等待本机 worker 领取…")
            continue
        s = stt.get("status")
        if s == "pending":
            status_box.info(f"⏳ 任务排队中，等待本机 worker 领取（已等 {(i + 1) * 2}s）…")
        elif s == "running":
            status_box.info(f"⚙️ 本机 worker 正在计算（已等 {(i + 1) * 2}s）…")
        elif s == "done":
            status_box.success("✅ 本机计算完成，正在载入结果…")
            ctx = _build_settings_ctx(**ctx_kwargs)
            _apply_local_result(stt.get("result") or {}, ctx)
            return
        elif s == "failed":
            status_box.error(f"❌ 本机计算失败：{stt.get('error')}")
            st.stop()
    st.session_state.local_task_notice = (
        "⏳ 已等待 120 秒，任务仍在计算中。稍后点上方「🔄 检查本地计算结果」查看；"
        "若本机 worker 已关闭，请先双击 `start_local_worker.bat` 启动，"
        "再用「♻️ 重新排队该任务」恢复。\n\n"
        "**下发错了想叫停？** 刷新页面（F5）回到本页后，点「🗑 删除该任务」即可删除；"
        "worker 若正在计算，回传时会自动丢弃结果。")
    status_box.warning(st.session_state.local_task_notice)
    st.stop()


def _render_local_compute_section(ctx_kwargs):
    """本地计算模式：下载脚本/操作员包 + 检查/载入/删除按钮。"""
    st.info("💻 **本地计算模式**：云端界面 + 本机 CPU。\n\n"
            "**本机就是项目电脑（管理员）**：下载「📥 一键启动脚本」放到项目根目录双击运行；\n\n"
            "**操作员/同事自己的电脑**：直接下载「📦 操作员本地计算包（zip）」→ 解压到任意文件夹 → "
            "双击 `start_local_worker.bat`（首次自动装精简依赖，输入自己的账号密码）；\n\n"
            "然后点「▶️ 下发本地计算任务」，本机算完后结果自动载入。"
            "**下发错了？** 刷新页面后点「🗑 删除该任务」即可叫停。")
    c_dl1, c_dl2, c_dl3 = st.columns(3)
    with c_dl1:
        st.download_button(
            "📥 下载 worker 一键启动脚本",
            data=_worker_bat("run"),
            file_name="start_local_worker.bat",
            mime="application/octet-stream",
            use_container_width=True,
            help="保存到项目根目录（和 local_worker.py 同一个文件夹）后双击，即启动本机 worker")
    with c_dl2:
        st.download_button(
            "📥 下载『开机自启』安装脚本（装一次，以后免手动）",
            data=_worker_bat("install_autostart"),
            file_name="install_local_worker_autostart.bat",
            mime="application/octet-stream",
            use_container_width=True,
            help="保存到项目根目录双击一次：注册 Windows 登录自启，以后每次开机自动运行 worker，无需再手动打开")
    with c_dl3:
        try:
            st.link_button(
                "📦 下载操作员本地计算包（zip）",
                url=_worker_package_data_url(),
                use_container_width=True,
                help="给其他操作员/同事的电脑用：解压后双击 start_local_worker.bat，"
                     "首次运行自动装精简依赖并输入自己的账号密码，之后即可本地计算")
        except Exception as exc:
            st.button("📦 操作员包（暂不可用）", use_container_width=True,
                      disabled=True, help=f"生成失败：{exc}")
    c_refresh, c_load, c_delete = st.columns(3)
    with c_refresh:
        if st.button("🔄 检查本地计算结果", use_container_width=True,
                     help="按本会话下发的任务 ID 查询状态（任务跑完自动载入）"):
            _check_local_task_once(ctx_kwargs)
    with c_load:
        if st.button("📂 载入最近一次结果", use_container_width=True,
                     help="从 Supabase 拉取该用户最近一次已完成的本地计算任务并载入；"
                          "刷新页面、重开浏览器或换电脑后也能找回结果"):
            _load_latest_local_task()
    with c_delete:
        _delete_local_task_with_confirm()
    if st.session_state.get("local_task_id"):
        st.caption(f"最近任务：{st.session_state.local_task_id}")
    else:
        st.caption("浏览器里没有本会话的任务 ID？点「📂 载入最近一次结果」找回已完成结果；"
                   "点「🗑 删除该任务」叫停最近一次任务（刷新后也能删）。")

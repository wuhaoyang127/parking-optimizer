"""仿真设置页：MOSA 场景权重自动绑定提示。"""
from ui.common import *


def _render_mosa_hint(strategy_name, import_mode, imported_vehicles, real_layout_mode,
                      n_spots, tandem_ratio, n_vehicles, env_params, layout):
    """MOSA 场景权重自动绑定提示。"""
    if strategy_name != "mosa":
        return
    eff_n_vehicles = len(imported_vehicles) if import_mode and imported_vehicles else n_vehicles
    avg_duration = (env_params["duration_min"] + env_params["duration_max"]) / 2
    # 真实布局下车位数由导入的 JSON 定义（车位数滑杆不生效），场景判定必须取实际车位数
    if real_layout_mode:
        try:
            _, hint_spots = LAYOUT_BUILDERS[layout](n_spots, tandem_ratio)
            hint_n_spots = len(hint_spots)
        except Exception:
            hint_n_spots = n_spots
    else:
        hint_n_spots = n_spots
    # 有导入需求序列时按真实车辆精确判定（与运行时 _resolve_scene 同规则）；否则用滑杆参数预估
    if import_mode and imported_vehicles:
        scene = resolve_mosa_scene(hint_n_spots, imported_vehicles)
    else:
        scene = estimate_mosa_scene(hint_n_spots, eff_n_vehicles,
                                    env_params["sim_duration"], avg_duration)
    weights_txt = {"peak": "0.6 / 0.2 / 0.2",
                   "normal": "0.2 / 0.6 / 0.2",
                   "saturated": "0.2 / 0.2 / 0.6"}[scene]
    src_txt = "导入文件车辆数" if import_mode and imported_vehicles else "车辆数"
    st.info(f"🔒 MOSA 场景权重**自动绑定**：车位数 {hint_n_spots}、{src_txt} {eff_n_vehicles}、"
            f"平均停车时长约 {avg_duration / 60:.0f} 分钟 → 判定为"
            f"「{MOSA_SCENE_LABELS[scene]}」，权重（时间/距离/利用率）＝ {weights_txt}。"
            f"该参数不可手动调节（已变灰）。")

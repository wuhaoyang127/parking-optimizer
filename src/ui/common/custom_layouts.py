"""自定义布局持久化：Supabase 偏好 + 本地备份 + 全局镜像同步。"""
from ui.common._imports import *
from ui.common.constants import LOCAL_LAYOUT_BACKUP_PATH
from ui.common.demand_save import is_local_desktop

# 自定义布局持久化（Supabase 偏好，用户级）：布局真相源为 session_state.custom_layouts，
# 全局 LAYOUT_BUILDERS/LAYOUTS 仅作为渲染时的镜像，避免"进程残留但删不掉"。
CUSTOM_LAYOUTS_PREF_KEY = "custom_layouts_v1"


def _sync_custom_layouts_to_globals():
    """以 session_state.custom_layouts 为真相源，重建全局字典中的自定义布局项。"""
    customs = st.session_state.get("custom_layouts", {}) or {}
    for k in [k for k in LAYOUT_BUILDERS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUT_BUILDERS.pop(k, None)
    for k in [k for k in LAYOUTS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUTS.pop(k, None)
    for lid, linfo in customs.items():
        data = linfo.get("data")
        if not isinstance(data, dict):
            continue
        net, spots = linfo.get("net"), linfo.get("spots")
        if net is None or spots is None:
            try:
                net, spots = build_layout_from_json(data)
                linfo["net"], linfo["spots"] = net, spots
            except Exception:
                continue
        LAYOUT_BUILDERS[lid] = (lambda ns=len(spots), tr=0.0, d=data: build_layout_from_json(d))
        LAYOUTS[lid] = linfo.get("name", lid)


def _build_customs_from_items(items) -> dict:
    """把持久化的布局 items 列表转成 {lid: {name,data,net,spots}}，跳过无效项。"""
    customs = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name")
        data = it.get("data")
        if not name or not isinstance(data, dict):
            continue
        lid = str(name).lower().replace(" ", "_")
        try:
            net, spots = build_layout_from_json(data)
        except Exception:
            continue
        customs[lid] = {"name": name, "data": data, "net": net, "spots": spots}
    return customs


def _load_layout_items_from_local_backup():
    """读取本地备份文件（仅桌面运行时可能存在），返回 items 列表或 None。"""
    if not is_local_desktop():
        return None
    try:
        if not LOCAL_LAYOUT_BACKUP_PATH.exists():
            return None
        items = json.loads(LOCAL_LAYOUT_BACKUP_PATH.read_text(encoding="utf-8"))
        return items if isinstance(items, list) else None
    except Exception:
        return None


def _write_local_layout_backup(items):
    """本地桌面运行时，把布局列表写一份到 data/custom_layouts_backup.json。"""
    if not is_local_desktop():
        return
    try:
        LOCAL_LAYOUT_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_LAYOUT_BACKUP_PATH.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def restore_custom_layouts():
    """登录/恢复会话后，从 Supabase 恢复自定义布局列表（带重试，防网络抖动）。

    云端无记录但本地备份存在时（仅桌面运行时），回退本地备份并自愈回写云端。
    恢复失败时不写入 session_state.custom_layouts（保持缺失），由页面渲染时的
    ``ensure_custom_layouts_loaded()`` 自动重试，避免一次网络抖动就丢布局。
    """
    token = st.session_state.get("token")
    if not token:
        return
    customs = {}
    cloud_ok = False
    last_err = None
    for attempt in range(3):
        try:
            val = auth_get_pref(token, CUSTOM_LAYOUTS_PREF_KEY)
            if val:
                items = json.loads(val)
                if isinstance(items, list):
                    customs = _build_customs_from_items(items)
                    cloud_ok = True
            last_err = None
            break
        except Exception as e:
            last_err = str(e)
            time.sleep(0.6 * (attempt + 1))
    if not customs:
        local_items = _load_layout_items_from_local_backup()
        if local_items:
            customs = _build_customs_from_items(local_items)
    if customs:
        st.session_state.custom_layouts = customs
        st.session_state.pop("layout_restore_error", None)
        st.session_state.pop("layout_restore_retry_at", None)
        _sync_custom_layouts_to_globals()
        if not cloud_ok:
            # 云端没有记录但本地备份有：回写云端（自愈）
            persist_custom_layouts()
    else:
        # 云端和本地都没有可恢复的布局；若因异常导致，记下来供 UI 提示重试
        if last_err:
            st.session_state.layout_restore_error = last_err
            # 失败后 30 秒内不自动重试，避免每个控件交互都打一次后端
            st.session_state.layout_restore_retry_at = time.time() + 30
        _sync_custom_layouts_to_globals()


def ensure_custom_layouts_loaded():
    """页面渲染前确保自定义布局已加载。

    登录/会话恢复时若云端读取失败（网络抖动），本函数会在后续页面渲染时
    自动重试恢复（失败后 30 秒节流），避免用户看到空列表后被迫重新导入。
    """
    if "custom_layouts" not in st.session_state and st.session_state.get("token"):
        retry_at = st.session_state.get("layout_restore_retry_at", 0.0) or 0.0
        if time.time() >= retry_at:
            restore_custom_layouts()
    _sync_custom_layouts_to_globals()


def persist_custom_layouts():
    """把当前自定义布局列表保存到 Supabase（并写本地备份）。

    返回 (ok, error)：ok=False 时 UI 应提示用户云端保存失败的原因。
    """
    token = st.session_state.get("token")
    if not token:
        return False, "未登录，无法保存到云端"
    customs = st.session_state.get("custom_layouts", {}) or {}
    items = [{"name": v.get("name", lid), "data": v.get("data")}
             for lid, v in customs.items() if isinstance(v.get("data"), dict)]
    _write_local_layout_backup(items)
    try:
        res = auth_set_pref(token, CUSTOM_LAYOUTS_PREF_KEY,
                            json.dumps(items, ensure_ascii=False))
    except Exception as e:
        return False, f"云端保存异常：{e}"
    if isinstance(res, dict) and res.get("success"):
        return True, ""
    return False, (res or {}).get("error", "云端保存失败")


def clear_custom_layouts():
    """退出登录时清空当前会话的自定义布局（session_state 与全局镜像）。"""
    st.session_state.pop("custom_layouts", None)
    st.session_state.pop("layout_restore_error", None)
    st.session_state.pop("layout_restore_retry_at", None)
    for k in [k for k in LAYOUT_BUILDERS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUT_BUILDERS.pop(k, None)
    for k in [k for k in LAYOUTS if k not in BUILTIN_LAYOUT_KEYS]:
        LAYOUTS.pop(k, None)

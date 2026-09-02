"""页面：新算法接入（上传算法描述文件，供 AI 后台接入）。"""
from ui.common import *


def render_algo_import_page(role):
    """页面: 新算法接入 —— 上传算法描述文件，供 AI 后台接入"""
    st.subheader("🧩 新算法接入")
    can_upload = role["can_import_algo"]
    can_view_docs = role["can_configure"] or can_upload
    if not can_view_docs:
        st.info("仅管理员/操作员可查看新算法接入说明")
        return
    st.markdown("""
上传你的算法描述文件（**文字说明 / 代码示例 / 伪代码**，支持 `.md` / `.txt` / `.py` / `.json`），
文件会保存到仓库 `pending_algorithms/` 目录。

> 上传后，请回到 **Deep Code 对话** 中说一句「接入算法」，AI 会读取文件、编写代码、复检并接入，
> 最后跑仿真比较，选出最优算法。
""")
    if not can_upload:
        st.info("📤 上传/删除算法文件仅管理员可操作；操作员可查看以上接入说明。")
        return

    pending_dir = Path(__file__).resolve().parents[2] / "pending_algorithms"
    pending_dir.mkdir(parents=True, exist_ok=True)

    uploaded = st.file_uploader("📤 上传算法文件", type=["md", "txt", "py", "json"],
                                key="algo_upload")
    if uploaded is not None:
        try:
            content = uploaded.read().decode("utf-8", errors="replace")
            target = pending_dir / uploaded.name
            target.write_text(content, encoding="utf-8")
            st.success(f"✅ 已保存 `{uploaded.name}` 到 pending_algorithms/")
            st.info("请回到 Deep Code 对话，说「接入算法」，AI 会读取并接入。")
        except Exception as e:
            st.error(f"保存失败: {e}")

    files = sorted(p for p in pending_dir.glob("*") if p.is_file()) if pending_dir.exists() else []
    if files:
        st.divider()
        st.caption("**已上传的算法文件：**")
        for f in files:
            c1, c2 = st.columns([4, 1])
            c1.write(f"📄 `{f.name}`（{f.stat().st_size} 字节）")
            confirm_key = f"confirm_algo_del_{f.name}"
            if not st.session_state.get(confirm_key):
                if c2.button("🗑 删除", key=f"del_algo_{f.name}",
                             help=f"删除算法文件「{f.name}」", type="primary"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                with c2:
                    st.warning(f"确认删除「{f.name}」？")
                    cc1, cc2 = st.columns(2)
                    if cc1.button("✅ 确认", key=f"del_algo_ok_{f.name}", type="primary"):
                        try:
                            f.unlink()
                            st.session_state.pop(confirm_key, None)
                            st.success(f"已删除「{f.name}」")
                        except Exception as e:
                            st.error(f"删除失败：{e}")
                        st.rerun()
                    if cc2.button("取消", key=f"del_algo_cancel_{f.name}"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
    else:
        st.caption("暂无已上传的算法文件")

"""动态路径页：20 帧回放控件（按钮/进度/时间轴/自动轮播）。"""
from ui.common import *


def _render_frame_controls(frames, t_start, t_end):
    """渲染帧控制按钮、时间轴并处理自动轮播。"""
    N = len(frames)
    c0, c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1, 3])
    with c0:
        if st.button("⏮", help="第1帧(起点)", use_container_width=True):
            st.session_state.frame_index = 0; st.session_state.replay_time = frames[0]
            st.session_state.frame_playing = False; st.rerun()
    with c1:
        if st.button("◀", help="上一帧", use_container_width=True):
            st.session_state.frame_index = max(0, st.session_state.frame_index - 1)
            st.session_state.replay_time = frames[st.session_state.frame_index]
            st.session_state.frame_playing = False; st.rerun()
    with c2:
        ply = "⏸" if st.session_state.frame_playing else "▶"
        if st.button(ply, help="自动播放/暂停", use_container_width=True,
                     type="primary" if st.session_state.frame_playing else "secondary"):
            st.session_state.frame_playing = not st.session_state.frame_playing
            if st.session_state.frame_playing and st.session_state.frame_index >= N - 1:
                st.session_state.frame_index = 0
            st.session_state.replay_time = frames[st.session_state.frame_index]
            st.rerun()
    with c3:
        if st.button("▶▶", help="下一帧", use_container_width=True):
            st.session_state.frame_index = min(N - 1, st.session_state.frame_index + 1)
            st.session_state.replay_time = frames[st.session_state.frame_index]
            st.session_state.frame_playing = False; st.rerun()
    with c4:
        if st.button("⏭", help="第20帧(终点)", use_container_width=True):
            st.session_state.frame_index = N - 1; st.session_state.replay_time = frames[-1]
            st.session_state.frame_playing = False; st.rerun()
    with c5:
        st.progress((st.session_state.frame_index + 1) / N,
                     f"帧 {st.session_state.frame_index+1}/{N} | t={frames[st.session_state.frame_index]:.1f}s")

    # 时间轴拖拽（拖动后跳帧并暂停播放）
    # 在渲染滑杆之前同步到当前帧；不能在 widget 实例化后再修改其 key，否则会抛 StreamlitAPIException
    st.session_state.replay_timeline = float(frames[st.session_state.frame_index])
    step = max((t_end - t_start) / 200.0, 0.001)
    t_val = st.slider(
        "拖拽时间轴",
        min_value=float(t_start),
        max_value=float(t_end),
        value=float(frames[st.session_state.frame_index]),
        step=step,
        key="replay_timeline",
        format="%.1f s",
    )
    new_idx = min(range(N), key=lambda i: abs(frames[i] - t_val))
    if new_idx != st.session_state.frame_index:
        st.session_state.frame_index = new_idx
        st.session_state.replay_time = frames[new_idx]
        st.session_state.frame_playing = False

    if st.session_state.frame_index < len(frames):
        st.session_state.replay_time = frames[st.session_state.frame_index]

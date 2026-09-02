"""登录 / 注册 / 会话恢复检查。"""
from ui.common._imports import *
from ui.common.constants import LOGIN_MAX_FAILS, LOGIN_LOCK_SECONDS
from ui.common.prefs import (load_compute_mode, _load_last_params,
                             _load_run_history, _load_priority_preference)
from ui.common.custom_layouts import restore_custom_layouts


def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False; st.session_state.username = None
        st.session_state.role = None; st.session_state.token = None
        st.session_state.compute_mode = "cloud"
    if not st.session_state.logged_in and not st.session_state.token:
        restored = restore_session()
        if restored:
            st.session_state.logged_in = True
            st.session_state.username = restored["username"]
            st.session_state.role = restored["role"]
            st.session_state.token = restored["token"]
            _load_priority_preference()
            _load_run_history()
            _load_last_params()
            restore_custom_layouts()
            load_compute_mode()
    if "login_fails" not in st.session_state:
        st.session_state.login_fails = 0
        st.session_state.login_blocked_until = 0.0
    if not st.session_state.logged_in:
        st.markdown('<div style="text-align:center;padding:3rem 0 1rem"><div style="font-size:3rem">🚗</div>'
            '<h1 style="border:none;font-size:1.6rem!important">智能停车场优化系统</h1>'
            '<p style="color:#64748b">车位分配 · 纵深移位 · 仿真对比</p></div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 2.5, 1])
        with c2:
            if time.time() < st.session_state.login_blocked_until:
                wait = int(st.session_state.login_blocked_until - time.time()) + 1
                st.error(f"⏳ 尝试次数过多，请 {wait} 秒后再试")
                st.stop()
            tab_login, tab_register = st.tabs(["登录", "注册"])
            with tab_login:
                username = st.text_input("用户名", key="login_user").strip()
                password = st.text_input("密码", type="password", key="login_pw").strip()
                if st.button("登录", type="primary", use_container_width=True):
                    res = auth_login(username, password)
                    if res.get("success"):
                        st.session_state.logged_in = True
                        st.session_state.username = res["username"]
                        st.session_state.role = res["role"]
                        st.session_state.token = res["token"]
                        st.session_state.login_fails = 0
                        set_session_token(res["token"])
                        _load_priority_preference()
                        _load_run_history()
                        _load_last_params()
                        restore_custom_layouts()
                        load_compute_mode()
                        st.rerun()
                    else:
                        st.session_state.login_fails += 1
                        if st.session_state.login_fails >= LOGIN_MAX_FAILS:
                            st.session_state.login_blocked_until = time.time() + LOGIN_LOCK_SECONDS
                        st.error(res.get("error", "用户名或密码错误"))
            with tab_register:
                reg_user = st.text_input("新用户名", key="reg_user").strip()
                reg_pw = st.text_input("密码", type="password", key="reg_pw").strip()
                reg_pw2 = st.text_input("确认密码", type="password", key="reg_pw2").strip()
                if st.button("注册", use_container_width=True):
                    if not reg_user or not reg_pw: st.error("请填写用户名和密码")
                    elif reg_pw != reg_pw2: st.error("两次密码不一致")
                    else:
                        res = auth_register(reg_user, reg_pw)
                        if res.get("success"): st.success("注册成功！请切换到登录标签页")
                        else: st.error(res.get("error", "注册失败"))
        st.stop()

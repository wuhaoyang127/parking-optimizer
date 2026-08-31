-- ============================================
-- 停车场 App — 安全与合规加固
-- 在 Supabase SQL Editor 中执行此脚本（在 01~04 之后执行）
--
-- 内容：
--   1. 启用 pgcrypto（bcrypt 密码哈希）
--   2. 新增操作审计日志表 audit_log
--   3. 认证/用户管理 RPC 升级：bcrypt + search_path 加固 + 审计
--   4. 反馈管理 RPC 升级：search_path 加固 + 审计
--   5. 其余既有 RPC 统一补 SET search_path（防 search_path 劫持）
-- ============================================

-- 1. pgcrypto 扩展（提供 crypt / gen_salt）
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 2. 审计日志表
CREATE TABLE IF NOT EXISTS public.audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT,                                  -- 操作者（登录失败时为尝试的用户名）
  action TEXT NOT NULL,                           -- 动作标识：login / login_failed / logout / register / ...
  detail JSONB DEFAULT '{}'::jsonb,               -- 附加信息（角色变更、反馈 id 等）
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON public.audit_log(created_at);
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

-- ============================================
-- 3. 认证与用户管理 RPC 升级
-- 密码统一改用 bcrypt（gen_salt('bf', 10)）；
-- 兼容旧的无盐 sha256 十六进制哈希：登录校验通过后透明升级为 bcrypt。
-- ============================================

-- 3.1 注册（bcrypt）
CREATE OR REPLACE FUNCTION public.register_user(
  p_username TEXT,
  p_password TEXT
) RETURNS JSON AS $$
BEGIN
  INSERT INTO public.users (username, password_hash, role)
  VALUES (p_username, crypt(p_password, gen_salt('bf', 10)), 'viewer');

  INSERT INTO public.audit_log(username, action) VALUES (p_username, 'register');

  RETURN json_build_object('success', true, 'username', p_username);
EXCEPTION WHEN unique_violation THEN
  RETURN json_build_object('success', false, 'error', '用户名已存在');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.2 登录（bcrypt + 旧 sha256 兼容透明升级 + 审计）
CREATE OR REPLACE FUNCTION public.login_user(
  p_username TEXT,
  p_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
  v_token TEXT;
  v_ok BOOLEAN := FALSE;
BEGIN
  SELECT * INTO v_user FROM public.users WHERE username = p_username;

  IF NOT FOUND THEN
    INSERT INTO public.audit_log(username, action, detail)
    VALUES (p_username, 'login_failed', jsonb_build_object('reason', 'user_not_found'));
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  -- bcrypt 哈希以 $2 开头；旧数据为 64 位十六进制 sha256
  IF v_user.password_hash LIKE '$2%' THEN
    v_ok := v_user.password_hash = crypt(p_password, v_user.password_hash);
  ELSE
    v_ok := v_user.password_hash = encode(sha256(p_password::bytea), 'hex');
    IF v_ok THEN
      -- 旧哈希校验通过 → 透明升级为 bcrypt
      UPDATE public.users
      SET password_hash = crypt(p_password, gen_salt('bf', 10))
      WHERE id = v_user.id;
    END IF;
  END IF;

  IF NOT v_ok THEN
    INSERT INTO public.audit_log(username, action, detail)
    VALUES (p_username, 'login_failed', jsonb_build_object('reason', 'wrong_password'));
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  v_token := encode(gen_random_bytes(32), 'hex');

  UPDATE public.users
  SET session_token = v_token,
      session_expires = NOW() + INTERVAL '7 days'
  WHERE id = v_user.id;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_user.username, 'login', jsonb_build_object('role', v_user.role));

  RETURN json_build_object(
    'success', true,
    'username', v_user.username,
    'role', v_user.role,
    'token', v_token
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.3 验证 session token（逻辑不变，补 search_path 加固）
CREATE OR REPLACE FUNCTION public.validate_session(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
BEGIN
  SELECT * INTO v_user FROM public.users
  WHERE session_token = p_token
    AND session_expires > NOW();

  IF NOT FOUND THEN
    RETURN json_build_object('success', false);
  END IF;

  RETURN json_build_object(
    'success', true,
    'username', v_user.username,
    'role', v_user.role,
    'token', v_user.session_token
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.4 退出登录（审计）
CREATE OR REPLACE FUNCTION public.logout_user(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
BEGIN
  SELECT username INTO v_username FROM public.users WHERE session_token = p_token;
  UPDATE public.users SET session_token = NULL, session_expires = NULL
  WHERE session_token = p_token;

  IF v_username IS NOT NULL THEN
    INSERT INTO public.audit_log(username, action) VALUES (v_username, 'logout');
  END IF;
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.5 更新用户角色（审计旧→新）
CREATE OR REPLACE FUNCTION public.update_user_role(
  p_token TEXT,
  p_username TEXT,
  p_role TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
  v_old_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  SELECT role INTO v_old_role FROM public.users WHERE username = p_username;
  UPDATE public.users SET role = p_role
  WHERE username = p_username AND username != 'wuhaoyang127';

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'update_user_role',
          jsonb_build_object('target', p_username, 'old_role', v_old_role, 'new_role', p_role));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.6 删除用户（审计）
CREATE OR REPLACE FUNCTION public.delete_user(
  p_token TEXT,
  p_username TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  DELETE FROM public.users WHERE username = p_username AND username != 'wuhaoyang127';

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'delete_user', jsonb_build_object('target', p_username));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.7 修改密码（bcrypt + 审计）
CREATE OR REPLACE FUNCTION public.change_password(
  p_token TEXT,
  p_old_password TEXT,
  p_new_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
  v_ok BOOLEAN := FALSE;
BEGIN
  SELECT * INTO v_user FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  IF v_user.password_hash LIKE '$2%' THEN
    v_ok := v_user.password_hash = crypt(p_old_password, v_user.password_hash);
  ELSE
    v_ok := v_user.password_hash = encode(sha256(p_old_password::bytea), 'hex');
  END IF;

  IF NOT v_ok THEN
    RETURN json_build_object('success', false, 'error', '当前密码错误');
  END IF;

  UPDATE public.users
  SET password_hash = crypt(p_new_password, gen_salt('bf', 10))
  WHERE id = v_user.id;

  INSERT INTO public.audit_log(username, action) VALUES (v_user.username, 'change_password');
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.8 重置用户密码（bcrypt + 审计）
CREATE OR REPLACE FUNCTION public.reset_user_password(
  p_token TEXT,
  p_username TEXT,
  p_new_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.users
  SET password_hash = crypt(p_new_password, gen_salt('bf', 10))
  WHERE username = p_username;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'reset_user_password', jsonb_build_object('target', p_username));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.9 导出用户（审计）
CREATE OR REPLACE FUNCTION public.export_users(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  INSERT INTO public.audit_log(username, action) VALUES (v_username, 'export_users');

  RETURN (SELECT json_agg(json_build_object(
    'id', id, 'username', username, 'password_hash', password_hash,
    'role', role, 'created_at', created_at
  )) FROM public.users);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3.10 导入用户（审计）
CREATE OR REPLACE FUNCTION public.import_users(
  p_token TEXT,
  p_users_json JSON
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
  v_user JSON;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  FOR v_user IN SELECT * FROM json_array_elements(p_users_json)
  LOOP
    INSERT INTO public.users (username, password_hash, role)
    VALUES (
      v_user->>'username',
      v_user->>'password_hash',
      COALESCE(v_user->>'role', 'viewer')
    ) ON CONFLICT (username) DO UPDATE SET
      password_hash = EXCLUDED.password_hash,
      role = EXCLUDED.role;
  END LOOP;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'import_users', jsonb_build_object('count', json_array_length(p_users_json)));
  RETURN json_build_object('success', true, 'count', json_array_length(p_users_json));
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- ============================================
-- 4. 反馈管理 RPC 升级（search_path + 审计）
-- ============================================

-- 4.1 更新反馈状态（审计）
CREATE OR REPLACE FUNCTION public.update_feedback_status(
  p_token TEXT,
  p_id UUID,
  p_status TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.feedback SET status = p_status WHERE id = p_id;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'update_feedback_status',
          jsonb_build_object('feedback_id', p_id, 'status', p_status));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 4.2 回复反馈（审计）
CREATE OR REPLACE FUNCTION public.reply_feedback(
  p_token TEXT,
  p_id UUID,
  p_reply TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.feedback SET reply = p_reply, replied_at = NOW() WHERE id = p_id;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'reply_feedback', jsonb_build_object('feedback_id', p_id));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 4.3 删除反馈（审计）
CREATE OR REPLACE FUNCTION public.delete_feedback(
  p_token TEXT,
  p_id UUID
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  DELETE FROM public.feedback WHERE id = p_id;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'delete_feedback', jsonb_build_object('feedback_id', p_id));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 4.4 修改反馈显示时间（审计）
CREATE OR REPLACE FUNCTION public.update_feedback_display_time(
  p_token TEXT,
  p_id UUID,
  p_display_time TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.feedback
  SET display_time = NULLIF(p_display_time, '')
  WHERE id = p_id;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, 'update_feedback_display_time',
          jsonb_build_object('feedback_id', p_id, 'display_time', p_display_time));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- ============================================
-- 5. 其余既有 RPC 统一补 SET search_path
-- （逻辑不变，仅防 search_path 劫持）
-- ============================================

ALTER FUNCTION public.list_users(TEXT) SET search_path = public;
ALTER FUNCTION public.get_preference(TEXT, TEXT) SET search_path = public;
ALTER FUNCTION public.set_preference(TEXT, TEXT, TEXT) SET search_path = public;
ALTER FUNCTION public.submit_feedback(TEXT, TEXT, TEXT, TEXT, TEXT) SET search_path = public;
ALTER FUNCTION public.list_my_feedbacks(TEXT) SET search_path = public;
ALTER FUNCTION public.list_feedbacks(TEXT) SET search_path = public;

-- ============================================
-- 6. 通用审计入口（供应用层记录仿真运行等事件）
-- ============================================
CREATE OR REPLACE FUNCTION public.log_action(
  p_token TEXT,
  p_action TEXT,
  p_detail JSONB DEFAULT '{}'::jsonb
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_username IS NULL THEN
    v_username := 'anonymous';
  END IF;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_username, p_action, COALESCE(p_detail, '{}'::jsonb));
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

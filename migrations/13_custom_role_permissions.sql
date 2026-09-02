-- ============================================
-- 迁移 13：自定义角色权限（板块 + 功能开关）
-- 目标：
--   1. users 表加 permissions JSONB（custom 用户实际生效的 {sections, features}）
--   2. app_settings 表存全局「自定义角色模板」
--   3. login_user / validate_session / list_users 返回 permissions
--   4. 新 RPC：get_custom_sections / save_custom_sections（对象结构）
--   5. update_user_role 支持 custom（自动套用模板）
-- 在 Supabase SQL Editor 中执行本脚本（幂等，可重复执行）
-- ============================================

-- 1. users 表加 permissions 列
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT NULL;

-- 2. 全局配置表（自定义角色模板落点）
CREATE TABLE IF NOT EXISTS public.app_settings (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 登录：返回 permissions（非 custom 角色为 NULL）
CREATE OR REPLACE FUNCTION public.login_user(
  p_username TEXT,
  p_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
  v_token TEXT;
BEGIN
  SELECT * INTO v_user FROM public.users WHERE username = p_username;

  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  IF v_user.password_hash != encode(sha256(p_password::bytea), 'hex') THEN
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  v_token := encode(gen_random_bytes(32), 'hex');

  UPDATE public.users
  SET session_token = v_token,
      session_expires = NOW() + INTERVAL '7 days'
  WHERE id = v_user.id;

  RETURN json_build_object(
    'success', true,
    'username', v_user.username,
    'role', v_user.role,
    'permissions', v_user.permissions,
    'token', v_token
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 4. 校验 session：返回 permissions
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
    'permissions', v_user.permissions,
    'token', v_user.session_token
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 5. 用户列表：返回 permissions（管理员查看 custom 用户的配置）
CREATE OR REPLACE FUNCTION public.list_users(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  RETURN (SELECT json_agg(json_build_object(
    'username', username,
    'role', role,
    'permissions', permissions
  )) FROM public.users);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 6. 更新用户角色：支持 custom（套用当前模板；无模板用内置默认）
CREATE OR REPLACE FUNCTION public.update_user_role(
  p_token TEXT,
  p_username TEXT,
  p_role TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
  v_template JSONB;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  IF p_role = 'custom' THEN
    SELECT value INTO v_template FROM public.app_settings WHERE key = 'custom_sections';
    IF v_template IS NULL THEN
      v_template := jsonb_build_object(
        'sections', '["settings","layout","path","metrics","history","feedback"]'::jsonb,
        'features', '{"can_configure":true,"can_import_demand":true,"can_export_demand":true,"can_run_simulation":true,"can_local_compute":true,"can_delete_local_task":true,"can_export_results":true,"can_delete_history":true,"can_manage_users":false,"can_manage_data":false,"can_import_algo":false,"can_debug":true,"can_submit_feedback":true,"can_manage_feedback":false}'::jsonb
      );
    END IF;
    UPDATE public.users SET role = p_role, permissions = v_template
    WHERE username = p_username AND username != 'wuhaoyang127';
  ELSE
    UPDATE public.users SET role = p_role, permissions = NULL
    WHERE username = p_username AND username != 'wuhaoyang127';
  END IF;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 7. 读取自定义角色模板（管理员）：返回 {sections, features}
CREATE OR REPLACE FUNCTION public.get_custom_sections(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
  v_value JSONB;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  SELECT value INTO v_value FROM public.app_settings WHERE key = 'custom_sections';
  IF v_value IS NULL THEN
    v_value := jsonb_build_object(
      'sections', '["settings","layout","path","metrics","history","feedback"]'::jsonb,
      'features', '{"can_configure":true,"can_import_demand":true,"can_export_demand":true,"can_run_simulation":true,"can_local_compute":true,"can_delete_local_task":true,"can_export_results":true,"can_delete_history":true,"can_manage_users":false,"can_manage_data":false,"can_import_algo":false,"can_debug":true,"can_submit_feedback":true,"can_manage_feedback":false}'::jsonb
    );
  END IF;

  RETURN json_build_object('success', true, 'sections', v_value);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 8. 保存自定义角色模板（管理员）：写 app_settings 并同步给所有 custom 用户
CREATE OR REPLACE FUNCTION public.save_custom_sections(
  p_token TEXT,
  p_sections JSON
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
  v_value JSONB;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  v_value := p_sections::jsonb;

  INSERT INTO public.app_settings (key, value, updated_at)
  VALUES ('custom_sections', v_value, NOW())
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();

  UPDATE public.users SET permissions = v_value WHERE role = 'custom';

  RETURN json_build_object('success', true, 'sections', v_value);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

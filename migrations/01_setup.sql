-- ============================================
-- 停车场 App — Supabase 数据库初始化
-- 在 Supabase SQL Editor 中执行此脚本
-- ============================================

-- 1. 用户表
CREATE TABLE IF NOT EXISTS public.users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  session_token TEXT,
  session_expires TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. RLS 开放（服务器端通过 anon key 调用 RPC，不走直连查表）
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- 3. 注册用户
CREATE OR REPLACE FUNCTION public.register_user(
  p_username TEXT,
  p_password TEXT
) RETURNS JSON AS $$
BEGIN
  INSERT INTO public.users (username, password_hash, role)
  VALUES (p_username, encode(sha256(p_password::bytea), 'hex'), 'viewer');

  RETURN json_build_object('success', true, 'username', p_username);
EXCEPTION WHEN unique_violation THEN
  RETURN json_build_object('success', false, 'error', '用户名已存在');
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 4. 登录（返回 token + 用户信息）
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
    'token', v_token
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 5. 验证 session token
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
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 6. 退出登录（清除 token）
CREATE OR REPLACE FUNCTION public.logout_user(
  p_token TEXT
) RETURNS JSON AS $$
BEGIN
  UPDATE public.users SET session_token = NULL, session_expires = NULL
  WHERE session_token = p_token;
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 7. 获取所有用户（管理员用）
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
    'role', role
  )) FROM public.users);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 8. 更新用户角色（管理员用）
CREATE OR REPLACE FUNCTION public.update_user_role(
  p_token TEXT,
  p_username TEXT,
  p_role TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.users SET role = p_role WHERE username = p_username AND username != 'wuhaoyang127';
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 9. 删除用户（管理员用）
CREATE OR REPLACE FUNCTION public.delete_user(
  p_token TEXT,
  p_username TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  DELETE FROM public.users WHERE username = p_username AND username != 'wuhaoyang127';
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 10. 修改密码
CREATE OR REPLACE FUNCTION public.change_password(
  p_token TEXT,
  p_old_password TEXT,
  p_new_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
BEGIN
  SELECT * INTO v_user FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  IF v_user.password_hash != encode(sha256(p_old_password::bytea), 'hex') THEN
    RETURN json_build_object('success', false, 'error', '当前密码错误');
  END IF;

  UPDATE public.users SET password_hash = encode(sha256(p_new_password::bytea), 'hex')
  WHERE id = v_user.id;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 11. 重置用户密码（管理员用）
CREATE OR REPLACE FUNCTION public.reset_user_password(
  p_token TEXT,
  p_username TEXT,
  p_new_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.users SET password_hash = encode(sha256(p_new_password::bytea), 'hex')
  WHERE username = p_username;
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 12. 导出所有用户数据（管理员用）
CREATE OR REPLACE FUNCTION public.export_users(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  RETURN (SELECT json_agg(row_to_json(users)) FROM public.users);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 13. 导入用户数据（管理员用）
CREATE OR REPLACE FUNCTION public.import_users(
  p_token TEXT,
  p_users_json JSON
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
  v_user JSON;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
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

  RETURN json_build_object('success', true, 'count', json_array_length(p_users_json));
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- 初始化管理员账号
-- ============================================
INSERT INTO public.users (username, password_hash, role)
VALUES ('wuhaoyang127', encode(sha256('Sa1248jkl@why050212'::bytea), 'hex'), 'admin')
ON CONFLICT (username) DO NOTHING;

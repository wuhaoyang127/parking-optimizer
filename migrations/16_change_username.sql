-- ============================================
-- 迁移 16：用户名修改（外键级联 + 自改/管理员改名 RPC）
-- 前置：迁移 01~15 已执行。
-- 说明：
--   1. 给引用 users(username) 的外键补 ON UPDATE CASCADE，
--      改用户名后 user_preferences / feedback / sim_runs / compute_tasks 自动跟随。
--   2. change_username：当前登录用户改自己的用户名。
--   3. admin_rename_user：管理员改任意用户的用户名。
--   4. 管理员账号 wuhaoyang127 的用户名不可修改（系统保护）。
-- 在 Supabase SQL Editor 中执行（幂等，可重复执行）。
-- ============================================

-- 1. 给引用 users(username) 的外键补 ON UPDATE CASCADE
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT con.conrelid::regclass::text AS tbl,
           con.conname AS conname
    FROM pg_constraint con
    JOIN pg_attribute att
      ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND con.confrelid = 'public.users'::regclass
      AND att.attname = 'username'
  LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', r.tbl, r.conname);
    EXECUTE format(
      'ALTER TABLE %s ADD CONSTRAINT %I FOREIGN KEY (username) '
      'REFERENCES public.users(username) ON UPDATE CASCADE ON DELETE CASCADE',
      r.tbl, r.conname);
  END LOOP;
END $$;

-- 2. 自己改自己的用户名
CREATE OR REPLACE FUNCTION public.change_username(
  p_token TEXT,
  p_new_username TEXT
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
BEGIN
  SELECT * INTO v_user FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  p_new_username := trim(p_new_username);
  IF p_new_username IS NULL OR length(p_new_username) < 2
     OR length(p_new_username) > 32 THEN
    RETURN json_build_object('success', false, 'error', '用户名长度需在 2~32 个字符之间');
  END IF;
  IF v_user.username = 'wuhaoyang127' THEN
    RETURN json_build_object('success', false, 'error', '管理员账号用户名不可修改');
  END IF;
  IF p_new_username = v_user.username THEN
    RETURN json_build_object('success', true, 'username', p_new_username);
  END IF;

  BEGIN
    UPDATE public.users SET username = p_new_username WHERE id = v_user.id;
  EXCEPTION WHEN unique_violation THEN
    RETURN json_build_object('success', false, 'error', '该用户名已被占用');
  END;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (p_new_username, 'change_username',
          jsonb_build_object('old', v_user.username, 'new', p_new_username));

  RETURN json_build_object('success', true, 'username', p_new_username);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 3. 管理员改任意用户用户名（管理员账号除外）
CREATE OR REPLACE FUNCTION public.admin_rename_user(
  p_token TEXT,
  p_old_username TEXT,
  p_new_username TEXT
) RETURNS JSON AS $$
DECLARE
  v_admin TEXT;
  v_role TEXT;
  v_target users%ROWTYPE;
BEGIN
  SELECT username, role INTO v_admin, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_admin IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足：仅管理员可修改用户名');
  END IF;

  SELECT * INTO v_target FROM public.users WHERE username = p_old_username;
  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '目标用户不存在');
  END IF;
  IF p_old_username = 'wuhaoyang127' THEN
    RETURN json_build_object('success', false, 'error', '管理员账号用户名不可修改');
  END IF;

  p_new_username := trim(p_new_username);
  IF p_new_username IS NULL OR length(p_new_username) < 2
     OR length(p_new_username) > 32 THEN
    RETURN json_build_object('success', false, 'error', '用户名长度需在 2~32 个字符之间');
  END IF;
  IF p_new_username = p_old_username THEN
    RETURN json_build_object('success', true, 'username', p_new_username);
  END IF;

  BEGIN
    UPDATE public.users SET username = p_new_username WHERE id = v_target.id;
  EXCEPTION WHEN unique_violation THEN
    RETURN json_build_object('success', false, 'error', '该用户名已被占用');
  END;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_admin, 'admin_rename_user',
          jsonb_build_object('old', p_old_username, 'new', p_new_username));

  RETURN json_build_object('success', true, 'username', p_new_username);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

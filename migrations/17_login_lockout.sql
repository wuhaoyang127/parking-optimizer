-- ============================================
-- 迁移 17：研究端服务端登录锁死（防暴力破解）
-- 目标：
--   1. 新增 login_attempts 表记录连续失败次数与锁定窗口；
--   2. 重写 login_user：登录前查锁、失败计数、成功后清零。
-- 前端限流（3 次 / 30 秒）可被绕过，这里在服务端兜底（5 次 / 5 分钟）。
-- 在 Supabase SQL Editor 中执行本脚本（幂等，可重复执行）。
-- ============================================

-- 1. 登录失败计数表（按用户名，避免 IP 维度被多 IP 绕过）
CREATE TABLE IF NOT EXISTS public.login_attempts (
  username TEXT PRIMARY KEY,
  failed_count INTEGER NOT NULL DEFAULT 0,
  blocked_until TIMESTAMPTZ DEFAULT NULL
);

-- 2. 重写 login_user：加锁死检查 + 失败计数 + 成功后清零（保持 v13 的 permissions 返回）
CREATE OR REPLACE FUNCTION public.login_user(
  p_username TEXT,
  p_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
  v_ok BOOLEAN := FALSE;
  v_token TEXT;
  v_attempt login_attempts%ROWTYPE;
BEGIN
  -- 锁死检查：窗口内直接拒绝
  SELECT * INTO v_attempt FROM public.login_attempts WHERE username = p_username;
  IF FOUND AND v_attempt.blocked_until IS NOT NULL AND v_attempt.blocked_until > NOW() THEN
    RETURN json_build_object('success', false, 'error', '尝试次数过多，请稍后再试');
  END IF;

  SELECT * INTO v_user FROM public.users WHERE username = p_username;
  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  -- 密码双格式兼容：bcrypt / sha256（老用户成功后自动升级 bcrypt）
  IF v_user.password_hash LIKE '$2%' THEN
    v_ok := v_user.password_hash = crypt(p_password, v_user.password_hash);
  ELSE
    v_ok := v_user.password_hash = encode(sha256(p_password::bytea), 'hex');
    IF v_ok THEN
      UPDATE public.users
      SET password_hash = crypt(p_password, gen_salt('bf', 10))
      WHERE id = v_user.id;
    END IF;
  END IF;

  IF NOT v_ok THEN
    -- 记录失败；累计达到 5 次则锁定 5 分钟
    INSERT INTO public.login_attempts (username, failed_count, blocked_until)
    VALUES (p_username, 1, NULL)
    ON CONFLICT (username) DO UPDATE SET
      failed_count = public.login_attempts.failed_count + 1,
      blocked_until = CASE
        WHEN public.login_attempts.failed_count + 1 >= 5 THEN NOW() + INTERVAL '5 minutes'
        ELSE NULL
      END;
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  -- 成功：清零失败计数
  DELETE FROM public.login_attempts WHERE username = p_username;

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

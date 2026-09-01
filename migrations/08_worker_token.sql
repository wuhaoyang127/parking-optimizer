-- ============================================
-- 停车场 App — 本机 worker 独立登录态（08）
-- 解决：网页登录与 local_worker 共用单个 session_token，
--       谁后登录谁把前一个顶掉，导致「登录态失效」互相踢。
-- 方案：users 表新增 worker_token / worker_expires 两个独立列；
--       worker 用 login_worker 登录（只更新 worker token，不动网页 session）；
--       计算任务 4 个 RPC 同时接受网页 session token 或 worker token。
-- 在 Supabase SQL Editor 中执行（一次性）。
-- ============================================

-- 1. users 表增加 worker 独立登录态列
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS worker_token TEXT,
  ADD COLUMN IF NOT EXISTS worker_expires TIMESTAMPTZ;

-- 2. worker 专用登录 RPC：不影响网页 session_token
CREATE OR REPLACE FUNCTION public.login_worker(
  p_username TEXT,
  p_password TEXT
) RETURNS JSON AS $$
DECLARE
  v_user public.users%ROWTYPE;
  v_ok BOOLEAN := FALSE;
  v_token TEXT;
BEGIN
  SELECT * INTO v_user FROM public.users WHERE username = p_username;

  IF NOT FOUND THEN
    INSERT INTO public.audit_log(username, action, detail)
    VALUES (p_username, 'login_worker_failed', jsonb_build_object('reason', 'user_not_found'));
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  -- bcrypt 哈希以 $2 开头；旧数据为 64 位十六进制 sha256
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
    INSERT INTO public.audit_log(username, action, detail)
    VALUES (p_username, 'login_worker_failed', jsonb_build_object('reason', 'wrong_password'));
    RETURN json_build_object('success', false, 'error', '用户名或密码错误');
  END IF;

  v_token := encode(gen_random_bytes(32), 'hex');

  UPDATE public.users
  SET worker_token = v_token,
      worker_expires = NOW() + INTERVAL '7 days'
  WHERE id = v_user.id;

  INSERT INTO public.audit_log(username, action, detail)
  VALUES (v_user.username, 'login_worker', jsonb_build_object('role', v_user.role));

  RETURN json_build_object(
    'success', true,
    'username', v_user.username,
    'role', v_user.role,
    'token', v_token
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 3. 计算任务 4 个 RPC 改为「网页 token 或 worker token 任一有效即可」

-- 3.1 创建任务（网页 UI 用 session token）
CREATE OR REPLACE FUNCTION public.create_compute_task(
  p_token TEXT,
  p_payload JSONB
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_id UUID;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE (session_token = p_token AND session_expires > NOW())
     OR (worker_token = p_token AND worker_expires > NOW());

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  INSERT INTO public.compute_tasks (username, payload)
  VALUES (v_username, p_payload)
  RETURNING id INTO v_id;

  RETURN json_build_object('success', true, 'task_id', v_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 3.2 领取任务（本机 worker 用 worker token）
CREATE OR REPLACE FUNCTION public.claim_compute_task(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_rec RECORD;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE (session_token = p_token AND session_expires > NOW())
     OR (worker_token = p_token AND worker_expires > NOW());

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  SELECT id, payload INTO v_rec FROM public.compute_tasks
  WHERE username = v_username AND status = 'pending'
  ORDER BY created_at
  LIMIT 1;

  IF v_rec.id IS NULL THEN
    RETURN json_build_object('success', true, 'task', NULL);
  END IF;

  UPDATE public.compute_tasks
  SET status = 'running', updated_at = NOW()
  WHERE id = v_rec.id;

  RETURN json_build_object('success', true,
    'task', json_build_object('id', v_rec.id, 'payload', v_rec.payload));
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 3.3 完成任务（本机 worker 用 worker token）
CREATE OR REPLACE FUNCTION public.complete_compute_task(
  p_token TEXT,
  p_task_id UUID,
  p_status TEXT,
  p_result JSONB,
  p_error TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE (session_token = p_token AND session_expires > NOW())
     OR (worker_token = p_token AND worker_expires > NOW());

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  UPDATE public.compute_tasks
  SET status = p_status,
      result = p_result,
      error = p_error,
      updated_at = NOW()
  WHERE id = p_task_id AND username = v_username;

  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '任务不存在');
  END IF;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 3.4 查询任务状态（网页 UI 用 session token）
CREATE OR REPLACE FUNCTION public.get_compute_task(
  p_token TEXT,
  p_task_id UUID
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_rec RECORD;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE (session_token = p_token AND session_expires > NOW())
     OR (worker_token = p_token AND worker_expires > NOW());

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  SELECT status, result, error, updated_at INTO v_rec
  FROM public.compute_tasks
  WHERE id = p_task_id AND username = v_username;

  IF v_rec.status IS NULL THEN
    RETURN json_build_object('success', false, 'error', '任务不存在');
  END IF;

  RETURN json_build_object('success', true, 'status', v_rec.status,
    'result', v_rec.result, 'error', v_rec.error, 'updated_at', v_rec.updated_at);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

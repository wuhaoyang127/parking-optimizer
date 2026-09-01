-- ============================================
-- 停车场 App — 本地计算任务队列（云 UI + 本机 worker）
-- 在 Supabase SQL Editor 中执行本脚本（一次性）
-- ============================================

-- 1. 任务表
CREATE TABLE IF NOT EXISTS public.compute_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL REFERENCES public.users(username) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending / running / done / failed
  payload JSONB NOT NULL,                   -- 任务参数（布局/需求/策略/引擎/种子）
  result JSONB,                             -- 计算结果（指标/事件/车辆）
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.compute_tasks ENABLE ROW LEVEL SECURITY;

-- 2. 创建任务（云端 UI 调用）
CREATE OR REPLACE FUNCTION public.create_compute_task(
  p_token TEXT,
  p_payload JSONB
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_id UUID;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  INSERT INTO public.compute_tasks (username, payload)
  VALUES (v_username, p_payload)
  RETURNING id INTO v_id;

  RETURN json_build_object('success', true, 'task_id', v_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 3. 领取任务（本机 worker 调用）：领取该用户最早的一个 pending 任务并置为 running
CREATE OR REPLACE FUNCTION public.claim_compute_task(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_rec RECORD;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

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

-- 4. 完成任务（本机 worker 调用）：写入结果或错误
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
  WHERE session_token = p_token AND session_expires > NOW();

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

-- 5. 查询任务状态（云端 UI 轮询/刷新调用）
CREATE OR REPLACE FUNCTION public.get_compute_task(
  p_token TEXT,
  p_task_id UUID
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_rec RECORD;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

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

-- ============================================
-- 停车场 App — 本地计算任务自愈（09）
-- 解决：worker 被关闭/崩溃后，任务卡在 running，网页无法恢复。
-- ① 新增 requeue_compute_task RPC：任务 owner 可把 running 任务重新置为 pending；
-- ② claim_compute_task 领取前自动把「卡在 running 超过 15 分钟」的任务重新置为 pending。
-- 在 Supabase SQL Editor 中执行（一次性）。
-- ============================================

-- 1. 重新排队 RPC（网页「检查本地计算结果」处调用）
CREATE OR REPLACE FUNCTION public.requeue_compute_task(
  p_token TEXT,
  p_task_id UUID
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
  SET status = 'pending', updated_at = NOW()
  WHERE id = p_task_id AND username = v_username AND status = 'running';

  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '任务不存在或不在计算中');
  END IF;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 2. 领取任务前自愈：把该用户卡在 running 超过 15 分钟的任务重新置为 pending
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

  UPDATE public.compute_tasks
  SET status = 'pending', updated_at = NOW()
  WHERE username = v_username AND status = 'running'
    AND updated_at < NOW() - INTERVAL '15 minutes';

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

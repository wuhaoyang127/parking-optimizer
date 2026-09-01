-- ============================================
-- 停车场 App — 载入最近一次本地计算结果（10）
-- 解决：浏览器 session 丢失 task_id（刷新/重开/换电脑）后，
--       已完成的本地计算任务无法在网页端找回。
-- ① 新增 get_latest_compute_task RPC：返回该用户最近一条 done 任务
--    （含 payload + result，网页可完整恢复布局/参数/结果）。
-- 在 Supabase SQL Editor 中执行（一次性）。
-- ============================================

CREATE OR REPLACE FUNCTION public.get_latest_compute_task(
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

  SELECT id, status, payload, result, error, created_at, updated_at INTO v_rec
  FROM public.compute_tasks
  WHERE username = v_username AND status = 'done'
  ORDER BY updated_at DESC
  LIMIT 1;

  IF v_rec.id IS NULL THEN
    RETURN json_build_object('success', true, 'task', NULL);
  END IF;

  RETURN json_build_object('success', true, 'task', json_build_object(
    'id', v_rec.id,
    'status', v_rec.status,
    'payload', v_rec.payload,
    'result', v_rec.result,
    'error', v_rec.error,
    'created_at', v_rec.created_at,
    'updated_at', v_rec.updated_at
  ));
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

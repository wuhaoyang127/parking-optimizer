-- ============================================
-- 停车场 App — 删除本地计算任务（11）
-- 解决：任务下发错了无法叫停/删除。
-- 新增 delete_compute_task RPC：任务 owner 可删除自己任意状态的任务；
-- 若 worker 正在计算，回传时发现任务已删除则丢弃结果。
-- 在 Supabase SQL Editor 中执行（一次性）。
-- ============================================

CREATE OR REPLACE FUNCTION public.delete_compute_task(
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

  DELETE FROM public.compute_tasks
  WHERE id = p_task_id AND username = v_username;

  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '任务不存在或无权删除');
  END IF;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

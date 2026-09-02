-- ============================================
-- 停车场 App — 查询最近一条本地计算任务（任意状态）（12）
-- 解决：刷新页面后 session 丢失 task_id，删除按钮失效；
--       但任务仍 pending/running 在队列里，用户找不到删除入口叫停。
-- 新增 get_latest_compute_task_any RPC：返回该用户最近一条任务
-- （任意状态，按 created_at DESC），供「🗑 删除该任务」按钮
-- 在没有本会话 task_id 时自动定位要删的任务。
-- 在 Supabase SQL Editor 中执行（一次性）。
-- ============================================

CREATE OR REPLACE FUNCTION public.get_latest_compute_task_any(
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

  SELECT id, status, error, created_at, updated_at INTO v_rec
  FROM public.compute_tasks
  WHERE username = v_username
  ORDER BY created_at DESC
  LIMIT 1;

  IF v_rec.id IS NULL THEN
    RETURN json_build_object('success', true, 'task', NULL);
  END IF;

  RETURN json_build_object('success', true, 'task', json_build_object(
    'id', v_rec.id,
    'status', v_rec.status,
    'error', v_rec.error,
    'created_at', v_rec.created_at,
    'updated_at', v_rec.updated_at
  ));
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

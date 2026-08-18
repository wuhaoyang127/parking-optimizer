-- ============================================
-- 停车场 App — 用户反馈（意见箱 + 仿真结果反馈）
-- 在 Supabase SQL Editor 中执行此脚本
-- ============================================

-- 1. 反馈表
CREATE TABLE IF NOT EXISTS public.feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL REFERENCES public.users(username) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'viewer',
  category TEXT NOT NULL DEFAULT 'general',   -- 'general' 通用意见 / 'simulation' 仿真结果反馈
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  related_run TEXT,                            -- 关联仿真信息（JSON 文本，可空）
  status TEXT NOT NULL DEFAULT 'pending',      -- 'pending' 待处理 / 'resolved' 已处理
  reply TEXT,                                  -- 管理员回复（可空）
  created_at TIMESTAMPTZ DEFAULT NOW(),
  replied_at TIMESTAMPTZ
);

-- 2. RLS 启用（直连拒绝，通过 RPC 访问）
ALTER TABLE public.feedback ENABLE ROW LEVEL SECURITY;

-- 3. 提交反馈（所有登录用户）
CREATE OR REPLACE FUNCTION public.submit_feedback(
  p_token TEXT,
  p_category TEXT,
  p_title TEXT,
  p_content TEXT,
  p_related_run TEXT DEFAULT NULL
) RETURNS JSON AS $$
DECLARE
  v_user users%ROWTYPE;
BEGIN
  SELECT * INTO v_user FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF NOT FOUND THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  INSERT INTO public.feedback (username, role, category, title, content, related_run)
  VALUES (v_user.username, v_user.role, p_category, p_title, p_content, p_related_run);

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 4. 查看我的反馈（所有登录用户，含管理员回复）
CREATE OR REPLACE FUNCTION public.list_my_feedbacks(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  RETURN (SELECT COALESCE(json_agg(f ORDER BY f.created_at DESC), '[]'::json)
          FROM public.feedback f WHERE f.username = v_username);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 5. 查看全部反馈（仅管理员）
CREATE OR REPLACE FUNCTION public.list_feedbacks(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  RETURN (SELECT COALESCE(json_agg(f ORDER BY f.created_at DESC), '[]'::json)
          FROM public.feedback f);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 6. 更新反馈状态（仅管理员）
CREATE OR REPLACE FUNCTION public.update_feedback_status(
  p_token TEXT,
  p_id UUID,
  p_status TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.feedback SET status = p_status WHERE id = p_id;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 7. 回复反馈（仅管理员）
CREATE OR REPLACE FUNCTION public.reply_feedback(
  p_token TEXT,
  p_id UUID,
  p_reply TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.feedback SET reply = p_reply, replied_at = NOW() WHERE id = p_id;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

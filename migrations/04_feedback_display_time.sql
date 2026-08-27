-- ============================================
-- 停车场 App — 反馈「显示时间」字段（管理员可修改）
-- 在 Supabase SQL Editor 中执行此脚本
-- ============================================

-- 1. 反馈表增加显示时间字段（TEXT：自由文本显示，如 "2026-08-27 15:30"）
ALTER TABLE public.feedback ADD COLUMN IF NOT EXISTS display_time TEXT;

-- 2. 修改反馈显示时间（仅管理员）
CREATE OR REPLACE FUNCTION public.update_feedback_display_time(
  p_token TEXT,
  p_id UUID,
  p_display_time TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  UPDATE public.feedback
  SET display_time = NULLIF(p_display_time, '')
  WHERE id = p_id;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

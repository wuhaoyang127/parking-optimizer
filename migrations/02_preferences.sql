-- ============================================
-- 停车场 App — 用户偏好持久化（算法优先级等）
-- 在 Supabase SQL Editor 中执行此脚本
-- ============================================

-- 1. 用户偏好表
CREATE TABLE IF NOT EXISTS public.user_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL REFERENCES public.users(username) ON DELETE CASCADE,
  pref_key TEXT NOT NULL,
  pref_value TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (username, pref_key)
);

-- 2. RLS 启用（直连拒绝，通过 RPC 访问）
ALTER TABLE public.user_preferences ENABLE ROW LEVEL SECURITY;

-- 3. 读取偏好
CREATE OR REPLACE FUNCTION public.get_preference(
  p_token TEXT,
  p_key TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_value TEXT;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  SELECT pref_value INTO v_value FROM public.user_preferences
  WHERE username = v_username AND pref_key = p_key;

  RETURN json_build_object('success', true, 'value', v_value);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 4. 写入偏好（不存在则插入，存在则更新）
CREATE OR REPLACE FUNCTION public.set_preference(
  p_token TEXT,
  p_key TEXT,
  p_value TEXT
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();

  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  INSERT INTO public.user_preferences (username, pref_key, pref_value)
  VALUES (v_username, p_key, p_value)
  ON CONFLICT (username, pref_key) DO UPDATE
    SET pref_value = EXCLUDED.pref_value, updated_at = NOW();

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

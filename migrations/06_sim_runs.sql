-- ============================================
-- 停车场 App — 仿真运行记录（企业数据沉淀与跨会话对比）
-- 在 Supabase SQL Editor 中执行此脚本（在 01~05 之后执行）
-- ============================================

-- 1. 运行记录表
CREATE TABLE IF NOT EXISTS public.sim_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL REFERENCES public.users(username) ON DELETE CASCADE,
  strategy TEXT NOT NULL,                  -- 策略名；compare_all 表示全部对比
  params JSONB DEFAULT '{}'::jsonb,        -- 策略参数快照
  env JSONB DEFAULT '{}'::jsonb,           -- 环境参数快照（车速/等待/需求生成）
  metrics JSONB DEFAULT '{}'::jsonb,       -- 指标结果（dict）或全部对比列表（array）
  layout_key TEXT,                         -- 布局标识（内置/真实布局名）
  demand_source TEXT,                      -- generated / imported
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sim_runs_username_created ON public.sim_runs(username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sim_runs_created_at ON public.sim_runs(created_at DESC);
ALTER TABLE public.sim_runs ENABLE ROW LEVEL SECURITY;

-- 2. 保存一次运行（所有登录用户）
CREATE OR REPLACE FUNCTION public.save_sim_run(
  p_token TEXT,
  p_strategy TEXT,
  p_params JSONB DEFAULT '{}'::jsonb,
  p_env JSONB DEFAULT '{}'::jsonb,
  p_metrics JSONB DEFAULT '{}'::jsonb,
  p_layout_key TEXT DEFAULT NULL,
  p_demand_source TEXT DEFAULT NULL
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

  INSERT INTO public.sim_runs (username, strategy, params, env, metrics, layout_key, demand_source)
  VALUES (v_username, p_strategy,
          COALESCE(p_params, '{}'::jsonb), COALESCE(p_env, '{}'::jsonb),
          COALESCE(p_metrics, '{}'::jsonb), p_layout_key, p_demand_source)
  RETURNING id INTO v_id;

  RETURN json_build_object('success', true, 'id', v_id);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 3. 查询运行记录（本人；管理员可查全部）
CREATE OR REPLACE FUNCTION public.list_sim_runs(
  p_token TEXT,
  p_all BOOLEAN DEFAULT FALSE,
  p_limit INT DEFAULT 200
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  IF p_all AND v_role = 'admin' THEN
    RETURN (SELECT COALESCE(json_agg(r ORDER BY r.created_at DESC), '[]'::json)
            FROM (SELECT * FROM public.sim_runs
                  ORDER BY created_at DESC LIMIT p_limit) r);
  ELSE
    RETURN (SELECT COALESCE(json_agg(r ORDER BY r.created_at DESC), '[]'::json)
            FROM (SELECT * FROM public.sim_runs
                  WHERE username = v_username
                  ORDER BY created_at DESC LIMIT p_limit) r);
  END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- 4. 删除运行记录（管理员可删任意；本人只能删自己的）
CREATE OR REPLACE FUNCTION public.delete_sim_run(
  p_token TEXT,
  p_id UUID
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;

  IF v_role = 'admin' THEN
    DELETE FROM public.sim_runs WHERE id = p_id;
  ELSE
    DELETE FROM public.sim_runs WHERE id = p_id AND username = v_username;
  END IF;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

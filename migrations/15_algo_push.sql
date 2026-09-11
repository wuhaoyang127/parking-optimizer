-- ============================================
-- 迁移 15：算法发布到车主端（发布快照 + 实验表幂等 + 自定义权限新功能位）
-- 前置：迁移 01~14 已执行。
-- 说明：
--   1. algorithm_releases：研发端「推送到车主端」的正式出口（仅管理员可写）。
--   2. experiments / experiment_assignments / experiment_events：
--      若你已手工建好这三张表，本脚本不会覆盖（IF NOT EXISTS）；
--      若尚未创建，本脚本按标准结构补建，保证仓库可复现。
--   3. 自定义角色权限新增 can_push_algo（默认 false），并同步旧模板数据。
-- 在 Supabase SQL Editor 中执行（幂等，可重复执行）。
-- ============================================

-- 1. 算法发布快照表
CREATE TABLE IF NOT EXISTS public.algorithm_releases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  algo_name TEXT NOT NULL,
  params JSONB DEFAULT '{}'::jsonb,
  pkg_version TEXT,
  git_commit TEXT,
  note TEXT,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_algorithm_releases_created
  ON public.algorithm_releases(created_at DESC);
ALTER TABLE public.algorithm_releases ENABLE ROW LEVEL SECURITY;

-- 2. 实验配置表（研发端/车主端共享：车主端 FastAPI 用 service_role 直连读取）
CREATE TABLE IF NOT EXISTS public.experiments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  algo_default TEXT NOT NULL,
  algo_new TEXT NOT NULL,
  traffic_pct INT NOT NULL DEFAULT 0 CHECK (traffic_pct BETWEEN 0 AND 100),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','running','stopped','kept','rolled_back')),
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 实验分组表（用户首次命中后固定分组，实验期内不跳变）
CREATE TABLE IF NOT EXISTS public.experiment_assignments (
  experiment_id UUID REFERENCES public.experiments(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  bucket INT NOT NULL,
  group_name TEXT NOT NULL CHECK (group_name IN ('control','treatment')),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (experiment_id, user_id)
);

-- 4. 实验指标事件表（每次算法调用记录，供月底保留/回滚决策）
CREATE TABLE IF NOT EXISTS public.experiment_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  experiment_id UUID REFERENCES public.experiments(id) ON DELETE CASCADE,
  user_id UUID,
  algo_version TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value NUMERIC,
  payload JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_experiment_events_exp_created
  ON public.experiment_events(experiment_id, created_at DESC);

ALTER TABLE public.experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_events ENABLE ROW LEVEL SECURITY;

-- 5. RPC：发布算法（仅管理员）
CREATE OR REPLACE FUNCTION public.publish_algorithm(
  p_token TEXT,
  p_algo_name TEXT,
  p_params JSONB DEFAULT '{}'::jsonb,
  p_note TEXT DEFAULT NULL
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
  v_id UUID;
BEGIN
  SELECT username, role INTO v_username, v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '未登录');
  END IF;
  IF v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足：仅管理员可推送到车主端');
  END IF;

  INSERT INTO public.algorithm_releases (algo_name, params, note, created_by)
  VALUES (p_algo_name, COALESCE(p_params, '{}'::jsonb), p_note, v_username)
  RETURNING id INTO v_id;

  RETURN json_build_object('success', true, 'id', v_id, 'algo_name', p_algo_name);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 6. RPC：查询发布历史（仅管理员）
CREATE OR REPLACE FUNCTION public.list_algorithm_releases(
  p_token TEXT,
  p_limit INT DEFAULT 50
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  RETURN (SELECT COALESCE(json_agg(r ORDER BY r.created_at DESC), '[]'::json)
          FROM (SELECT * FROM public.algorithm_releases
                ORDER BY created_at DESC LIMIT p_limit) r);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 7. RPC：查询实验列表（仅管理员；车主端走 service_role 直连，不经过这里）
CREATE OR REPLACE FUNCTION public.list_experiments(
  p_token TEXT,
  p_limit INT DEFAULT 20
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
BEGIN
  SELECT role INTO v_role FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  RETURN (SELECT COALESCE(json_agg(r ORDER BY r.created_at DESC), '[]'::json)
          FROM (SELECT * FROM public.experiments
                ORDER BY created_at DESC LIMIT p_limit) r);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, extensions;

-- 8. 自定义角色模板补齐新功能位 can_push_algo（默认 false）
UPDATE public.app_settings
SET value = jsonb_set(value, '{features,can_push_algo}', 'false'::jsonb, true)
WHERE key = 'custom_sections' AND value ? 'features';

UPDATE public.users
SET permissions = jsonb_set(permissions, '{features,can_push_algo}', 'false'::jsonb, true)
WHERE role = 'custom' AND permissions IS NOT NULL AND permissions ? 'features';

-- 9. 覆盖 update_user_role 兜底模板（含 can_push_algo，与迁移 13 保持一致）
CREATE OR REPLACE FUNCTION public.update_user_role(
  p_token TEXT,
  p_username TEXT,
  p_role TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
  v_template JSONB;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  IF p_role = 'custom' THEN
    SELECT value INTO v_template FROM public.app_settings WHERE key = 'custom_sections';
    IF v_template IS NULL THEN
      v_template := jsonb_build_object(
        'sections', '["settings","layout","path","metrics","history","feedback"]'::jsonb,
        'features', '{"can_configure":true,"can_import_demand":true,"can_export_demand":true,"can_run_simulation":true,"can_local_compute":true,"can_delete_local_task":true,"can_export_results":true,"can_delete_history":true,"can_manage_users":false,"can_manage_data":false,"can_import_algo":false,"can_push_algo":false,"can_debug":true,"can_submit_feedback":true,"can_manage_feedback":false}'::jsonb
      );
    END IF;
    UPDATE public.users SET role = p_role, permissions = v_template
    WHERE username = p_username AND username != 'wuhaoyang127';
  ELSE
    UPDATE public.users SET role = p_role, permissions = NULL
    WHERE username = p_username AND username != 'wuhaoyang127';
  END IF;

  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 10. 覆盖 get_custom_sections 兜底模板（含 can_push_algo）
CREATE OR REPLACE FUNCTION public.get_custom_sections(
  p_token TEXT
) RETURNS JSON AS $$
DECLARE
  v_role TEXT;
  v_value JSONB;
BEGIN
  SELECT role INTO v_role FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_role IS NULL OR v_role != 'admin' THEN
    RETURN json_build_object('success', false, 'error', '权限不足');
  END IF;

  SELECT value INTO v_value FROM public.app_settings WHERE key = 'custom_sections';
  IF v_value IS NULL THEN
    v_value := jsonb_build_object(
      'sections', '["settings","layout","path","metrics","history","feedback"]'::jsonb,
      'features', '{"can_configure":true,"can_import_demand":true,"can_export_demand":true,"can_run_simulation":true,"can_local_compute":true,"can_delete_local_task":true,"can_export_results":true,"can_delete_history":true,"can_manage_users":false,"can_manage_data":false,"can_import_algo":false,"can_push_algo":false,"can_debug":true,"can_submit_feedback":true,"can_manage_feedback":false}'::jsonb
    );
  END IF;

  RETURN json_build_object('success', true, 'sections', v_value);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

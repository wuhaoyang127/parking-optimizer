-- ============================================
-- 迁移 18：布局推送改走 RPC（研究端降权，不再持有 service key）
-- 目标：
--   1. push_driver_layout / list_driver_layouts 改为 SECURITY DEFINER RPC；
--   2. 用 p_token 校验调用者（admin 或自定义角色开启 layout_push 板块）；
--   3. 研究端只需 anon key，service key 只保留在车主端服务端。
-- 在 Supabase SQL Editor 中执行本脚本（幂等，可重复执行）。
-- ============================================

-- 推送/覆盖一个布局（按 id 去重追加到 app_settings.driver_layouts）
CREATE OR REPLACE FUNCTION public.push_driver_layout(
  p_token TEXT,
  p_layout JSONB
) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_role TEXT;
  v_permissions JSONB;
  v_items JSONB;
BEGIN
  SELECT username, role, permissions INTO v_username, v_role, v_permissions
  FROM public.users WHERE session_token = p_token AND session_expires > NOW();
  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '会话无效');
  END IF;
  IF v_role <> 'admin' AND (
    v_permissions IS NULL OR NOT (v_permissions->'sections' ? 'layout_push')
  ) THEN
    RETURN json_build_object('success', false, 'error', '无布局推送权限');
  END IF;
  SELECT COALESCE(value, '[]'::jsonb) INTO v_items
  FROM public.app_settings WHERE key = 'driver_layouts';
  v_items := (SELECT COALESCE(jsonb_agg(e), '[]'::jsonb)
              FROM jsonb_array_elements(v_items) e
              WHERE e->>'id' <> (p_layout->>'id')) || jsonb_build_array(p_layout);
  INSERT INTO public.app_settings (key, value, updated_at)
  VALUES ('driver_layouts', v_items, NOW())
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
  RETURN json_build_object('success', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- 读取已推送布局列表
CREATE OR REPLACE FUNCTION public.list_driver_layouts(p_token TEXT) RETURNS JSON AS $$
DECLARE
  v_username TEXT;
  v_items JSONB;
BEGIN
  SELECT username INTO v_username FROM public.users
  WHERE session_token = p_token AND session_expires > NOW();
  IF v_username IS NULL THEN
    RETURN json_build_object('success', false, 'error', '会话无效');
  END IF;
  SELECT COALESCE(value, '[]'::jsonb) INTO v_items
  FROM public.app_settings WHERE key = 'driver_layouts';
  RETURN v_items;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- 固定 search_path，防止函数劫持
ALTER FUNCTION public.push_driver_layout(TEXT, JSONB) SET search_path = public, extensions;
ALTER FUNCTION public.list_driver_layouts(TEXT) SET search_path = public, extensions;

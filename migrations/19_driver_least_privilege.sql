-- ============================================
-- 迁移 19：车主端最小权限角色（防删库）
-- 目标：driver_app 角色只能读写 app_settings（布局/发布状态），
--       不能碰 users / sim_runs / feedback 等其他表。
-- 效果：即使车主端的 key 泄露，攻击者也只能动布局数据，删不了全库。
-- 执行后在 Supabase 控制台：Settings → API → JWT 签发一个 role=driver_app 的 key，
--       替换车主端 Render 环境变量 SUPABASE_SERVICE_KEY。
-- ============================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'driver_app') THEN
    CREATE ROLE driver_app NOLOGIN;
  END IF;
END $$;

-- 允许 authenticator 切换到 driver_app（PostgREST 自定义角色标准做法）
GRANT driver_app TO authenticator;

-- 只授权 app_settings，不授权 users / sim_runs 等
GRANT USAGE ON SCHEMA public TO driver_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.app_settings TO driver_app;

-- app_settings 已开 RLS，给 driver_app 放行（幂等）
ALTER TABLE public.app_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS driver_app_all ON public.app_settings;
CREATE POLICY driver_app_all ON public.app_settings
  FOR ALL TO driver_app USING (true) WITH CHECK (true);

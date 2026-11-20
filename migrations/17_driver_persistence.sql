-- ============================================
-- 迁移 17：车主端持久化（算法发布状态快照 + 推送布局）
-- 前置：迁移 01~16 已执行。
-- 说明：
--   1. driver_state：车主端 FastAPI 用 service_role 直连，把「已发布算法/激活/试用/
--      审计/观测/备份」整个 ReleaseStore 状态以 JSON 快照存到这里；
--      Render 重新部署/重启后从快照恢复，解决"重新部署就丢"的问题。
--   2. driver_layouts：研究端「布局推送」到车主端的自定义停车场（新增停车场），
--      同样持久化，重启不丢。
-- 在 Supabase SQL Editor 执行（幂等，可重复执行）。
-- ============================================

-- 1. 车主端状态快照表（key-value：单键存整个 ReleaseStore 状态 JSON）
CREATE TABLE IF NOT EXISTS public.driver_state (
  key TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 推送布局表（研究端 -> 车主端，新增停车场）
CREATE TABLE IF NOT EXISTS public.driver_layouts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  data JSONB NOT NULL,
  created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_driver_layouts_created
  ON public.driver_layouts(created_at DESC);

-- 3. RLS：车主端用 service_role 直连绕过 RLS；anon/authenticated 不开放直连
--    （表数据只由车主端服务与 RPC 访问，避免密钥泄漏后被直接读取）
ALTER TABLE public.driver_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.driver_layouts ENABLE ROW LEVEL SECURITY;

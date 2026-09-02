-- ============================================
-- 迁移 14：旧版迁移 13（仅板块数组）→ 新版（板块+功能对象）数据升级
-- 仅当你在 2026-09-02 之前已执行过旧版 13 时需要本脚本；
-- 若尚未执行迁移 13，直接执行最新版 13 即可，本脚本可跳过。
-- 幂等，可重复执行。
-- ============================================

-- 1. 用户级：permissions 从 JSON 数组升级为 {sections, features}
UPDATE public.users
SET permissions = jsonb_build_object(
  'sections', permissions,
  'features', '{"can_configure":true,"can_import_demand":true,"can_export_demand":true,"can_run_simulation":true,"can_local_compute":true,"can_delete_local_task":true,"can_export_results":true,"can_delete_history":true,"can_manage_users":false,"can_manage_data":false,"can_import_algo":false,"can_debug":true,"can_submit_feedback":true,"can_manage_feedback":false}'::jsonb
)
WHERE role = 'custom'
  AND permissions IS NOT NULL
  AND jsonb_typeof(permissions) = 'array';

-- 2. 模板级：app_settings.custom_sections 同样升级
UPDATE public.app_settings
SET value = jsonb_build_object(
  'sections', value,
  'features', '{"can_configure":true,"can_import_demand":true,"can_export_demand":true,"can_run_simulation":true,"can_local_compute":true,"can_delete_local_task":true,"can_export_results":true,"can_delete_history":true,"can_manage_users":false,"can_manage_data":false,"can_import_algo":false,"can_debug":true,"can_submit_feedback":true,"can_manage_feedback":false}'::jsonb
)
WHERE key = 'custom_sections'
  AND jsonb_typeof(value) = 'array';

-- 3. 提示：RPC（get/save_custom_sections 等）请重新执行最新版迁移 13 覆盖（幂等）

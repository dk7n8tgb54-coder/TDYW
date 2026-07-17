-- 排班管理模块租户过滤性能优化索引
-- 针对tenant_id + pk的复合索引，优化租户过滤查询性能
-- 创建时间: 2026-03-04

-- 值班记录表索引
CREATE INDEX IF NOT EXISTS idx_exec_dutyrecord_tenant_pk ON exec_duty_records(tenant_id, id);
COMMENT ON INDEX idx_exec_dutyrecord_tenant_pk IS '租户过滤性能优化: tenant_id + id复合索引';

-- 交接班记录表索引
CREATE INDEX IF NOT EXISTS idx_exec_handoverrecord_tenant_pk ON exec_handover_records(tenant_id, id);
COMMENT ON INDEX idx_exec_handoverrecord_tenant_pk IS '租户过滤性能优化: tenant_id + id复合索引';

-- 排班表索引
CREATE INDEX IF NOT EXISTS idx_exec_schedule_tenant_pk ON exec_schedule(tenant_id, id);
COMMENT ON INDEX idx_exec_schedule_tenant_pk IS '租户过滤性能优化: tenant_id + id复合索引';

-- 排班人员表索引
CREATE INDEX IF NOT EXISTS idx_exec_schedulestaff_tenant_pk ON exec_schedule_staff(tenant_id, id);
COMMENT ON INDEX idx_exec_schedulestaff_tenant_pk IS '租户过滤性能优化: tenant_id + id复合索引';

-- 班次表索引
CREATE INDEX IF NOT EXISTS idx_exec_scheduleshift_tenant_pk ON exec_schedule_shift(tenant_id, id);
COMMENT ON INDEX idx_exec_scheduleshift_tenant_pk IS '租户过滤性能优化: tenant_id + id复合索引';

-- 换班记录表索引
CREATE INDEX IF NOT EXISTS idx_exec_scheduleswap_tenant_pk ON exec_schedule_swap(tenant_id, id);
COMMENT ON INDEX idx_exec_scheduleswap_tenant_pk IS '租户过滤性能优化: tenant_id + id复合索引';

-- 替班记录表索引
CREATE INDEX IF NOT EXISTS idx_exec_schedulesubstitute_tenant_pk ON exec_schedule_substitute(tenant_id, id);
COMMENT ON INDEX idx_exec_schedulesubstitute_tenant_pk IS '租户过滤性能优化: tenant_id + id复合索引';

-- 验证索引创建成功
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN (
    'exec_duty_records',
    'exec_handover_records',
    'exec_schedule',
    'exec_schedule_staff',
    'exec_schedule_shift',
    'exec_schedule_swap',
    'exec_schedule_substitute'
)
AND indexname LIKE 'idx_exec_%_tenant_pk';

-- 第二阶段修复验证 - 数据库索引验证脚本
-- 执行时间: 2026-03-17

-- ============================================
-- 1. 查看已创建的索引
-- ============================================

SELECT 
    TABLE_NAME,
    INDEX_NAME,
    COLUMN_NAME,
    CARDINALITY
FROM information_schema.STATISTICS 
WHERE TABLE_SCHEMA = 'spug' 
    AND TABLE_NAME LIKE 'exec_schedule%'
    AND INDEX_NAME LIKE 'idx_%'
ORDER BY TABLE_NAME, INDEX_NAME;

-- ============================================
-- 2. 验证索引使用情况 (P1-3)
-- ============================================

-- 测试1: 排班表复合索引验证
EXPLAIN SELECT * FROM exec_schedule 
WHERE tenant_id = 'admin' 
    AND schedule_date = '2026-03-17' 
    AND staff_id = 1;
-- 预期: key = idx_sched_tnt_date_staff, type = ref/range

-- 测试2: 排班表日期+人员索引验证
EXPLAIN SELECT * FROM exec_schedule 
WHERE schedule_date = '2026-03-17' 
    AND staff_id = 1;
-- 预期: key = idx_sched_date_staff

-- 测试3: 换班表日期范围查询索引验证
EXPLAIN SELECT * FROM exec_schedule_swap 
WHERE tenant_id = 'admin' 
    AND from_date >= '2026-03-01' 
    AND to_date <= '2026-03-31';
-- 预期: key = idx_swap_tnt_dates

-- 测试4: 换班表状态查询索引验证
EXPLAIN SELECT * FROM exec_schedule_swap 
WHERE status = 'pending';
-- 预期: key = idx_swap_status

-- 测试5: 替班表复合索引验证
EXPLAIN SELECT * FROM exec_schedule_substitute 
WHERE tenant_id = 'admin' 
    AND schedule_date = '2026-03-17' 
    AND status = 'approved';
-- 预期: key = idx_sub_tnt_date_stat

-- 测试6: 人员表活跃状态索引验证
EXPLAIN SELECT * FROM exec_schedule_staff 
WHERE tenant_id = 'admin' 
    AND is_active = TRUE;
-- 预期: key = idx_staff_tnt_active

-- ============================================
-- 3. 查询性能对比测试
-- ============================================

-- 使用索引的查询
EXPLAIN ANALYZE 
SELECT * FROM exec_schedule 
WHERE tenant_id = 'admin' 
    AND schedule_date = '2026-03-17';

-- 全表扫描的查询 (作为对比)
EXPLAIN ANALYZE 
SELECT * FROM exec_schedule 
WHERE notes LIKE '%测试%';

-- ============================================
-- 4. 索引统计信息
-- ============================================

-- 查看索引大小
SELECT 
    TABLE_NAME,
    INDEX_NAME,
    ROUND(SUM(STAT_VALUE * @@innodb_page_size) / 1024 / 1024, 2) AS size_mb
FROM mysql.innodb_index_stats
WHERE TABLE_NAME LIKE 'exec_schedule%'
    AND INDEX_NAME LIKE 'idx_%'
GROUP BY TABLE_NAME, INDEX_NAME;

-- ============================================
-- 5. 清理测试数据 (如果需要)
-- ============================================

-- 注意：以下命令会删除索引，仅用于回滚测试
-- DROP INDEX idx_sched_tnt_date_staff ON exec_schedule;
-- DROP INDEX idx_sched_date_staff ON exec_schedule;
-- DROP INDEX idx_sched_staff ON exec_schedule;

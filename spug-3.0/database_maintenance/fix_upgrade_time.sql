-- 修复 exec_upgrade_records 表缺少 upgrade_time 字段的问题
-- 执行此脚本前请备份数据库

-- 1. 添加 upgrade_time 字段
ALTER TABLE exec_upgrade_records 
ADD COLUMN upgrade_time VARCHAR(20) NULL;

-- 2. 如果存在 plan_time 字段，将数据迁移到 upgrade_time
-- ALTER TABLE exec_upgrade_records 
-- CHANGE COLUMN plan_time upgrade_time VARCHAR(20);

-- 3. 添加统计字段（如果不存在）
ALTER TABLE exec_upgrade_records 
ADD COLUMN IF NOT EXISTS update_count INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS first_update_date VARCHAR(20) NULL,
ADD COLUMN IF NOT EXISTS last_update_date VARCHAR(20) NULL;

-- 4. 验证字段已添加
DESCRIBE exec_upgrade_records;

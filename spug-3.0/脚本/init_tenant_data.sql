-- 初始化租户数据
-- 为用户分配租户ID

-- 管理员租户
UPDATE `users` SET `tenant_id` = 'admin' WHERE `username` = 'admin';

-- 通信科租户
UPDATE `users` SET `tenant_id` = 'txk' WHERE `username` = '通信科';

-- 自动化科租户
UPDATE `users` SET `tenant_id` = 'zdhk' WHERE `username` = '自动化科';

-- 导航科租户
UPDATE `users` SET `tenant_id` = 'dhk' WHERE `username` = '导航科';

-- 迁移现有数据到对应租户
-- 根据created_by的用户租户来分配

-- 运行日志
UPDATE `exec_run_logs` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 故障记录
UPDATE `exec_fault_records` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 故障备件
UPDATE `exec_fault_parts` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 干扰记录
UPDATE `exec_interferences` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 升级记录
UPDATE `exec_upgrade_records` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 值班记录
UPDATE `exec_duty_records` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 交接班记录
UPDATE `exec_handover_records` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 排班人员
UPDATE `exec_schedule_staff` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 班次规则
UPDATE `exec_schedule_shift` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 班次时间
UPDATE `exec_schedule_shift_time` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 排班表
UPDATE `exec_schedule` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 换班记录
UPDATE `exec_schedule_swap` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

-- 替班记录
UPDATE `exec_schedule_substitute` t1
INNER JOIN `users` u ON t1.created_by_id = u.id
SET t1.tenant_id = u.tenant_id
WHERE t1.tenant_id = '';

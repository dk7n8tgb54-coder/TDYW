-- 检查运行日志相关角色的权限配置
-- 在Docker容器中执行: docker exec -i spug mysql -uroot -p123456 spug < check_runlog_perms.sql

SELECT 
    id,
    name,
    page_perms
FROM roles
WHERE name LIKE '%通信%' OR id IN (
    SELECT DISTINCT role_id 
    FROM user_role_rel 
    WHERE user_id IN (
        SELECT id 
        FROM users 
        WHERE username LIKE '%通信%'
    )
);

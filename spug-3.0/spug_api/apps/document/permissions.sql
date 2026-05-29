-- 资料管理模块权限初始化脚本
-- 执行此脚本前请确保已经执行了 init.sql 创建了数据库表

-- 获取超级管理员角色的ID (假设为1，实际可能需要调整)
SET @role_id = 1;

-- 为超级管理员角色添加资料管理模块的所有权限
UPDATE roles
SET page_perms = JSON_SET(
    COALESCE(page_perms, '{}'),
    '$.document',
    JSON_OBJECT(
        'view', JSON_ARRAY('view', 'download'),
        'folder', JSON_ARRAY('create', 'delete', 'move'),
        'file', JSON_ARRAY('upload', 'delete', 'download', 'copy', 'preview')
    )
)
WHERE id = @role_id;

-- 检查权限是否添加成功
SELECT name, page_perms FROM roles WHERE id = @role_id;

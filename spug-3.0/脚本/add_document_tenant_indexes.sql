-- ==========================================
-- 文档管理模块租户隔离优化索引
-- 用于提升租户过滤查询性能
-- ==========================================

-- ==========================================
-- 索引创建辅助函数（MySQL 8.0+ 兼容）
-- ==========================================
DELIMITER $$

DROP PROCEDURE IF EXISTS create_index_if_not_exists$$

CREATE PROCEDURE create_index_if_not_exists(
    IN table_name VARCHAR(64),
    IN index_name VARCHAR(64),
    IN index_definition TEXT
)
BEGIN
    DECLARE index_count INT;

    -- 检查索引是否已存在
    SELECT COUNT(*) INTO index_count
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE table_schema = DATABASE()
      AND table_name = table_name
      AND index_name = index_name;

    -- 如果索引不存在，则创建
    IF index_count = 0 THEN
        SET @sql = CONCAT('CREATE INDEX ', index_name, ' ON ', table_name, ' ', index_definition);
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('✅ 索引 ', index_name, ' 创建成功') AS result;
    ELSE
        SELECT CONCAT('ℹ️  索引 ', index_name, ' 已存在，跳过创建') AS result;
    END IF;
END$$

DELIMITER ;

-- ==========================================
-- 1. 私有文件夹表索引
-- ==========================================

-- 优化场景：按租户查询文件夹
CALL create_index_if_not_exists(
    'spug_document_folder_private',
    'idx_doc_folder_private_tenant',
    '(tenant_id)'
);

-- 优化场景：按租户和父文件夹查询
CALL create_index_if_not_exists(
    'spug_document_folder_private',
    'idx_doc_folder_private_tenant_parent',
    '(tenant_id, parent_id)'
);

-- ==========================================
-- 2. 私有文件表索引
-- ==========================================

-- 优化场景：按租户查询文件
CALL create_index_if_not_exists(
    'spug_document_file_private',
    'idx_doc_file_private_tenant',
    '(tenant_id)'
);

-- 优化场景：按租户和文件夹查询
CALL create_index_if_not_exists(
    'spug_document_file_private',
    'idx_doc_file_private_tenant_folder',
    '(tenant_id, folder_id)'
);

-- 优化场景：按租户和创建人查询
CALL create_index_if_not_exists(
    'spug_document_file_private',
    'idx_doc_file_private_tenant_created_by',
    '(tenant_id, created_by_id)'
);

-- ==========================================
-- 3. 公共文件夹表索引
-- ==========================================

-- 优化场景：按父文件夹查询公共文件夹
CALL create_index_if_not_exists(
    'spug_document_folder_public',
    'idx_doc_folder_public_parent',
    '(parent_id)'
);

-- ==========================================
-- 4. 公共文件表索引
-- ==========================================

-- 优化场景：按文件夹查询公共文件
CALL create_index_if_not_exists(
    'spug_document_file_public',
    'idx_doc_file_public_folder',
    '(folder_id)'
);

-- 优化场景：按创建人查询公共文件
CALL create_index_if_not_exists(
    'spug_document_file_public',
    'idx_doc_file_public_created_by',
    '(created_by_id)'
);

-- ==========================================
-- 清理辅助函数
-- ==========================================
DELIMITER $$

DROP PROCEDURE IF EXISTS create_index_if_not_exists$$

DELIMITER ;

-- ==========================================
-- 验证索引创建结果
-- ==========================================

SELECT
    table_name AS '表名',
    index_name AS '索引名',
    column_name AS '列名',
    index_type AS '类型',
    non_unique AS '允许重复'
FROM INFORMATION_SCHEMA.STATISTICS
WHERE table_schema = DATABASE()
  AND table_name IN ('spug_document_folder_private', 'spug_document_file_private',
                   'spug_document_folder_public', 'spug_document_file_public')
  AND index_name LIKE 'idx_doc_%'
ORDER BY table_name, index_name, seq_in_index;

-- ==========================================
-- 索引使用说明
-- ==========================================
-- idx_doc_folder_private_tenant: 用于 WHERE tenant_id = ? 的查询
-- idx_doc_folder_private_tenant_parent: 用于 WHERE tenant_id = ? AND parent_id = ? 的查询
-- idx_doc_file_private_tenant: 用于 WHERE tenant_id = ? 的查询
-- idx_doc_file_private_tenant_folder: 用于 WHERE tenant_id = ? AND folder_id = ? 的查询
-- idx_doc_file_private_tenant_created_by: 用于 WHERE tenant_id = ? AND created_by_id = ? 的查询
-- idx_doc_folder_public_parent: 用于 WHERE parent_id = ? 的查询
-- idx_doc_file_public_folder: 用于 WHERE folder_id = ? 的查询
-- idx_doc_file_public_created_by: 用于 WHERE created_by_id = ? 的查询

-- ==========================================
-- 性能影响评估
-- ==========================================
-- 写操作：索引会增加 INSERT/UPDATE/DELETE 的开销（约 10-20%）
-- 读操作：索引可提升 SELECT 性能 50-90%（特别是租户过滤场景）
-- 空间：索引约占表大小的 20-30%

-- ==========================================
-- PostgreSQL 版本（如果使用 PostgreSQL，请使用以下脚本）
-- ==========================================
/*
-- PostgreSQL 索引创建脚本
CREATE INDEX IF NOT EXISTS idx_doc_folder_private_tenant
ON spug_document_folder_private (tenant_id);

CREATE INDEX IF NOT EXISTS idx_doc_folder_private_tenant_parent
ON spug_document_folder_private (tenant_id, parent_id);

CREATE INDEX IF NOT EXISTS idx_doc_file_private_tenant
ON spug_document_file_private (tenant_id);

CREATE INDEX IF NOT EXISTS idx_doc_file_private_tenant_folder
ON spug_document_file_private (tenant_id, folder_id);

CREATE INDEX IF NOT EXISTS idx_doc_file_private_tenant_created_by
ON spug_document_file_private (tenant_id, created_by_id);

CREATE INDEX IF NOT EXISTS idx_doc_folder_public_parent
ON spug_document_folder_public (parent_id);

CREATE INDEX IF NOT EXISTS idx_doc_file_public_folder
ON spug_document_file_public (folder_id);

CREATE INDEX IF NOT EXISTS idx_doc_file_public_created_by
ON spug_document_file_public (created_by_id);
*/

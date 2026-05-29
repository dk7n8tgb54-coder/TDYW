-- 分表迁移SQL脚本
-- 将原有表重命名为私有表,创建新的公共表

-- 步骤1: 将原表重命名为私有表(保留所有数据)
ALTER TABLE spug_document_folder RENAME TO spug_document_folder_private;
ALTER TABLE spug_document_file RENAME TO spug_document_file_private;

-- 步骤2: 更新私有文件表的外键指向私有文件夹表
ALTER TABLE spug_document_file_private 
DROP FOREIGN KEY spug_document_file_folder_id_...;

-- 步骤3: 创建公共文件夹表
CREATE TABLE spug_document_folder_public (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL COMMENT '文件夹名称',
    parent_id INT NULL COMMENT '父文件夹ID',
    created_by_id INT NULL COMMENT '创建人ID',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_parent_id (parent_id),
    INDEX idx_created_by (created_by_id),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (parent_id) REFERENCES spug_document_folder_public(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件夹';

-- 步骤4: 创建公共文件表
CREATE TABLE spug_document_file_public (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL COMMENT '文件名',
    folder_id INT NULL COMMENT '所属文件夹ID',
    file_path VARCHAR(500) NOT NULL COMMENT '文件存储路径',
    file_size BIGINT NOT NULL DEFAULT 0 COMMENT '文件大小(字节)',
    file_type VARCHAR(500) NOT NULL COMMENT '文件类型',
    created_by_id INT NULL COMMENT '上传人ID',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    INDEX idx_folder_id (folder_id),
    INDEX idx_created_by (created_by_id),
    INDEX idx_created_at (created_at),
    UNIQUE KEY uk_folder_name (folder_id, name),
    FOREIGN KEY (folder_id) REFERENCES spug_document_folder_public(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件';

-- 步骤5: 更新私有文件表的外键
ALTER TABLE spug_document_file_private
ADD CONSTRAINT fk_file_private_folder 
FOREIGN KEY (folder_id) REFERENCES spug_document_folder_private(id) ON DELETE CASCADE;

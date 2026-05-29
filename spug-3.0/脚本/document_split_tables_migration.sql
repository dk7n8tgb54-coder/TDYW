-- 分表迁移SQL脚本
-- 将原有表重命名为私有表，创建新的公共表
-- Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug

-- 备份原有表结构（用于回滚）
-- CREATE TABLE spug_document_folder_backup LIKE spug_document_folder;
-- CREATE TABLE spug_document_file_backup LIKE spug_document_file;

-- 步骤1: 将原表 spug_document_folder 重命名为 spug_document_folder_private
RENAME TABLE spug_document_folder TO spug_document_folder_private;

-- 步骤2: 将原表 spug_document_file 重命名为 spug_document_file_private
RENAME TABLE spug_document_file TO spug_document_file_private;

-- 步骤3: 更新私有文件表的外键约束（指向私有文件夹表）
-- 由于Django的外键引用表名，需要重新创建约束
-- 注意：MySQL会自动更新外键指向，因为表名已更改

-- 步骤4: 创建空的公共文件夹表
CREATE TABLE IF NOT EXISTS `spug_document_folder_public` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT '文件夹名称',
  `parent_id` int(11) DEFAULT NULL COMMENT '父文件夹',
  `created_by_id` int(11) DEFAULT NULL COMMENT '创建人',
  `created_at` datetime(6) NOT NULL COMMENT '创建时间',
  `updated_at` datetime(6) NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `spug_document_folder_public_parent_id_idx` (`parent_id`),
  KEY `spug_document_folder_public_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_folder_public_created_by_id_fk` FOREIGN KEY (`created_by_id`) REFERENCES `spug_account_user` (`id`) ON DELETE SET NULL,
  CONSTRAINT `spug_document_folder_public_parent_id_fk` FOREIGN KEY (`parent_id`) REFERENCES `spug_document_folder_public` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件夹';

-- 步骤5: 创建空的公共文件表
CREATE TABLE IF NOT EXISTS `spug_document_file_public` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT '文件名',
  `file_path` varchar(500) NOT NULL COMMENT '文件存储路径',
  `file_size` bigint(20) NOT NULL DEFAULT '0' COMMENT '文件大小(字节)',
  `file_type` varchar(500) NOT NULL COMMENT '文件类型',
  `folder_id` int(11) DEFAULT NULL COMMENT '所属文件夹',
  `created_by_id` int(11) DEFAULT NULL COMMENT '上传人',
  `created_at` datetime(6) NOT NULL COMMENT '上传时间',
  PRIMARY KEY (`id`),
  KEY `spug_document_file_public_folder_id_idx` (`folder_id`),
  KEY `spug_document_file_public_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_file_public_created_by_id_fk` FOREIGN KEY (`created_by_id`) REFERENCES `spug_account_user` (`id`) ON DELETE SET NULL,
  CONSTRAINT `spug_document_file_public_folder_id_fk` FOREIGN KEY (`folder_id`) REFERENCES `spug_document_folder_public` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='公共文档文件';

-- 步骤6: 更新Django迁移记录表（标记迁移已应用）
INSERT INTO django_migrations (app, name, applied) VALUES 
('document', '0002_document_split_public_private', NOW())
ON DUPLICATE KEY UPDATE applied = NOW();

-- 验证SQL
SELECT 'Migration completed successfully!' AS message;
SELECT COUNT(*) AS private_folders FROM spug_document_folder_private;
SELECT COUNT(*) AS private_files FROM spug_document_file_private;
SELECT COUNT(*) AS public_folders FROM spug_document_folder_public;
SELECT COUNT(*) AS public_files FROM spug_document_file_public;

-- 资料管理模块数据库初始化脚本
-- Windows环境使用方法：
-- 1. 找到MySQL安装目录，通常在 C:\Program Files\MySQL\MySQL Server 8.0\bin\
-- 2. 使用以下命令执行：
--    cd "C:\Program Files\MySQL\MySQL Server 8.0\bin"
--    mysql -u root -p spug < "E:\TDYW\spug-3.0\spug_api\apps\document\init.sql"
--
-- 或者使用Docker环境：
--    docker exec -i spug-mysql mysql -u root -p spug < "E:\TDYW\spug-3.0\spug_api\apps\document\init.sql"
--
-- 或者使用phpMyAdmin等图形工具直接执行以下SQL语句

-- 创建文档文件夹表
CREATE TABLE IF NOT EXISTS `spug_document_folder` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT '文件夹名称',
  `parent_id` int(11) DEFAULT NULL COMMENT '父文件夹ID',
  `created_by_id` int(11) DEFAULT NULL COMMENT '创建人ID',
  `created_at` datetime NOT NULL COMMENT '创建时间',
  `updated_at` datetime NOT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `spug_document_folder_parent_id_idx` (`parent_id`),
  KEY `spug_document_folder_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_folder_parent_id_refs_id` FOREIGN KEY (`parent_id`) REFERENCES `spug_document_folder` (`id`) ON DELETE CASCADE,
  CONSTRAINT `spug_document_folder_created_by_id_refs_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档文件夹表';

-- 创建文档文件表
CREATE TABLE IF NOT EXISTS `spug_document_file` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(200) NOT NULL COMMENT '文件名',
  `folder_id` int(11) DEFAULT NULL COMMENT '所属文件夹ID',
  `file_path` varchar(500) NOT NULL COMMENT '文件存储路径',
  `file_size` bigint(20) NOT NULL DEFAULT '0' COMMENT '文件大小(字节)',
  `file_type` varchar(50) NOT NULL COMMENT '文件类型',
  `created_by_id` int(11) DEFAULT NULL COMMENT '上传人ID',
  `created_at` datetime NOT NULL COMMENT '上传时间',
  PRIMARY KEY (`id`),
  KEY `spug_document_file_folder_id_idx` (`folder_id`),
  KEY `spug_document_file_created_by_id_idx` (`created_by_id`),
  CONSTRAINT `spug_document_file_folder_id_refs_id` FOREIGN KEY (`folder_id`) REFERENCES `spug_document_folder` (`id`) ON DELETE CASCADE,
  CONSTRAINT `spug_document_file_created_by_id_refs_id` FOREIGN KEY (`created_by_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档文件表';

-- 显示创建成功信息
SELECT '资料管理模块数据库表创建成功！' AS message;

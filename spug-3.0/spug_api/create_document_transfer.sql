-- DocumentTransfer 表创建 SQL
-- Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
-- Copyright: (c) <spug.dev@gmail.com>
-- Released under the AGPL-3.0 License.

-- 创建文件传输记录表
CREATE TABLE IF NOT EXISTS `tdyw_document_transfer` (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    `tenant_id` VARCHAR(50) NOT NULL DEFAULT '' COMMENT '租户标识',
    `user_id` INT NULL COMMENT '用户ID',
    `transfer_type` VARCHAR(20) NOT NULL COMMENT '传输类型：UPLOAD-上传, DOWNLOAD-下载',
    `status` VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '状态：PENDING-等待中, UPLOADING-上传中, DOWNLOADING-下载中, PAUSED-已暂停, COMPLETED-已完成, FAILED-失败, CANCELED-已取消',
    `file_name` VARCHAR(255) NOT NULL COMMENT '文件名',
    `file_size` BIGINT NOT NULL DEFAULT 0 COMMENT '文件大小(字节)',
    `file_path` VARCHAR(500) NOT NULL COMMENT '文件存储路径',
    `file_hash` VARCHAR(100) NULL COMMENT '文件哈希(MD5)',
    `folder_id` INT NULL COMMENT '目标文件夹ID',
    `is_public` BOOLEAN NOT NULL DEFAULT FALSE COMMENT '是否公共空间',
    `total_chunks` INT NOT NULL DEFAULT 0 COMMENT '总分片数',
    `uploaded_chunks` INT NOT NULL DEFAULT 0 COMMENT '已上传分片数',
    `progress` INT NOT NULL DEFAULT 0 COMMENT '进度百分比',
    `transferred_size` BIGINT NOT NULL DEFAULT 0 COMMENT '已传输大小(字节)',
    `speed` FLOAT NOT NULL DEFAULT 0 COMMENT '传输速度(字节/秒)',
    `created_at` DATETIME NOT NULL COMMENT '创建时间',
    `started_at` DATETIME NULL COMMENT '开始时间',
    `completed_at` DATETIME NULL COMMENT '完成时间',
    `updated_at` DATETIME NOT NULL COMMENT '更新时间',
    `error_message` TEXT NULL COMMENT '错误信息',
    INDEX `idx_transfer_tenant_user` (`tenant_id`, `user_id`),
    INDEX `idx_transfer_tenant_status` (`tenant_id`, `status`),
    INDEX `idx_transfer_tenant_hash` (`tenant_id`, `file_hash`),
    INDEX `idx_transfer_user_status` (`user_id`, `status`),
    INDEX `idx_transfer_created` (`created_at`),
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文件传输记录表';

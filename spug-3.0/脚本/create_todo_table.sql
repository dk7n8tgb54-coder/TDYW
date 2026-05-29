-- 创建待办事项表
CREATE TABLE IF NOT EXISTS `todos` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL COMMENT '用户ID',
  `user_name` varchar(100) NOT NULL COMMENT '用户名',
  `title` varchar(200) NOT NULL COMMENT '待办标题',
  `description` text COMMENT '描述',
  `status` varchar(20) NOT NULL DEFAULT 'pending' COMMENT '状态: pending待完成, completed已完成',
  `priority` varchar(20) NOT NULL DEFAULT 'medium' COMMENT '优先级: low低, medium中, high高',
  `due_date` varchar(20) DEFAULT NULL COMMENT '截止日期',
  `created_at` varchar(20) NOT NULL COMMENT '创建时间',
  `created_by_id` int(11) NOT NULL,
  `updated_at` varchar(20) DEFAULT NULL COMMENT '更新时间',
  `updated_by_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_status` (`status`),
  KEY `idx_priority` (`priority`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='待办事项表';

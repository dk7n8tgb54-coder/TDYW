-- 创建故障件管理表
CREATE TABLE IF NOT EXISTS `exec_fault_parts` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL COMMENT '故障件名称',
  `system_name` varchar(100) NOT NULL COMMENT '所属系统',
  `date` varchar(20) NOT NULL COMMENT '日期',
  `fault_date` varchar(20) NOT NULL COMMENT '故障日期',
  `status` varchar(20) NOT NULL COMMENT '状态',
  `fault_sent_date` varchar(20) DEFAULT NULL COMMENT '送修日期',
  `test_return_date` varchar(20) DEFAULT NULL COMMENT '运回测试日期',
  `archive_date` varchar(20) DEFAULT NULL COMMENT '归档日期',
  `created_at` varchar(20) NOT NULL COMMENT '创建时间',
  `created_by_id` int(11) NOT NULL COMMENT '创建人',
  `updated_at` varchar(20) DEFAULT NULL COMMENT '更新时间',
  `updated_by_id` int(11) DEFAULT NULL COMMENT '更新人',
  PRIMARY KEY (`id`),
  KEY `status_idx` (`status`),
  KEY `system_name_idx` (`system_name`),
  KEY `date_idx` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='故障件管理表';

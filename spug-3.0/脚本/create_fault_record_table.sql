-- 创建故障处置记录表
CREATE TABLE IF NOT EXISTS `exec_fault_records` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `system_name` varchar(100) NOT NULL COMMENT '系统名称',
  `device_code` varchar(100) NOT NULL COMMENT '设备编号',
  `fault_date` varchar(20) NOT NULL COMMENT '日期',
  `handler` varchar(100) NOT NULL COMMENT '处置人员',
  `recorder` varchar(100) NOT NULL COMMENT '记录人员',
  `fault_level` varchar(10) NOT NULL COMMENT '故障评级',
  `fault_phenomenon` text NOT NULL COMMENT '故障现象',
  `handling_process` text NOT NULL COMMENT '处置过程',
  `created_at` varchar(20) NOT NULL COMMENT '创建时间',
  `created_by_id` int(11) NOT NULL COMMENT '创建人',
  `updated_at` varchar(20) DEFAULT NULL COMMENT '更新时间',
  `updated_by_id` int(11) DEFAULT NULL COMMENT '更新人',
  PRIMARY KEY (`id`),
  KEY `fault_date_idx` (`fault_date`),
  KEY `system_name_idx` (`system_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='故障处置记录表';

-- 创建干扰管理表
CREATE TABLE IF NOT EXISTS `exec_interferences` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `frequency` VARCHAR(100) NOT NULL COMMENT '频率',
  `report_dept` VARCHAR(100) NOT NULL COMMENT '汇报科室',
  `datetime` VARCHAR(20) NOT NULL COMMENT '日期时间',
  `coordinates` VARCHAR(200) NOT NULL COMMENT '坐标',
  `interference_type` VARCHAR(100) NOT NULL COMMENT '干扰类型',
  `phenomenon` TEXT NOT NULL COMMENT '现象',
  `flight_number` VARCHAR(100) NULL COMMENT '航班号',
  `aircraft_type` VARCHAR(100) NULL COMMENT '机型',
  `is_reported` VARCHAR(10) DEFAULT '否' COMMENT '是否上报',
  `created_at` VARCHAR(20) NOT NULL COMMENT '创建时间',
  `created_by_id` INT NOT NULL COMMENT '创建人ID',
  `updated_at` VARCHAR(20) NULL COMMENT '更新时间',
  `updated_by_id` INT NULL COMMENT '更新人ID',
  INDEX `idx_datetime` (`datetime`),
  INDEX `idx_report_dept` (`report_dept`),
  INDEX `idx_interference_type` (`interference_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='干扰管理表';

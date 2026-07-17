-- 完整排班系统数据库表结构

-- 1. 排班人员表
CREATE TABLE IF NOT EXISTS exec_schedule_staff (
    id INT(11) NOT NULL AUTO_INCREMENT,
    user_id INT(11) NOT NULL COMMENT '关联的用户ID',
    user_name VARCHAR(100) NOT NULL COMMENT '用户名',
    department VARCHAR(100) DEFAULT NULL COMMENT '部门',
    phone VARCHAR(20) DEFAULT NULL COMMENT '联系电话',
    is_active TINYINT(1) DEFAULT 1 COMMENT '是否激活',
    unavailable_dates TEXT DEFAULT NULL COMMENT '不可用日期(JSON数组)',
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    KEY user_id (user_id),
    KEY is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='排班人员表';

-- 2. 班次规则表
CREATE TABLE IF NOT EXISTS exec_schedule_shift (
    id INT(11) NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL COMMENT '班次名称',
    work_days INT(11) DEFAULT NULL COMMENT '工作天数',
    rest_days INT(11) DEFAULT NULL COMMENT '休息天数',
    shift_type VARCHAR(50) NOT NULL COMMENT '班次类型: work_rest(上X休Y), custom(自定义)',
    description TEXT DEFAULT NULL COMMENT '班次描述',
    color VARCHAR(20) DEFAULT NULL COMMENT '颜色标记',
    is_default TINYINT(1) DEFAULT 0 COMMENT '是否默认班次',
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    KEY shift_type (shift_type),
    KEY is_default (is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='班次规则表';

-- 3. 班次时间配置表
CREATE TABLE IF NOT EXISTS exec_schedule_shift_time (
    id INT(11) NOT NULL AUTO_INCREMENT,
    shift_id INT(11) NOT NULL COMMENT '关联班次ID',
    shift_name VARCHAR(100) NOT NULL COMMENT '班次名称',
    start_time VARCHAR(20) NOT NULL COMMENT '开始时间',
    end_time VARCHAR(20) NOT NULL COMMENT '结束时间',
    color VARCHAR(20) DEFAULT NULL COMMENT '颜色标记',
    sort_order INT(11) DEFAULT 0 COMMENT '排序',
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    KEY shift_id (shift_id),
    KEY shift_name (shift_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='班次时间配置表';

-- 4. 排班表
CREATE TABLE IF NOT EXISTS exec_schedule (
    id INT(11) NOT NULL AUTO_INCREMENT,
    staff_id INT(11) NOT NULL COMMENT '人员ID',
    staff_name VARCHAR(100) NOT NULL COMMENT '人员姓名',
    schedule_date VARCHAR(20) NOT NULL COMMENT '排班日期',
    shift_id INT(11) NOT NULL COMMENT '班次ID',
    shift_name VARCHAR(100) NOT NULL COMMENT '班次名称',
    shift_time_id INT(11) DEFAULT NULL COMMENT '班次时间ID',
    notes TEXT DEFAULT NULL COMMENT '备注',
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY unique_schedule (staff_id, schedule_date),
    KEY schedule_date (schedule_date),
    KEY shift_id (shift_id),
    KEY staff_id (staff_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='排班表';

-- 5. 换班记录表
CREATE TABLE IF NOT EXISTS exec_schedule_swap (
    id INT(11) NOT NULL AUTO_INCREMENT,
    from_staff_id INT(11) NOT NULL COMMENT '申请人ID',
    from_staff_name VARCHAR(100) NOT NULL COMMENT '申请人姓名',
    to_staff_id INT(11) NOT NULL COMMENT '被换人ID',
    to_staff_name VARCHAR(100) NOT NULL COMMENT '被换人姓名',
    schedule_date VARCHAR(20) NOT NULL COMMENT '换班日期',
    from_shift_id INT(11) NOT NULL COMMENT '申请人班次ID',
    from_shift_name VARCHAR(100) NOT NULL COMMENT '申请人班次名称',
    to_shift_id INT(11) NOT NULL COMMENT '被换人班次ID',
    to_shift_name VARCHAR(100) NOT NULL COMMENT '被换人班次名称',
    reason TEXT DEFAULT NULL COMMENT '换班原因',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '状态: pending待审批, approved已通过, rejected已拒绝, cancelled已取消',
    approved_by_id INT(11) DEFAULT NULL COMMENT '审批人ID',
    approved_by_name VARCHAR(100) DEFAULT NULL COMMENT '审批人姓名',
    approved_at VARCHAR(20) DEFAULT NULL COMMENT '审批时间',
    remarks TEXT DEFAULT NULL COMMENT '审批备注',
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    KEY schedule_date (schedule_date),
    KEY status (status),
    KEY from_staff_id (from_staff_id),
    KEY to_staff_id (to_staff_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='换班记录表';

-- 6. 替班记录表
CREATE TABLE IF NOT EXISTS exec_schedule_substitute (
    id INT(11) NOT NULL AUTO_INCREMENT,
    original_staff_id INT(11) NOT NULL COMMENT '原值班人ID',
    original_staff_name VARCHAR(100) NOT NULL COMMENT '原值班人姓名',
    substitute_staff_id INT(11) NOT NULL COMMENT '替班人ID',
    substitute_staff_name VARCHAR(100) NOT NULL COMMENT '替班人姓名',
    schedule_date VARCHAR(20) NOT NULL COMMENT '替班日期',
    shift_id INT(11) NOT NULL COMMENT '班次ID',
    shift_name VARCHAR(100) NOT NULL COMMENT '班次名称',
    reason TEXT DEFAULT NULL COMMENT '替班原因',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '状态: pending待审批, approved已通过, rejected已拒绝, cancelled已取消',
    approved_by_id INT(11) DEFAULT NULL COMMENT '审批人ID',
    approved_by_name VARCHAR(100) DEFAULT NULL COMMENT '审批人姓名',
    approved_at VARCHAR(20) DEFAULT NULL COMMENT '审批时间',
    remarks TEXT DEFAULT NULL COMMENT '审批备注',
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    KEY schedule_date (schedule_date),
    KEY status (status),
    KEY original_staff_id (original_staff_id),
    KEY substitute_staff_id (substitute_staff_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='替班记录表';

-- 插入默认班次
INSERT INTO exec_schedule_shift (name, work_days, rest_days, shift_type, description, color, is_default, created_at, created_by_id) VALUES
('白班', 1, 0, 'custom', '早上8:00-下午6:00', '#52c41a', 1, NOW(), 1),
('夜班', 1, 0, 'custom', '晚上6:00-次日早上8:00', '#1890ff', 0, NOW(), 1);

INSERT INTO exec_schedule_shift_time (shift_id, shift_name, start_time, end_time, color, sort_order, created_at, created_by_id) VALUES
(1, '白班', '08:00', '18:00', '#52c41a', 1, NOW(), 1),
(2, '夜班', '18:00', '08:00', '#1890ff', 2, NOW(), 1);

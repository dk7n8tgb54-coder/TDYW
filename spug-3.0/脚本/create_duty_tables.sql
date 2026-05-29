CREATE TABLE IF NOT EXISTS exec_duty_records (
    id INT(11) NOT NULL AUTO_INCREMENT,
    user_id INT(11) NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    duty_date VARCHAR(20) NOT NULL,
    log_content TEXT,
    events TEXT,
    attachments TEXT,
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    KEY user_name (user_name),
    KEY duty_date (duty_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exec_handover_records (
    id INT(11) NOT NULL AUTO_INCREMENT,
    from_user_id INT(11) NOT NULL,
    from_user_name VARCHAR(100) NOT NULL,
    to_user_id INT(11) NOT NULL,
    to_user_name VARCHAR(100) NOT NULL,
    handover_time VARCHAR(20) NOT NULL,
    items TEXT,
    notes TEXT,
    confirmed TINYINT(1) DEFAULT 0,
    confirmed_at VARCHAR(20) NULL,
    created_at VARCHAR(20) NOT NULL,
    created_by_id INT(11) NOT NULL,
    updated_at VARCHAR(20) NULL,
    updated_by_id INT(11) NULL,
    PRIMARY KEY (id),
    KEY handover_time (handover_time),
    KEY confirmed (confirmed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

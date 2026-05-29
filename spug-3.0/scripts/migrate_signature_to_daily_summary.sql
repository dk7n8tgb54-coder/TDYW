-- 迁移脚本：将 checksheet_signature 表合并到 checksheet_daily_summary
-- 步骤1：在 checksheet_daily_summary 表中添加 operator 字段
-- 步骤2：将现有 checksheet_signature 数据迁移到 checksheet_daily_summary
-- 步骤3：删除 checksheet_signature 表

-- 开始事务
START TRANSACTION;

-- 步骤1：在 checksheet_daily_summary 表中添加 operator 字段
ALTER TABLE `checksheet_daily_summary`
ADD COLUMN `operator` VARCHAR(50) DEFAULT NULL COMMENT '值班人员' AFTER `day`;

-- 步骤2：将现有 checksheet_signature 数据迁移到 checksheet_daily_summary
-- 注意：checksheet_signature 表可能有多条记录（每个项目一条）
-- 需要选择一个记录作为值班人员，这里选择 operator 不为空的记录
UPDATE `checksheet_daily_summary` ds
SET `ds`.`operator` = (
    SELECT `cs`.`operator`
    FROM `checksheet_signature` cs
    WHERE `cs`.`year` = `ds`.`year`
      AND `cs`.`month` = `ds`.`month`
      AND `cs`.`day` = `ds`.`day`
      AND `cs`.`operator` IS NOT NULL
      AND `cs`.`operator` != ''
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1
    FROM `checksheet_signature` cs
    WHERE `cs`.`year` = `ds`.`year`
      AND `cs`.`month` = `ds`.`month`
      AND `cs`.`day` = `ds`.`day`
      AND `cs`.`operator` IS NOT NULL
      AND `cs`.`operator` != ''
);

-- 步骤3：删除 checksheet_signature 表
DROP TABLE IF EXISTS `checksheet_signature`;

-- 提交事务
COMMIT;

-- 验证迁移结果
SELECT 'Migration completed' AS status;
SELECT COUNT(*) AS daily_summary_count FROM `checksheet_daily_summary`;
SELECT COUNT(*) AS operator_not_null_count FROM `checksheet_daily_summary` WHERE `operator` IS NOT NULL AND `operator` != '';

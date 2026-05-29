# 日检查表备注和整改情况改为每日汇总方案

## 概述
将日检查表录入中的"发现问题及整改情况"和"备注"字段，从每条检查项对应一个，改为每个项目每天只有一个统一的汇总字段。

## 修改内容

### 1. 数据库修改

#### 1.1 创建新表 `checksheet_daily_summary`
```sql
CREATE TABLE IF NOT EXISTS checksheet_daily_summary (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    template_id INT NOT NULL COMMENT '模板ID',
    year VARCHAR(4) NOT NULL COMMENT '年份',
    month VARCHAR(2) NOT NULL COMMENT '月份',
    day INT NOT NULL COMMENT '日期',
    remark TEXT COMMENT '备注',
    rectification TEXT COMMENT '发现问题及整改情况',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY unique_template_date (template_id, year, month, day),
    FOREIGN KEY (template_id) REFERENCES checksheet_template(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日检查汇总表';
```

#### 1.2 修改 `checksheet_signature` 表
```sql
-- 添加 day 字段
ALTER TABLE checksheet_signature
ADD COLUMN IF NOT EXISTS day INT DEFAULT 1 COMMENT '日期' AFTER month;

-- 修改唯一约束
ALTER TABLE checksheet_signature
DROP INDEX IF EXISTS checksheet_signature_template_id_year_month_uniq;

ALTER TABLE checksheet_signature
ADD UNIQUE KEY unique_template_date (template_id, year, month, day);
```

### 2. 后端修改

#### 2.1 模型修改 (`spug_api/apps/checksheet/models.py`)
- 新增 `CheckSheetDailySummary` 模型
- 修改 `CheckSheetSignature` 模型，添加 `day` 字段

#### 2.2 视图修改 (`spug_api/apps/checksheet/views.py`)
- GET 方法：返回 `daily_summaries` 字段（按天分组的汇总数据）
- POST 方法：接收 `daily_summary` 参数，保存到 `CheckSheetDailySummary` 表
- 检查记录不再包含 `remark` 和 `rectification` 字段

### 3. 前端修改

#### 3.1 CheckSheet.js
- 修改数据加载逻辑，从 `daily_summaries` 获取每日汇总
- 修改保存逻辑，发送 `daily_summary` 参数
- 修改表格渲染，`rowSpan` 合并单元格，每个项目每天只有一个"发现问题及整改情况"和"备注"输入框

#### 3.2 store.js
- `fetchCheckRecords` 方法支持可选的 `day` 参数

## 迁移步骤

1. **执行数据库迁移**
   ```bash
   # 在 MySQL Workbench 中执行
   mysql -u root -p spug < create_daily_summary_table.sql
   ```

2. **重启后端服务**
   ```bash
   # 重启 Django 服务以加载新的模型
   ```

3. **前端自动更新**
   - 修改前端代码后，热重载会自动更新

4. **测试验证**
   - 加载数据：验证是否能正确显示每日汇总
   - 保存数据：验证每日汇总是否正确保存到数据库
   - 检查表格布局：验证"发现问题及整改情况"和"备注"是否已合并

## 兼容性说明

- 原有的 `checksheet_record` 表中的 `remark` 和 `rectification` 字段保留不变
- 旧数据仍然可以查看，但新保存的数据会使用新的结构
- 如需迁移旧数据，可以将每条记录的 `remark` 和 `rectification` 合并到每日汇总中

## 数据迁移（可选）

如果需要将旧数据的 `remark` 和 `rectification` 迁移到每日汇总：

```sql
-- 示例：将每天的所有 remark 和 rectification 合并到 daily_summary 表
INSERT INTO checksheet_daily_summary (template_id, year, month, day, remark, rectification, created_at, updated_at)
SELECT
    template_id,
    year,
    month,
    day,
    GROUP_CONCAT(remark SEPARATOR '\n') as remark,
    GROUP_CONCAT(rectification SEPARATOR '\n') as rectification,
    NOW(),
    NOW()
FROM checksheet_record
WHERE remark IS NOT NULL AND remark != '' OR rectification IS NOT NULL AND rectification != ''
GROUP BY template_id, year, month, day
ON DUPLICATE KEY UPDATE
    remark = VALUES(remark),
    rectification = VALUES(rectification),
    updated_at = NOW();
```

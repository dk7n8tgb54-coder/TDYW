-- 检查数据库表碎片情况
USE spug;

-- 1. 检查碎片情况
SELECT '=== 数据库表碎片检查 ===' AS message;

SELECT table_schema, table_name, data_free, engine 
FROM information_schema.tables 
WHERE table_schema = 'spug' AND data_free > 0 
ORDER BY data_free DESC;

-- 2. 检查所有表状态
SELECT '=== 所有表状态 ===' AS message;

SELECT table_name, table_rows, data_length, index_length, data_length + index_length as total_size 
FROM information_schema.tables 
WHERE table_schema = 'spug' 
ORDER BY total_size DESC;

-- 3. 优化有碎片的表
SELECT '=== 开始优化表 ===' AS message;

-- 生成优化命令
SET @sql = NULL;

SELECT GROUP_CONCAT(
    CONCAT('OPTIMIZE TABLE ', table_name, ';')
    SEPARATOR '\n'
) INTO @sql
FROM information_schema.tables 
WHERE table_schema = 'spug' AND data_free > 0;

-- 执行优化
IF @sql IS NOT NULL THEN
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
    SELECT '=== 优化完成 ===' AS message;
ELSE
    SELECT '=== 无表需要优化 ===' AS message;
END IF;

-- 4. 再次检查碎片情况
SELECT '=== 优化后碎片检查 ===' AS message;

SELECT table_schema, table_name, data_free, engine 
FROM information_schema.tables 
WHERE table_schema = 'spug' AND data_free > 0 
ORDER BY data_free DESC;

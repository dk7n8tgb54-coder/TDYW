-- 删除文件表的唯一索引（display_name方案实施后执行）
-- 注意：此操作需要确保后端+前端改造完成并稳定运行1-2周后执行

-- 步骤1: 查看现有唯一索引
SHOW INDEX FROM spug_document_file_public WHERE Key_name LIKE '%unique%';
SHOW INDEX FROM spug_document_file_private WHERE Key_name LIKE '%unique%';
SHOW INDEX FROM spug_document_folder_public WHERE Key_name LIKE '%unique%';
SHOW INDEX FROM spug_document_folder_private WHERE Key_name LIKE '%unique%';

-- 步骤2: 删除公共文件表的唯一索引
ALTER TABLE spug_document_file_public DROP INDEX unique_file_name_folder_public;

-- 步骤3: 删除私有文件表的唯一索引（如果存在）
-- ALTER TABLE spug_document_file_private DROP INDEX unique_file_name_folder_private;

-- 步骤4: 删除公共文件夹表的唯一索引（可选，如果也支持同名文件夹）
-- ALTER TABLE spug_document_folder_public DROP INDEX unique_folder_name_parent_public;

-- 步骤5: 删除私有文件夹表的唯一索引（可选）
-- ALTER TABLE spug_document_folder_private DROP INDEX unique_folder_name_parent_private;

-- 步骤6: 验证删除成功
SHOW INDEX FROM spug_document_file_public WHERE Key_name LIKE '%unique%';
SHOW INDEX FROM spug_document_file_private WHERE Key_name LIKE '%unique%';

-- 步骤7: （可选）添加普通索引优化查询性能
-- CREATE INDEX idx_file_folder_created ON spug_document_file_public(folder_id, created_at);
-- CREATE INDEX idx_file_folder_created ON spug_document_file_private(folder_id, created_at);

-- 回滚方案（如需恢复唯一索引）
-- ALTER TABLE spug_document_file_public ADD CONSTRAINT unique_file_name_folder_public UNIQUE (name, folder_id);
-- ALTER TABLE spug_document_file_private ADD CONSTRAINT unique_file_name_folder_private UNIQUE (name, folder_id);

# 文档管理模块租户隔离 - 使用指南

## 📋 目录
1. [快速开始](#快速开始)
2. [自动化测试](#自动化测试)
3. [数据库索引优化](#数据库索引优化)
4. [审计日志查看](#审计日志查看)
5. [问题排查](#问题排查)

---

## 🚀 快速开始

### 前置条件

1. **已修复的安全漏洞**
   - ✅ 递归查询租户过滤
   - ✅ 所有关键接口审计日志
   - ✅ 租户过滤告警机制

2. **测试账号准备**
   - 租户A账号：`tenant_a` / `123456`
   - 租户B账号：`tenant_b` / `123456`
   - 超级管理员账号：`admin`

3. **数据库准备**
   - 确认数据库连接正常
   - 确认租户隔离表已创建

---

## 🧪 自动化测试

### 方法1：使用Python脚本（推荐）

```bash
# 进入测试目录
cd tests

# 运行自动化测试
python automated_tenant_isolation_test.py
```

**预期输出**：
```
[2026-02-28 14:00:00] [INFO] 🚀 开始文档管理模块租户隔离测试
[2026-02-28 14:00:01] [INFO] 📝 步骤1：登录测试账号
[2026-02-28 14:00:02] [SUCCESS] ✅ tenant_a 登录成功
[2026-02-28 14:00:03] [SUCCESS] ✅ tenant_b 登录成功
[2026-02-28 14:00:04] [INFO] 📝 步骤2：创建测试数据
[2026-02-28 14:00:05] [SUCCESS] ✅ tenant_a 创建文件成功
[2026-02-28 14:00:06] [INFO] 📝 步骤3：执行安全测试
[2026-02-28 14:00:07] [PASS] ✅ 通过 | 测试1：跨租户下载文件
...
```

**测试覆盖**：
- ✅ 跨租户文件下载
- ✅ 跨租户文件删除
- ✅ 跨租户文件夹删除
- ✅ 公共空间权限校验

### 方法2：手动测试

参考 `tests/租户隔离测试指南.md`，执行10个完整测试用例。

---

## 📊 数据库索引优化

### 执行索引创建

```bash
# 连接到MySQL数据库
mysql -u root -p spug

# 执行索引创建脚本
source scripts/add_document_tenant_indexes.sql
```

**预期输出**：
```
✅ 索引 idx_doc_folder_private_tenant 创建成功
✅ 索引 idx_doc_folder_private_tenant_parent 创建成功
✅ 索引 idx_doc_file_private_tenant 创建成功
...
```

### 验证索引

```sql
-- 查看已创建的索引
SELECT
    table_name AS '表名',
    index_name AS '索引名',
    column_name AS '列名',
    index_type AS '类型'
FROM INFORMATION_SCHEMA.STATISTICS
WHERE table_schema = DATABASE()
  AND table_name LIKE 'spug_document_%'
  AND index_name LIKE 'idx_doc_%'
ORDER BY table_name, index_name, seq_in_index;
```

### 性能对比

**索引创建前**（无租户索引）：
```sql
-- 查询计划（可能全表扫描）
EXPLAIN SELECT * FROM spug_document_file_private
WHERE tenant_id = 'tenant_a' AND folder_id = 101;

-- 输出：type=ALL（全表扫描）
```

**索引创建后**（有租户索引）：
```sql
-- 查询计划（使用索引）
EXPLAIN SELECT * FROM spug_document_file_private
WHERE tenant_id = 'tenant_a' AND folder_id = 101;

-- 输出：type=ref（索引查找）
```

**性能提升预期**：
- 小表（< 1000条）：50-70% 提升
- 中表（1000-10000条）：70-85% 提升
- 大表（> 10000条）：85-95% 提升

---

## 📝 审计日志查看

### 日志位置

Django日志默认位置（根据 `settings.py` 配置）：
- 开发环境：控制台输出
- 生产环境：`logs/spug.log` 或 `/var/log/spug/`

### 日志格式

```
[TenantAudit] Action=FILE_DELETE, User=tenant_a, Tenant=tenant_a, IsPublic=false, Type=FILE, ID=1001, file_name=test.txt
```

### 查询审计日志

#### 查看所有文件操作
```bash
grep "\[TenantAudit\]" logs/spug.log | grep "Type=FILE"
```

#### 查看某个用户的操作
```bash
grep "\[TenantAudit\]" logs/spug.log | grep "User=tenant_a"
```

#### 查看告警（潜在越权尝试）
```bash
grep "潜在越权拦截" logs/spug.log
```

#### 导出为CSV（便于分析）
```bash
grep "\[TenantAudit\]" logs/spug.log | \
  sed 's/.*Action=/Action,/;s/, User=/,User=/;s/, Tenant=/,Tenant=/;s/, IsPublic=/,IsPublic=/;s/, Type=/,Type=/;s/, ID=/,ID=/' | \
  cut -d',' -f1-7 > audit_log.csv
```

### 日志告警说明

**正常操作**：
```
[TENANT FILTER] 用户 tenant_a (租户:tenant_a) - 过滤前:5, 过滤后:5
```

**潜在越权尝试**：
```
[TENANT FILTER] ⚠️ 潜在越权拦截！用户=tenant_b, 租户=tenant_b, 拦截记录数=5, 过滤后=0
```

**处理建议**：
1. 立即检查该用户的行为
2. 确认是否有配置错误
3. 必要时封禁可疑账号

---

## 🔍 问题排查

### 问题1：测试失败 - 租户B能下载租户A的文件

**可能原因**：
1. `apply_tenant_filter` 未正确调用
2. 数据库中文件的 `tenant_id` 字段为空
3. 使用了错误的模型（公共而非私有）

**排查步骤**：

1. 检查数据库记录
```sql
SELECT id, name, tenant_id, created_by_id
FROM spug_document_file_private
WHERE id = 1001;
```
2. 检查日志
```bash
grep "Download.*id:1001" logs/spug.log
```
3. 检查代码是否调用 `apply_tenant_filter`

**修复方案**：
- 确认所有查询都调用了 `apply_tenant_filter`
- 补充缺失租户ID的记录
- 更新测试账号的 `tenant_id` 字段

### 问题2：性能测试慢（响应时间 > 2s）

**可能原因**：
1. 索引未创建
2. 索引未生效
3. 统计信息过时

**排查步骤**：

1. 检查索引是否存在
```sql
SHOW INDEX FROM spug_document_file_private;
```

2. 使用 EXPLAIN 分析查询
```sql
EXPLAIN SELECT * FROM spug_document_file_private
WHERE tenant_id = 'tenant_a' AND folder_id = 101;
```

3. 更新统计信息
```sql
ANALYZE TABLE spug_document_file_private;
ANALYZE TABLE spug_document_folder_private;
```

**修复方案**：
- 重新创建索引
- 重启数据库（让索引生效）
- 定期执行 `ANALYZE TABLE`

### 问题3：审计日志缺失

**可能原因**：
1. `log_operation()` 函数未调用
2. 日志级别配置错误
3. 日志文件权限问题

**排查步骤**：

1. 搜索审计日志
```bash
grep "\[TenantAudit\]" logs/spug.log | wc -l
```

2. 检查日志配置
```python
# settings.py
LOGGING = {
    'version': 1,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/spug.log',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
        },
    },
}
```

**修复方案**：
- 确认关键接口调用了 `log_operation()`
- 调整日志级别为 INFO 或 DEBUG
- 检查日志文件目录权限

### 问题4：索引创建失败

**可能原因**：
1. 数据库版本不支持存储过程
2. 权限不足
3. 索引名称冲突

**排查步骤**：

1. 检查数据库版本
```sql
SELECT VERSION();
```

2. 检查用户权限
```sql
SHOW GRANTS FOR CURRENT_USER;
```

3. 检查索引是否存在
```sql
SELECT * FROM INFORMATION_SCHEMA.STATISTICS
WHERE table_schema = DATABASE()
  AND index_name = 'idx_doc_file_private_tenant';
```

**修复方案**：
- MySQL < 8.0：删除存储过程，直接执行 CREATE INDEX
- 权限问题：使用 root 账号或授予 INDEX 权限
- 索引冲突：先删除已存在的索引

---

## 📚 相关文档

- `tests/租户隔离测试指南.md` - 完整的手动测试用例
- `tests/automated_tenant_isolation_test.py` - 自动化测试脚本
- `scripts/add_document_tenant_indexes.sql` - 数据库索引优化脚本

---

## 📞 支持与反馈

如遇到问题，请检查：
1. Django 日志：`logs/spug.log`
2. 数据库日志：`/var/log/mysql/error.log`
3. 测试脚本输出

---

## ✅ 验证清单

部署前请确认：

- [ ] 所有租户接口都调用了 `apply_tenant_filter`
- [ ] 递归查询都显式传递了租户过滤
- [ ] 关键操作都调用了 `log_operation()`
- [ ] 数据库索引已创建
- [ ] 所有安全测试通过
- [ ] 审计日志正常输出
- [ ] 告警机制正常工作

---

**最后更新**：2026-02-28
**版本**：1.0

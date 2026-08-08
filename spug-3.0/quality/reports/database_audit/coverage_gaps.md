# 覆盖缺口说明

## 未验证项目

### 1. 生产数据库状态
- **原因**: 仅连接 dev 库（tdyw-test 容器），未连接生产数据库
- **影响**: 生产库的表结构、索引状态、数据质量可能与 dev 库不同
- **建议**: 如需审计生产库，需单独授权并使用只读副本

### 2. 物理文件一致性
- **原因**: 本次仅做数据库层面检查，未访问文件系统
- **影响**: 无法确认物理文件与数据库记录是否一一对应
- **建议**: 后续补充文件系统审计（`is_pending_clean` 已确认为 0，风险低）

### 3. Role.page_perms 内容分析
- **原因**: 未导出 TextField 内容做权限编码文本分析
- **影响**: 无法确认角色是否引用已删除模块的权限编码
- **建议**: 后续导出 Role.page_perms 做文本匹配

### 4. EXPLAIN 执行计划
- **原因**: 未对高频查询执行 EXPLAIN 验证索引使用
- **影响**: 无法确认索引是否被查询优化器实际使用
- **建议**: 后续对关键查询补充 EXPLAIN 分析

### 5. 数据库视图和触发器
- **原因**: 未检查是否存在数据库视图或触发器
- **影响**: 可能有遗留的视图/触发器引用已删除表
- **建议**: 后续检查 `information_schema.VIEWS` 和 `information_schema.TRIGGERS`

### 6. django_celery_beat_crontabschedule 等框架表
- **原因**: 属于 Celery 框架，非业务模块
- **影响**: 不影响业务功能
- **建议**: 无需处理

### 7. 统计数据精确性
- **原因**: `TABLE_ROWS` 为 MariaDB 估计值
- **影响**: 行数为近似值
- **建议**: 如需精确值，使用 `SELECT COUNT(*)`

## 已验证项目

- ✅ 72 张表的表结构（SHOW CREATE TABLE + information_schema.COLUMNS）
- ✅ 216 条迁移记录全部已应用
- ✅ 268 条权限记录无 schedule 残留
- ✅ 67 条 Content Type 无 schedule 残留
- ✅ 42 条外键关系无孤儿数据
- ✅ 所有含 tenant_id 的表无 NULL 租户数据
- ✅ 所有含 is_pending_clean 的表无堆积
- ✅ DateTimeField 查询模式（__date/__year/__month/__startswith/__icontains）
- ✅ raw SQL 使用（.raw() / cursor.execute()）
- ✅ select_for_update 使用情况
- ✅ schedule 模块数据库残留（表/迁移/权限/Content Type/代码引用）

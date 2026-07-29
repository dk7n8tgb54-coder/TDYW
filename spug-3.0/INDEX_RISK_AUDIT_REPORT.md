# 索引与慢查询风险排查报告

> 依据《CRUD 系统可靠性工程实践指南》2.1 索引与慢查询治理
> 排查时间：2026-07-29
> 验证环境：tdyw-test 容器（MariaDB 10.8.2）

## 一、风险点排查汇总表

| 编号 | 风险等级 | 模块 | 位置 | 风险描述 | 现有索引 | EXPLAIN 结论 |
|:---:|:---:|:---:|:---|:---|:---|:---:|
| R1 | 高 | fault | `fault/exporters.py:46` | `fault_date__icontains` 在 DateTimeField 上，生成 `CAST(col AS CHAR) LIKE '%xxx%'`，绕过 fault_date 索引 | `fault_rec_t_date_idx(tenant_id, -fault_date, -id)` | PARTIAL |
| R2 | **严重** | department_duty_log | `services.py:302` | `duty_date__year` + `duty_date__month` 翻译为 `YEAR(col)=N AND MONTH(col)=N`，函数绕过索引 | `duty_date_idx(status, deleted_at, duty_date)` | **CONFIRMED** |
| R3 | 高 | upgrade | `statistics_service.py:82` | `.extra({'date': 'DATE(upgrade_time)'})` 在 DateTimeField 上用 DATE() 函数，绕过 upgrade_time 索引位置；产生 `Using temporary; Using filesort` | `upg_rec_time_idx(tenant_id, upgrade_time, id)` | PARTIAL |
| R4a | 中 | runlog | `views.py:93` | `system_name__icontains` 在无索引 CharField 上，`LIKE '%xxx%'` 无法走索引 | 无 system_name 索引 | PARTIAL |
| R4b | 中 | interference | `views.py` | `frequency__icontains` 在无索引 CharField 上 | 无 frequency 索引 | PARTIAL |
| R4c | 中 | device | `views.py:69` | `device_name__icontains` 在无索引 CharField 上 | 无 device_name 索引 | PARTIAL |
| R4d | 中 | logs | `views.py` | `target_name__icontains` 在无索引 CharField 上 | 无 target_name 索引 | PARTIAL |
| R5 | 中 | fault | `views.py:20` | 分页前对全量数据做 `.values('system_name').distinct()`，每次列表请求触发全量 DISTINCT | 有 tenant_id 索引 | PARTIAL |
| R6 | 中 | runlog | `views.py:985` | 证据包视图 `AuditLog.filter(target_type='runlog')` 无日期范围限制、无分页 | 有 target_type 索引 | PARTIAL |
| R7 | 中 | device | `views.py:640` | 设备履历导出 `DeviceResume.filter(device_sn=...)` 无行数上限，全量导出 | 有 tenant_id+device_sn 索引 | PARTIAL |
| R8 | 低 | runlog | `views.py:496` | `RunLogRepairView` 用 `RunLog.objects.all()` 遍历全量记录（仅管理员触发） | 有 tenant_id 索引 | PARTIAL |
| R9 | **严重** | department_duty_log | `services.py:335` | `duty_record__icontains` 在 TextField 上，`LIKE '%xxx%'` 全表扫描 | 无 duty_record 索引 | **CONFIRMED** |
| R10 | 中 | device | `views.py:787` | 证据包 fallback 分支：`AuditLog.filter(target_type='device')` 无 target_id 过滤，无界查询 | 有 target_type 索引 | PARTIAL |
| R11 | **严重** | department_duty_log | `models.py` Meta.indexes | 复合索引 `['status', 'deleted_at', 'duty_date']` 违反最左前缀原则：大多数查询按 `duty_date` 过滤但不按 `status` 过滤，导致索引完全不可用 | `duty_date_idx(status, deleted_at, duty_date)` | **CONFIRMED** |

---

## 二、EXPLAIN 测试验证结果

### 测试环境
- 容器：`tdyw-test`（镜像 tdyw:django42-stage2，bind mount）
- 数据库：MariaDB 10.8.2（dev 库）
- 脚本：`explain_test.py`，对每个风险点生成 ORM 查询并执行 `EXPLAIN`

### 结果汇总

```
ID         状态           全表扫描    有索引     Using where  标题
----------------------------------------------------------------------------------------------------
R1         PARTIAL      否          是          是            fault_date__icontains 在 DateTimeField
R1-对照    PARTIAL      否          是          否            fault_date__gte/__lt 正确写法
R2         CONFIRMED    是          否          是            duty_date__year+__month 绕过索引
R2-对照    CONFIRMED    是          否          是            duty_date__gte/__lt 正确写法（仍全表扫描！）
R3         PARTIAL      否          是          是            .extra(DATE(upgrade_time)) 绕过索引
R4a        PARTIAL      否          是          是            RunLog.system_name__icontains 无索引
R4b        PARTIAL      否          是          是            Interference.frequency__icontains 无索引
R4c        PARTIAL      否          是          是            DeviceResume.device_name__icontains 无索引
R4d        PARTIAL      否          是          是            AuditLog.target_name__icontains 无索引
R5         PARTIAL      否          是          是            分页前无界 DISTINCT
R6         PARTIAL      否          是          是            证据包无界审计日志查询
R8         PARTIAL      否          是          是            RunLogRepairView 遍历全部记录
R9         CONFIRMED    是          否          是            TextField __icontains 全表扫描
R10        PARTIAL      否          是          是            设备证据包 fallback 无界审计日志

总计: 14 个测试
  CONFIRMED (已确认风险): 3
  PARTIAL (部分风险): 11
```

### 状态定义

| 状态 | 含义 |
|:---:|:---|
| **CONFIRMED** | `EXPLAIN` 显示 `type=ALL`（全表扫描）且 `key=NULL`（无索引），风险已确认 |
| **PARTIAL** | 索引被部分使用（通常仅 `tenant_id` 走索引），但目标列的过滤条件仍做 `Using where` 全行扫描 |
| **NOT_CONFIRMED** | 索引正常使用，无风险 |

---

## 三、关键发现详解

### 3.1 R2 + R11（严重）：DepartmentDutyLog 索引设计缺陷

**现象**：无论用 `__year/__month` 还是 `__gte/__lt`，EXPLAIN 都是 `type=ALL, key=None`（全表扫描）。

**根因**：复合索引 `duty_date_idx(status, deleted_at, duty_date)` 的最左列是 `status`，但绝大多数查询直接按 `duty_date` 过滤，不按 `status` 过滤。根据 B+Tree 最左前缀原则，跳过 `status` 列时索引完全不可用。

**EXPLAIN 对比**：
```
R2  (__year/__month):  type=ALL  key=None  rows=2  Extra=Using where; Using filesort
R2-对照 (__gte/__lt):  type=ALL  key=None  rows=2  Extra=Using where; Using filesort
```

**修复建议**：
1. 新增独立索引 `Index(fields=['duty_date'])` 或 `Index(fields=['-duty_date', '-id'])`
2. `services.py:302` 将 `duty_date__year` + `duty_date__month` 改为 `duty_date__gte` + `duty_date__lt`

### 3.2 R9（严重）：TextField 全表扫描

**现象**：`duty_record__icontains` 在 TextField 上，EXPLAIN 显示 `type=ALL, key=None`。

**根因**：TextField 无索引，`LIKE '%xxx%'` 本身也无法使用索引（即使有索引，前缀通配符 `%` 也会导致全扫描）。

**修复建议**：
- 数据量大时考虑全文索引（MySQL FULLTEXT INDEX）
- 数据量不大时可接受，但应在 `services.py` 中增加查询结果行数上限

### 3.3 R1（高）：icontains 在 DateTimeField 上

**现象**：`fault_date__icontains='2025'` 生成 `CAST(fault_date AS CHAR) LIKE '%2025%'`。

**EXPLAIN 对比**：
```
R1     (icontains):   type=ref    key=fault_rec_t_date_idx  Extra=Using index condition; Using where
R1-对照 (__gte/__lt): type=range  key=fault_rec_t_date_idx  Extra=Using index condition
```

**分析**：
- 两种写法都用了索引（因 `tenant_id` 在复合索引首位），但：
  - `icontains`：`type=ref`（等值匹配 tenant_id），然后 `Using where` 逐行做 CAST+LIKE 过滤
  - `__gte/__lt`：`type=range`（范围扫描 tenant_id+fault_date），无需 Using where
- `type=range` 比 `type=ref + Using where` 更高效，尤其在数据量大时差异显著

**修复建议**：`fault/exporters.py:46` 将 `fault_date__icontains` 改为日期范围查询

### 3.4 R3（高）：extra(DATE()) 函数绕过索引

**现象**：`.extra({'date': 'DATE(upgrade_time)'})` 生成 `GROUP BY DATE(upgrade_time)`。

**EXPLAIN**：
```
type=ref  key=upg_rec_time_idx  Extra=Using where; Using index; Using temporary; Using filesort
```

**分析**：
- `tenant_id` 走了索引，但 `DATE(upgrade_time)` 函数绕过了 `upgrade_time` 在复合索引中的位置
- `Using temporary; Using filesort` 说明需要创建临时表和排序，数据量大时内存/磁盘开销显著

**修复建议**：用 `__gte`/`__lt` 按日期分组循环查询，或用 `__date` 查询（虽然 `__date` 也绕过索引，但至少不产生 `Using temporary`）

### 3.5 R4a-d（中）：icontains 在无索引 CharField 上

**现象**：多个模块的列表查询使用 `__icontains` 在无索引的 CharField 上。

**分析**：
- 索引仅用于 `tenant_id` 过滤（缩小范围），`icontains` 仍做 `Using where` 逐行 LIKE
- 在租户数据量不大时影响有限，但随着数据增长会逐渐恶化
- `LIKE '%xxx%'` 的前缀通配符使得即使添加 B-Tree 索引也无法使用

**修复建议**：
- 高频搜索字段考虑迁移到 Elasticsearch 或 MySQL FULLTEXT
- 低频搜索可接受现状，但应增加查询结果行数上限

### 3.6 R5（中）：分页前无界 DISTINCT

**现象**：`fault/views.py:20` 每次列表请求都执行 `records.order_by('system_name').values('system_name').distinct()` 获取下拉选项。

**分析**：
- 虽然有 `tenant_id` 索引，但 DISTINCT 需要对全量数据排序去重
- 每次列表请求都触发，属于 N+1 查询模式的变体

**修复建议**：将系统名称下拉选项缓存到 Redis（TTL 5 分钟），避免每次请求都做 DISTINCT

### 3.7 R6/R10（中）：无界审计日志查询

**现象**：证据包视图中 `AuditLog.filter(target_type='...')` 无日期范围限制、无分页。

**分析**：
- 有 `target_type` 索引，但单个 target_type 下的日志可能非常多
- `device/views.py:787` 的 fallback 分支甚至不按 `target_id` 过滤，查全部设备日志

**修复建议**：增加 `created_at__gte` 日期范围限制（如最近 90 天），并加分页

---

## 四、修复优先级

| 优先级 | 编号 | 修复内容 | 预计工作量 |
|:---:|:---:|:---|:---:|
| P0 | R2+R11 | DepartmentDutyLog 新增 `duty_date` 索引 + 改 `__year/__month` 为 `__gte/__lt` | 1 个 migration + 3 行代码 |
| P1 | R1 | `fault/exporters.py` 改 `fault_date__icontains` 为日期范围查询 | 5 行代码 |
| P1 | R3 | `upgrade/statistics_service.py` 改 `.extra(DATE())` 为按日期循环查询 | 15 行代码 |
| P2 | R6+R10 | 证据包视图增加审计日志日期范围限制 | 10 行代码 |
| P2 | R5 | 系统名称下拉选项加 Redis 缓存 | 20 行代码 |
| P3 | R4a-d | 高频搜索字段评估全文索引方案 | 需调研 |
| P3 | R7 | 设备履历导出增加行数上限 | 3 行代码 |
| P3 | R9 | TextField 搜索增加结果行数上限 | 3 行代码 |
| P4 | R8 | RunLogRepairView 增加分页（仅管理员触发） | 10 行代码 |

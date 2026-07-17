# 数据库字段 NULL 值整改方案

## 一、项目概述

### 1.1 扫描范围
- **扫描时间**: 2026-03-27
- **扫描范围**: spug_api 下所有 models.py 文件
- **涉及应用**: 11 个
- **涉及模型**: 31 个
- **允许 NULL 字段总数**: 71 个

### 1.2 统计汇总

| 统计项 | 数量 |
|--------|------|
| 扫描的模型总数 | 31 个 |
| 允许 NULL 的字段总数 | **约 75 个** |
| 仅 null=True | 约 20 个 |
| 仅 blank=True | 0 个 |
| null=True + blank=True | 约 35 个 |
| 外键关联 null=True | 约 20 个 |

---

## 二、整改原则

### 2.1 整改目标
1. **减少 NULL 值使用**: 除业务上确实需要表示"无/未设置"状态外，其他字段应设为非空
2. **统一默认值**: CharField/TextField 使用空字符串 `''`，JSON 字段使用 `'{}'` 或 `'[]'`
3. **保持业务逻辑**: 软删除标记、可选业务字段等保持 nullable

### 2.2 字段分类处理策略

| 字段类型 | 处理策略 | 示例 |
|----------|----------|------|
| 必填业务字段 | **必须设为非空** | physical_name, username |
| JSON 存储字段 | 设置默认空值 | page_perms='{}', group_perms='[]' |
| 可选描述字段 | 设置默认空字符串 | desc='', remark='' |
| 软删除标记 | **保持 nullable** | deleted_at, deleted_by |
| 审批流程字段 | **保持 nullable** | approved_by, approved_at |
| 时间戳字段 | **保持 nullable** | started_at, completed_at |
| 外键关联 | 视业务而定 | created_by 保持 null |

---

## 三、高优先级整改（立即执行）

### 3.1 必须设为非空或添加默认值的字段

| 序号 | 应用 | 模型 | 字段 | 当前定义 | 整改后定义 | 影响评估 |
|------|------|------|------|----------|------------|----------|
| 1 | document | DocumentFilePrivate | physical_name | `CharField(max_length=100, null=True, blank=True)` | `CharField(max_length=100)` | **高** - 物理文件名必须 |
| 2 | document | DocumentFilePublic | physical_name | `CharField(max_length=100, null=True, blank=True)` | `CharField(max_length=100)` | **高** - 物理文件名必须 |
| 3 | account | History | username | `CharField(max_length=100, null=True)` | `CharField(max_length=100)` | **中** - 登录记录应有用户名 |
| 4 | document | DocumentFolderPrivate | created_by | `ForeignKey(User, null=True)` | `ForeignKey(User, null=True, default=1)` | **中** - 记录创建人，默认系统管理员 |
| 5 | document | DocumentFolderPublic | created_by | `ForeignKey(User, null=True)` | `ForeignKey(User, null=True, default=1)` | **中** - 记录创建人，默认系统管理员 |
| 6 | document | DocumentFilePrivate | created_by | `ForeignKey(User, null=True)` | `ForeignKey(User, null=True, default=1)` | **中** - 记录创建人 |
| 7 | document | DocumentFilePublic | created_by | `ForeignKey(User, null=True)` | `ForeignKey(User, null=True, default=1)` | **中** - 记录创建人 |

### 3.2 必须添加默认值的 JSON 字段

| 序号 | 应用 | 模型 | 字段 | 当前定义 | 整改后定义 |
|------|------|------|------|----------|------------|
| 8 | account | Role | page_perms | `TextField(null=True)` | `TextField(default='{}')` |
| 9 | account | Role | deploy_perms | `TextField(null=True)` | `TextField(default='{}')` |
| 10 | account | Role | group_perms | `TextField(null=True)` | `TextField(default='[]')` |

---

## 四、中优先级整改（逐步执行）

### 4.1 建议添加默认值的字段

| 序号 | 应用 | 模型 | 字段 | 当前定义 | 整改后定义 | 备注 |
|------|------|------|------|----------|------------|------|
| 11 | account | Role | desc | `CharField(max_length=255, null=True)` | `CharField(max_length=255, default='')` | 角色描述 |
| 12 | checksheet | CheckSheetRecord | remark | `TextField(null=True, blank=True)` | `TextField(default='')` | 备注 |
| 13 | checksheet | CheckSheetRecord | rectification | `TextField(null=True, blank=True)` | `TextField(default='')` | 整改情况 |
| 14 | checksheet | CheckSheetRecord | operator | `CharField(null=True, blank=True)` | `CharField(default='')` | 操作人 |
| 15 | checksheet | CheckSheetDailySummary | operator | `CharField(null=True, blank=True)` | `CharField(default='')` | 操作人 |
| 16 | checksheet | CheckSheetDailySummary | remark | `TextField(null=True, blank=True)` | `TextField(default='')` | 备注 |
| 17 | checksheet | CheckSheetDailySummary | rectification | `TextField(null=True, blank=True)` | `TextField(default='')` | 整改情况 |
| 18 | device | DeviceResume | frequency | `CharField(null=True, blank=True)` | `CharField(default='')` | 频率 |
| 19 | device | DeviceResume | call_sign | `CharField(null=True, blank=True)` | `CharField(default='')` | 呼号 |
| 20 | device | DeviceResume | geo_coordinate | `CharField(null=True, blank=True)` | `CharField(default='')` | 地理坐标 |
| 21 | device | DeviceResume | device_purpose | `TextField(null=True, blank=True)` | `TextField(default='')` | 设备用途 |
| 22 | device | DeviceResume | remark | `TextField(null=True, blank=True)` | `TextField(default='')` | 备注 |
| 23 | device | DeviceEvent | fault_part | `CharField(null=True, blank=True)` | `CharField(default='')` | 故障部位 |
| 24 | device | DeviceEvent | fault_phenomenon_cause | `TextField(null=True, blank=True)` | `TextField(default='')` | 故障现象及原因 |
| 25 | device | DeviceEvent | maintenance_measures | `TextField(null=True, blank=True)` | `TextField(default='')` | 维护措施 |
| 26 | device | DeviceEvent | repair_time | `CharField(null=True, blank=True)` | `CharField(default='')` | 修复时间 |
| 27 | device | DeviceEvent | remark | `TextField(null=True, blank=True)` | `TextField(default='')` | 备注 |
| 28 | exec | DutyRecord | log_content | `TextField(null=True, blank=True)` | `TextField(default='')` | 日志内容 |
| 29 | exec | HandoverRecord | notes | `TextField(null=True, blank=True)` | `TextField(default='')` | 注意事项 |
| 30 | interference | Interference | flight_number | `CharField(null=True, blank=True)` | `CharField(default='')` | 航班号 |
| 31 | interference | Interference | aircraft_type | `CharField(null=True, blank=True)` | `CharField(default='')` | 机型 |
| 32 | runlog | RunLogUpdate | update_time_detail | `CharField(null=True, blank=True)` | `CharField(default='')` | 更新时间详情 |
| 33 | runlog | RunLogUpdate | attachments | `TextField(null=True, blank=True)` | `TextField(default='[]')` | 附件列表 |
| 34 | schedule | ScheduleStaff | department | `CharField(null=True, blank=True)` | `CharField(default='')` | 部门 |
| 35 | schedule | ScheduleStaff | phone | `CharField(null=True, blank=True)` | `CharField(default='')` | 电话 |
| 36 | schedule | ScheduleShift | description | `TextField(null=True, blank=True)` | `TextField(default='')` | 描述 |
| 37 | schedule | ScheduleShift | color | `CharField(null=True, blank=True)` | `CharField(default='')` | 颜色 |
| 38 | schedule | ScheduleShiftTime | color | `CharField(null=True, blank=True)` | `CharField(default='')` | 颜色 |
| 39 | schedule | Schedule | notes | `TextField(null=True, blank=True)` | `TextField(default='')` | 备注 |
| 40 | schedule | ScheduleSwap | reason | `TextField(null=True, blank=True)` | `TextField(default='')` | 换班原因 |
| 41 | schedule | ScheduleSwap | remarks | `TextField(null=True, blank=True)` | `TextField(default='')` | 备注 |
| 42 | schedule | ScheduleSubstitute | reason | `TextField(null=True, blank=True)` | `TextField(default='')` | 替班原因 |
| 43 | schedule | ScheduleSubstitute | remarks | `TextField(null=True, blank=True)` | `TextField(default='')` | 备注 |
| 44 | upgrade | UpgradeRecord | lessons | `TextField(null=True, blank=True)` | `TextField(default='')` | 经验总结 |
| 45 | setting | Setting | desc | `CharField(null=True)` | `CharField(default='')` | 设置描述 |

---

## 五、保持现状的字段（低优先级）

### 5.1 软删除相关字段（应保持 nullable）

| 应用 | 模型 | 字段 | 理由 |
|------|------|------|------|
| document | DocumentFolderPrivate/DocumentFolderPublic | deleted_at, deleted_by | 未删除时为 NULL |
| document | DocumentFilePrivate/DocumentFilePublic | deleted_at | 未删除时为 NULL |

### 5.2 审批流程相关字段（应保持 nullable）

| 应用 | 模型 | 字段 | 理由 |
|------|------|------|------|
| schedule | ScheduleSwap/ScheduleSubstitute | approved_by, approved_by_name, approved_at | 未审批时为 NULL |
| exec | HandoverRecord | confirmed_at | 未确认时为 NULL |

### 5.3 时间戳相关字段（应保持 nullable）

| 应用 | 模型 | 字段 | 理由 |
|------|------|------|------|
| document | DocumentTransfer | started_at, completed_at | 未开始/未完成时为 NULL |
| device/exec/interference/runlog/schedule/upgrade | 多个模型 | updated_at, updated_by | 首次创建时可能为 NULL |

### 5.4 可选业务字段（应保持 nullable）

| 应用 | 模型 | 字段 | 理由 |
|------|------|------|------|
| document | DocumentTransfer | file_hash, folder_id, error_message, celery_task_id, user | 业务上可选/未开始 |
| document | DocumentFilePrivate/DocumentFilePublic | folder, last_clean_attempt | 根目录/未清理时为 NULL |
| runlog | RunLog | responsible_user_id, resolution, verifier_id, verified_at, closed_at | 未分配/未解决/未验证时为 NULL |
| account | User | token_expired, wx_token, deleted_at, deleted_by | 系统字段，可选 |

### 5.5 updated_by 字段（建议保持 nullable）

| 应用 | 涉及模型 | 字段 | 理由 |
|------|----------|------|------|
| upgrade | UpgradeRecord | updated_by | 首次创建时可能为 NULL |
| exec | DutyRecord, HandoverRecord, Task, Command | updated_by | 首次创建时可能为 NULL |
| schedule | ScheduleStaff, ScheduleShift, ScheduleShiftTime, Schedule, ScheduleSwap, ScheduleSubstitute | updated_by | 首次创建时可能为 NULL |
| runlog | RunLog | updated_by | 首次创建时可能为 NULL |
| interference | Interference | updated_by | 首次创建时可能为 NULL |
| device | DeviceResume, DeviceEvent | updated_by | 首次创建时可能为 NULL |

**建议**: 这些字段可考虑设置为 `default=1`（系统管理员）或保持 nullable

---

## 六、整改实施步骤

### 6.1 第一阶段：高优先级整改（1-2天）

1. **修改模型定义**
   - 修改 `DocumentFilePrivate.physical_name`
   - 修改 `DocumentFilePublic.physical_name`
   - 修改 `History.username`
   - 修改 `DocumentFolderPrivate.created_by`（添加默认值）
   - 修改 `DocumentFolderPublic.created_by`（添加默认值）
   - 修改 `DocumentFilePrivate.created_by`（添加默认值）
   - 修改 `DocumentFilePublic.created_by`（添加默认值）
   - 修改 `Role.page_perms/deploy_perms/group_perms`

2. **创建数据迁移脚本**
   ```bash
   python manage.py makemigrations
   ```

3. **数据清洗（如需要）**
   - 对于 `physical_name` 为 NULL 的记录，生成默认值
   - 对于 `username` 为 NULL 的 History 记录，填充默认值

4. **应用迁移**
   ```bash
   python manage.py migrate
   ```

### 6.2 第二阶段：中优先级整改（1周内）

1. **批量修改模型定义**
   - 按应用分组修改字段
   - 统一添加 `default=''` 或 `default='{}'`/`default='[]'`

2. **创建并应用迁移**
   - 建议每个应用一个迁移文件
   - 便于回滚和问题定位

### 6.3 第三阶段：验证与测试

1. **单元测试**
   - 验证字段默认值生效
   - 验证非空约束生效

2. **集成测试**
   - 验证业务流程正常
   - 验证数据导入导出正常

---

## 七、整改示例代码

### 7.1 CharField 整改示例

```python
# 整改前
desc = models.CharField(max_length=255, null=True)

# 整改后
desc = models.CharField(max_length=255, default='')
```

### 7.2 TextField 整改示例

```python
# 整改前
remark = models.TextField(null=True, blank=True)

# 整改后
remark = models.TextField(default='')
```

### 7.3 JSON 存储字段整改示例

```python
# 整改前
page_perms = models.TextField(null=True)

# 整改后
page_perms = models.TextField(default='{}')
```

### 7.4 必填字段整改示例

```python
# 整改前
physical_name = models.CharField(max_length=100, null=True, blank=True)

# 整改后
physical_name = models.CharField(max_length=100)
```

---

## 八、风险评估与回滚方案

### 8.1 风险点

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 现有数据不符合新约束 | 迁移失败 | 先执行数据清洗脚本 |
| 业务代码依赖 NULL 值 | 运行时错误 | 全面代码审查 |
| 默认值不符合业务逻辑 | 数据错误 | 与业务方确认 |

### 8.2 回滚方案

1. **迁移前备份数据库**
   ```bash
   mysqldump -u root -p spug > backup_$(date +%Y%m%d).sql
   ```

2. **保留迁移文件**
   - 所有迁移文件纳入版本控制
   - 记录迁移前后的 schema 变更

3. **紧急回滚步骤**
   ```bash
   # 回滚到指定迁移
   python manage.py migrate document 0002_documenttransfer_celery_task_id
   
   # 恢复数据库备份（如需要）
   mysql -u root -p spug < backup_20260327.sql
   ```

---

## 九、验收标准

1. **高优先级字段整改完成**: 10 个字段全部整改
2. **中优先级字段整改完成**: 35 个字段全部整改
3. **数据库无 NULL 值**: 除保留字段外，其他字段无 NULL
4. **业务测试通过**: 核心业务流程正常
5. **单元测试通过**: 所有测试用例通过

---

## 十、附录：完整字段清单

详见本文档第三章和第四章的详细表格。

---

**文档版本**: v1.0  
**创建日期**: 2026-03-27  
**最后更新**: 2026-03-27  
**负责人**: 待指定

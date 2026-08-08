# 未来重构影响评估

## 1. 受影响的 E2E 测试

### 对话 8 Playwright E2E 覆盖

| 模块 | E2E 用例 | 重构影响 | 优先级 |
|---|---|---|---|
| device | 设备列表/详情/创建/编辑/删除 | 字段变更需更新选择器和断言 | 高 |
| device | 设备履历查看 | DeviceEvent IntegerField→FK 后查询方式变更 | 高 |
| fault | 故障列表/创建/编辑/删除 | system_name/device_code→FK 后选择器变更 | 高 |
| fault | 故障部件管理 | FaultPart→FK 后关联方式变更 | 中 |
| upgrade | 升级记录列表/创建 | system→FK 后选择器变更 | 高 |
| upgrade | 系统候选项管理 | UpgradeSystem→全局主数据后管理方式变更 | 中 |
| interference | 干扰记录列表/创建/编辑 | 字段变更较小 | 低 |
| alert | 告警列表/处理 | 全局数据→租户隔离后需增加租户过滤 | 低 |

### 需要重写的 E2E 用例

1. **设备详情页面履历展示** - 依赖 DeviceEvent.device_resume_id（IntegerField）
2. **故障创建页面设备选择** - 依赖 system_name/device_code 文本关联
3. **升级记录创建页面系统选择** - 依赖 system 文本字段
4. **告警列表页面** - 依赖全局数据设计（无 tenant_id）

## 2. 受影响的 API 接口

| 接口 | 变更类型 | 影响 |
|---|---|---|
| GET /device/device-resume/ | 字段可能变更 | 前端需更新 |
| POST /device/device-resume/ | 必填字段可能变更 | 前端需更新 |
| PUT /device/device-resume/ | CHECK 约束需修复 | 当前已有缺陷 |
| GET /device/device-event/ | device_resume_id 可能变为 FK | 前端需更新 |
| GET /fault/faultrecord/ | system_name/device_code 可能变为 FK | 前端需更新 |
| POST /fault/faultrecord/ | 必填字段可能变更 | 前端需更新 |
| GET /upgrade/records/ | system 可能变为 FK | 前端需更新 |
| GET /upgrade/systems/ | 可能变为全局主数据 | 管理方式变更 |
| GET /alert/ | 可能增加 tenant_id | 需确认隔离需求 |

## 3. 受影响的数据库迁移

| 迁移 | 风险 | 建议步骤 |
|---|---|---|
| DeviceEvent.device_resume_id → FK | 高（需数据清洗） | 1. 删孤儿 2. 加约束 3. 改字段类型 |
| FaultRecord 增加设备外键 | 高（需人工映射） | 1. 建映射表 2. 人工确认 3. 加外键 |
| UpgradeRecord.system → FK | 高（需人工映射） | 1. 建映射表 2. 人工确认 3. 加外键 |
| FaultPart 增加故障外键 | 中（需确认关联） | 1. 人工确认 2. 加外键 |
| UpgradeRecordStep.upgrade_id → FK | 中（需数据清洗） | 1. 删孤儿 2. 加约束 |
| Alert 增加 tenant_id | 低（需确认需求） | 1. 确认 2. 加字段 3. 数据迁移 |
| DeviceResume CHECK 约束 | 中（需兼容） | 1. 验证数据 2. 重建约束 |

## 4. 受影响的权限体系

| 变更 | 影响 |
|---|---|
| device.device_resume.* | 保持不变 |
| fault.faultrecord.* | 保持不变 |
| upgrade.upgrade.* | 保持不变 |
| interference.interference.* | 保持不变 |
| system.alert.* | 如增加租户隔离可能需调整 |

## 5. 不受影响的内容

- 租户隔离机制（TenantModelMixin/TenantModelManager）
- 权限缓存机制（User.page_perms）
- 审计日志机制（record_audit_event）
- 附件系统（EvidenceAttachment）
- 软删除机制
- Celery 定时任务

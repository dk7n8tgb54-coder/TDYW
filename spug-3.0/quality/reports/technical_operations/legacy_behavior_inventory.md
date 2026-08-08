# 旧架构行为清单

## 概述

以下行为只是当前旧架构的临时实现方式，不是未来目标架构。重构完成后应逐项删除或转化。

## 1. 设备模块旧架构行为

### 1.1 DeviceResume 当前字段

| 行为 | 描述 | 测试 |
|---|---|---|
| responsible_user_name 是文本 | CharField 存储人名，不是外键到 User | test_device_resume_has_text_responsible_user_name |
| current_status 是 CharField | 存储 '1'-'5' 字符串，不是 IntegerField | test_device_resume_current_status_is_charfield |
| 无资产编号字段 | 不存在 asset_number 或类似字段 | test_device_resume_no_asset_number_field |
| 无系统关系外键 | 没有 system 或 subsystem 的 ForeignKey | test_device_resume_no_system_relationship |

### 1.2 DeviceEvent 当前关联方式

| 行为 | 描述 | 测试 |
|---|---|---|
| device_resume_id 是 IntegerField | 不是 ForeignKey 到 DeviceResume | test_device_event_resume_id_is_integer_field |
| 冗余存储 device_name/device_sn | CharField 文本副本，不自动更新 | test_device_event_has_redundant_text_fields |
| 改设备名后事件不更新 | 事件记录中的旧名称保留 | test_device_rename_doesnt_update_event_text |
| 软删除设备后事件仍存在 | device_resume_id 指向已删除设备 | test_device_soft_delete_preserves_events |
| 事件手工创建 | 创建设备后不自动生成事件 | test_events_are_manually_created |

## 2. 故障模块旧架构行为

### 2.1 FaultRecord 当前字段

| 行为 | 描述 | 测试 |
|---|---|---|
| system_name 是文本 | CharField，不是外键到系统表 | test_system_name_is_text_not_fk |
| device_code 是文本 | CharField，不是外键到设备表 | test_device_code_is_text_not_fk |
| handler 是文本 | CharField 存储人名 | test_handler_is_text_not_fk |
| recorder 是文本 | CharField 存储人名 | test_recorder_is_text_not_fk |
| 无设备外键 | 不存在 device_resume FK | test_no_fk_to_device_resume |
| 改设备编号后故障记录不更新 | 文本引用不会同步 | test_rename_device_doesnt_update_fault_text |

### 2.2 FaultPart 当前关联方式

| 行为 | 描述 | 测试 |
|---|---|---|
| 无外键到 FaultRecord | 独立存在 | test_fault_part_has_no_fk_to_fault_record |
| system_name 是文本 | 与 FaultRecord.system_name 不关联 | test_fault_part_uses_system_name_text |
| 用 name 无资产编号 | 不存在 asset_number | test_fault_part_has_name_not_asset_number |
| 故障不自动写 DeviceEvent | 无自动履历生成 | test_no_auto_device_history_on_fault_create |
| 无部件实例表 | FaultPart 是独立记录 | test_no_part_instance_table |

## 3. 系统升级模块旧架构行为

### 3.1 UpgradeRecord 当前字段

| 行为 | 描述 | 测试 |
|---|---|---|
| system 是文本 | CharField，不关联 UpgradeSystem | test_system_field_is_text_not_fk |
| owner 是文本 | CharField 存储人名 | test_owner_is_text_not_fk |
| 无设备外键 | 不存在 device_resume FK | test_no_fk_to_device |
| 改系统名称后记录不更新 | 文本引用不会同步 | test_rename_system_doesnt_update_record |
| 删除系统后记录仍存在 | 无级联删除 | test_delete_system_doesnt_delete_records |
| 升级不自动写 DeviceEvent | 无自动履历生成 | test_no_auto_device_history |

### 3.2 UpgradeSystem 当前字段

| 行为 | 描述 | 测试 |
|---|---|---|
| 是字典表 | 有 tenant_id，是租户级别字典 | test_upgrade_system_is_dictionary_table |
| 有 sort_order | 排序字段 | test_upgrade_system_has_sort_order |
| 有 is_active | 启用/停用标志 | test_upgrade_system_has_is_active |

## 4. 干扰模块旧架构行为

| 行为 | 描述 | 测试 |
|---|---|---|
| 无设备外键 | 不存在 device_resume FK | test_no_fk_to_device |
| frequency 是文本 | CharField 存储频率值 | test_frequency_is_text |
| status 有预定义选项 | draft/submitted/reviewed 等 | test_status_has_choices |
| report_dept 是文本 | CharField 存储部门名 | test_report_dept_is_text |

## 5. 告警模块旧架构行为

| 行为 | 描述 | 测试 |
|---|---|---|
| 无 tenant_id | 全局数据，使用 ModelMixin | test_alert_is_global_no_tenant_id |
| AlertRead.user_id 是 IntegerField | 不是 ForeignKey 到 User | test_alert_read_uses_user_id_not_fk |
| 使用 ModelMixin | 不使用 TenantModelMixin | test_alert_uses_model_mixin_not_tenant_mixin |
| level 有 3 种选项 | error/warning/info | test_alert_level_choices |
| status 有 2 种选项 | active/resolved | test_alert_status_choices |
| AlertRead 有唯一约束 | (alert_id, user_id) 保证幂等 | test_alert_read_unique_constraint |

## 6. 关键临时行为总结

以下行为在重构时**必须处理**：

1. **DeviceEvent.device_resume_id 为 IntegerField** → 改为外键
2. **FaultRecord.system_name/device_code 为文本** → 改为外键
3. **UpgradeRecord.system 为文本** → 改为外键
4. **DeviceEvent 冗余文本字段** → 去冗余或改为外键
5. **FaultPart 无 FaultRecord 外键** → 增加外键
6. **UpgradeRecordStep/StatusLog.upgrade_id 为 IntegerField** → 改为外键
7. **AlertRead.user_id 为 IntegerField** → 改为外键
8. **Alert 无 tenant_id** → 确认是否需要租户隔离
9. **事件/履历手工创建** → 确认是否需要自动生成
10. **DeviceResume CHECK 约束** → 迁移时需确保兼容

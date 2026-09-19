# 彻底移除"系统类型"机制 — 实施计划

## 目标

删除 SystemType 及其全部派生机制：类型 CRUD、类型模板字段（scope=template）、系统建档的类型必填、台账模板按类型适用、相关权限码/菜单/页面。自定义字段（scope=custom）机制完整保留——这是此前已确认的 custom-fields-only 路线。

## 数据影响（明示）

新增迁移 `0011_remove_system_type`（一功能一迁移，数据操作在 DDL 之前）：
1. **台账模板**：已按"适用系统类型"定义的模板，迁移时把该类型下全部系统写入其 `applicable_systems` M2M（语义等价转换，不丢模板）；
2. **模板字段及其已录值**：scope=template 的字段定义和 SystemConfigValue 一并删除（PROTECT 要求先删值）。若 dev/生产已录了需要保留的模板字段值，请在审批时提出，我改为"转换为各系统自定义字段"的洗数据方案；
3. **系统的类型归属值**：`LifecycleSystem.system_type` 列删除（仅dev测试数据）。
4. 存量角色 JSON 里残留的 `equipment_lifecycle.system_type.*` 码是惰性的（校验只对"提交⊆操作者"），**不动 account 数据**，下次保存角色自然清除。

## 后端改动（apps/equipment_lifecycle）

**models.py**：删 `SystemType` 类；`LifecycleSystem` 删 system_type FK 及 (tenant_id, system_type) 索引、to_view 两字段；`ConfigFieldDefinition` 删 system_type FK 与 SCOPE_TEMPLATE（scope_type/scope_owner_id 列保留，唯一约束不变）；`OperationLedgerTemplate` 删 applicable_system_type FK，`applies_to_system()` 退化为 M2M 判断。

**views.py**（最重）：删 SystemTypeView / SystemTypeDetailView / TypeFieldView / TypeFieldDetailView / CustomFieldPromoteView / `_get_type_for_user` / AUDIT_TARGET_TYPE；系统创建不再要求 system_type（含 `?system_type=` 列表筛选、聚合创建的模板字段加载与 template_values 处理、审计里的类型名）；RESERVED 保留字去掉 system_type/系统类型；`_generate_field_code` 只查本系统自定义字段；动态列表筛选条件从"模板字段且 is_filterable"改为"自定义字段且 is_filterable"；form-fields 接口去掉新增模式（新增页动态字段全部走内联自定义字段），保留编辑模式；CSV 导出去类型列、"来源"列只剩自定义。

**services.py**：`collect_applicable_fields` 只取 custom；快照固定字段删 system_type（历史快照内容不受影响）。

**ledger_views.py**：模板头校验删类型分支，必填改为"请选择适用系统"；巡检点归属校验只用 M2M；列表 select_related、编辑写回同步删。

**work_order_views.py / fault_views.py**：candidate-systems 候选输出删 system_type_name（前端无消费方）。

**urls.py**：删 system-types 四条路由和 custom-fields promote 路由。

## 前端改动（spug_web/src）

- **routes.js**：删"系统类型"菜单项与 import；组/子组 auth 字符串去掉 system_type.view；
- **constants.js**：删 TYPE_* 四个权限常量；**system/role/codes.js**：删"系统类型模板"权限树节点（L112-120）；
- **整目录删除** `pages/equipmentLifecycle/systemType/`（index.js + store.js）；
- **store.js**：删 f_system_type / types / fetchTypes（fetchFormFields 保留，编辑模式仍需要）；**index.js** 删类型筛选下拉；**Table.js** 删类型列；
- **SystemForm.js**：删类型下拉、模板字段加载、切换类型确认弹窗、template_values 载荷、"类型扩展字段"区块；内联自定义字段（custom_fields + client_key）能力保留，新增流程不受影响；
- **SystemDetail.js / ConfigArchiveTab.js**：删类型展示、模板字段只读表、"提升为模板字段"动作及相关文案；ConfigFieldsIndex.js 注释同步；
- **ledger/TemplateForm.js** 删"适用系统类型"选择器与 systemTypes 拉取；**TemplateIndex.js** 删该列；**LedgerForm.js** 删死状态 systemTypeNames；
- **systemStatus/Table.js** 删类型列。

## 测试

- 后端：tests/base.py 工厂改造（make_type 删除、make_system 去类型、make_field 只支持 custom），18 个测试文件同步修改；在 tdyw-test 容器跑 `manage.py test apps.equipment_lifecycle.tests --keepdb`，全绿为准；
- 前端：6 个测试文件（SystemForm/store/SystemIndex/ConfigFieldsIndex/systemStatus/LedgerForm.submit）更新 mock 与断言；`CI=true npm test -- --watchAll=false equipmentLifecycle` 全绿为准。

## 验证与收尾

1. `python manage.py check` + py_compile（容器内）；
2. 迁移在 tdyw-test 测试库自动验证；**dev 库执行 migrate**（注意 0010 尚未应用，会 0010+0011 一起上）并重启 tdyw 容器；
3. 生产部署需重建镜像 + migrate（前端菜单/权限树变化需重新登录生效）；
4. 全程不创建 commit；改动文件保持 LF。

## 不做的事

- 不引入任何替代分类字段（系统建档不再有分类概念，符合你的决定）；
- 不动 fault/work_order/event/health 状态机（仅候选输出微调）；
- 不动《总体方案 v2.0》等设计文档（如需同步由你决定）。
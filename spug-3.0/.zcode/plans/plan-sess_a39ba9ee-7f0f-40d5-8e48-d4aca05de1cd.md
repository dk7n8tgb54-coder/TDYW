# 彻底删除巡检点功能（含台账明细"维护位置"字段）

## 决策依据（用户已确认）
- 彻底删除：模型、数据表 `tdyw_el_inspection_point`、两处外键、接口、页面、权限码全删，新增迁移 0013。
- 台账明细上的手填"维护位置"（`location_snapshot`）一并删除——明细不再有位置概念；原"巡检点或维护位置二选一必填"校验整体删除。
- `SystemFault.fault_location`、`SystemWorkOrder.work_location` 是故障/工单自身的独立字段，**保留**，仅转单时不再自动预填（手动填写）；表单标签"故障位置/巡检点"改为"故障位置"。
- 台账表头 `location_scope`（机房/区域/维护范围）是表头字段，与明细位置无关，**不动**。
- 角色 JSON 中残留的 `equipment_lifecycle.inspection_point.*` 权限码惰性不洗（沿用 0011 SystemType 先例）。

## 一、后端 spug_api/apps/equipment_lifecycle/

1. **models.py**
   - 删 `SystemInspectionPoint` 整类（844-899）。
   - 删 `OperationLedgerTemplateItem.inspection_point` FK（987-989）及 to_view 中两行（1063-1064）。
   - 删 `OperationLedgerItem` 的"巡检点/维护位置"块（1236-1241）：`inspection_point` FK、`point_name_snapshot`、`location_snapshot`，及 to_view 对应三键（1336-1338）。
   - 更新 762 行结构注释（去掉"巡检点/维护位置"层级）。
2. **ledger_services.py**
   - 删 `get_point_for_entry`（146-155）、`ITEM_EDITABLE_FIELDS` 中 `'location_snapshot'`（64）。
   - `_build_item_instance`（406-458）：删 point/location 取值与校验（408-409、419-420、427-428、439-441）。
   - `_apply_item_edits`（600-607）：删巡检点改绑分支。
   - `preview_entries`（669）：删 `inspection_point_id` 附加。
3. **ledger_views.py**
   - 删 `AUDIT_TARGET_POINT`（61）、`_get_point_for_user`（90-91）、`InspectionPointView/DetailView/ActiveView` 三个类（94-196）。
   - 模板项目校验删 `inspection_point` 分支（272-280、298）。
   - CSV 导出删"巡检点/位置"列（838、857）。
4. **urls.py**：删 3 条 inspection-points 路由（61-64）。
5. **views.py**：`_collect_system_references` 删巡检点检查块（321-323）与 import（314），更新 docstring。
6. **work_order_views.py**：1260、1289、1399 处去掉 `point_name_snapshot/location_snapshot` 取值（转故障/转工单不再预填位置），更新 1193 docstring。
7. **迁移 0013**（`makemigrations equipment_lifecycle`，一功能一迁移）：RemoveField ×4（template_item.inspection_point、ledger_item.inspection_point/point_name_snapshot/location_snapshot）+ DeleteModel SystemInspectionPoint。不改动已应用的 0008。

## 二、前端 spug_web/src/

1. 删文件 `pages/equipmentLifecycle/ledger/PointIndex.js`。
2. **store.js**：删 PointStore 类（151-200）、`pointStore` 导出（212）、头注释；LedgerStore/TemplateStore 保留。
3. **entries.js**：删 PointIndex import/export（11、26）及注释。
4. **routes.js**：删 import 别名（61）、路由（97）、:87/:91 auth 串中 `|equipment_lifecycle.inspection_point.view`。
5. **role/codes.js**：删 inspection_point 权限块（135-141）。
6. **ledger/constants.js**：删 POINT_VIEW/POINT_MANAGE（11-12）。
7. **LedgerForm.js**：删 makeRow 的 `inspection_point_id`/`location`（55）、编辑回填（121）、预览取值（232）、`loadPoints`/`pointsMap`（88、203-210、256、499）、payload 字段（392）、整个"巡检点/位置"列（559-579，模板行与临时行一并删除）。
8. **LedgerDetail.js**（53）、**SystemLedgerTab.js**（51）：删"巡检点/位置"列。
9. **workOrder/LedgerItemDisposition.js**（237）：去掉 work_location 预填。
10. **FaultForm.js**（210）、**FaultDetail.js**（62）：标签"故障位置/巡检点"→"故障位置"。

## 三、测试同步

后端（stable_contract）：删 `test_ledger_points.py` 整文件；`ledger_base.py` 删 P_POINT_*/ALL_POINT_PERMS/POINT_URL/make_point 及 make_template_item/make_ledger_item/make_ledger_user 中的点参数；`test_ledger_boundaries.py` 删白名单中 SystemInspectionPoint（119、146）与未用 import；`test_system_events.py` 561-568 改为仅台账明细阻断；`test_exception_conversion.py`、`test_work_orders.py` 删 ALL_POINT_PERMS 与位置预填断言；`test_ledger_templates.py`、`test_single_system_simplification.py` 删 ALL_POINT_PERMS。
前端：`store.test.js` 删 PointStore/pointStore 用例（104-118）与 import；`LedgerPage.test.js` 删 point stub（161、176）；`LedgerForm.submit.test.js` 删造数字段（33）。

## 四、验证

1. `docker exec tdyw-test python manage.py makemigrations equipment_lifecycle`（核对生成的 0013 内容）+ `migrate`（test_spug 与 dev 库）+ `check`。
2. 后端测试：`docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py test apps.equipment_lifecycle --keepdb`。
3. 前端：`npm test`（CI=true）跑 equipmentLifecycle 相关套件；全局 grep 确认 `inspection_point/pointStore/POINT_VIEW/巡检点` 无残留（仅历史审计日志与角色 JSON 惰性数据除外）。
4. 汇报按 AGENTS.md 第十四节格式，不创建 commit。
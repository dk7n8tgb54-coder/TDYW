# 部门值班日志上线前测试收口报告

日期：2026-09-02

## 结论

当前后端和前端自动化门禁通过；E2E 浏览器门禁因宿主机 Chromium 启动权限被阻断，发布结论为 **BLOCKED（待补跑 E2E）**，不得直接标记为全量 PASS。

## 本次修复

- `departmentDutyLogStore.showDetail` 增加请求序号，旧详情响应不会覆盖当前记录。
- 版本冲突时移除表单重复 `message.error`，保留表单和用户输入。
- 公共审计 `save_audit_log` 使用 `json.dumps(..., default=str)`，保证 PUT 失败审计中的数据库 `date/datetime` 快照可落库。
- 增加失败编辑审计日期快照回归用例，并将前端缺陷复现用例更新为已修复回归用例。

## 执行结果

| 检查 | 结果 | 证据 |
|---|---|---|
| Django check | PASS（1 个既有 ForeignKey unique 警告） | WSL `tdyw-test` |
| 发布门禁后端 | PASS，39 项 | `apps.department_duty_log.tests.release_gate.test_release_gate` |
| 模块后端全量回归 | PASS，262 项 | `apps.department_duty_log.tests` |
| 审计专项 | PASS，5 项 | `DepartmentDutyLogAuditTests` |
| 前端单测 | PASS，12 项，2 suites | `spug_web/src/pages/departmentDutyLog/__tests__/` |
| 前端生产构建 | PASS（存在既有 ESLint warnings） | `npm run build` |
| Playwright E2E | BLOCKED：Chromium `spawn EPERM` | 当前宿主机无法启动浏览器 |

此前 2026-09-01 的 E2E 证据显示发布流程 8 项通过，见 `pre_release_20260901_234841/80_e2e_tests.txt`；修复后需在可启动浏览器的测试机补跑。

## 阻断与风险

- E2E 兼容性、移动视口和真实浏览器流程尚未在本次修复后重新执行。
- 共享 `apps.logs.tests` 当前有 22/34 项因测试夹具写入 `User.deleted_by_id=NULL` 与数据库约束不兼容而失败，属于既有测试环境/夹具问题，未扩大修复范围。
- 运行日志中的 CSRF warning 和 `document.DocumentSystemFolder.folder` unique ForeignKey warning 不构成本模块失败，但应由对应专项处理。

## 数据与清理

后端测试使用 WSL `tdyw-test` 隔离测试库；未执行开发库清理、生产操作或迁移变更。E2E 测试数据只允许使用既定 `E2E_DDL_RG_` 前缀并软删除本次创建的数据。

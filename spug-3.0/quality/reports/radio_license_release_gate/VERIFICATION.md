# 无线电执照模块 缺陷真伪验证报告（复验）

- **验证日期**: 2026-09-03（首轮全量测试后同日）
- **验证方式**: 每项缺陷对应一个表达正确业务规格的自动化用例（既有 15 项 + 本次新增 2 项），在真实代码路径上运行：用例 FAIL = 缺陷真实存在；用例 PASS = 缺陷已消除（或已修复）。
- **背景**: 首轮测试报告（REPORT.md）产出后，并行开发会话提交了缺陷修复（commit `e6c4b199`「完成无线电管理、合同协议、干扰模块的缺陷修复」等）。本复验对全部 18 项缺陷逐项重新执行用例，判定「真实/证伪」与「当前状态」。

## 一、验证矩阵（18 项缺陷，18 项判定为真实，0 项证伪）

| 编号 | 缺陷（严重级别） | 验证用例 | 首轮结果 | 本次复验 | 判定 |
|---|---|---|---|---|---|
| F-01 (High) | 执照附件下载端点跨对象越权 | `test_attachments.AttachmentIsolationTests.test_license_endpoint_cannot_download_approval_attachment` | FAIL（返回批复附件文件流） | **PASS** | ✅ 真实，**已修复** |
| F-02 (High) | 执照附件删除端点跨对象越权 | `...test_license_endpoint_cannot_delete_approval_attachment` | FAIL（软删成功） | **PASS** | ✅ 真实，**已修复** |
| F-03 (High) | 执照预览端点越权签发令牌 | `...test_license_endpoint_cannot_preview_approval_attachment` | FAIL（签发成功） | **PASS** | ✅ 真实，**已修复** |
| F-04 (High) | 附件删除证据事件死代码 | `test_versions_audit.AuditLogTests.test_attachment_delete_writes_evidence_event` | FAIL（0 条事件） | **PASS** | ✅ 真实，**已修复** |
| F-05 (Med) | 执照 ack 不校验责任人 | `test_reminders.LicenseAckAuthorizationTests.test_non_responsible_user_cannot_ack` | FAIL | **PASS** | ✅ 真实，**已修复** |
| F-06 (Med) | 执照 ack 不校验状态 | `...test_ack_normal_license_rejected` | FAIL | **PASS** | ✅ 真实，**已修复** |
| F-07 (Med) | status 筛选依赖缓存字段 | `test_license_functional.LicenseListTests.test_list_filter_by_status_realtime` | FAIL（0 条） | **PASS** | ✅ 真实，**已修复** |
| F-08 (Med) | 执照列表 N+1 | `test_performance.QueryCountTests.test_license_list_no_n_plus_1` | FAIL（5/20/25 条→45/134/164 次查询） | **PASS**（→21/20/20 恒定） | ✅ 真实，**已修复** |
| F-09 (Med) | 并发编辑重复 version_no | `test_versions_audit.ConcurrencyTests.test_concurrent_edits_version_consistency` | 间歇 FAIL（4 次中 2 次产生 [1,1]） | **5/5 轮 PASS**（含并发用例共 15 次执行） | ✅ 真实，**已修复**（`select_for_update` 行锁，`views.py:378`） |
| F-10 (Low) | `page=abc` 500 | `...test_list_invalid_page_param_returns_business_error_not_crash` | FAIL（服务器内部错误） | **PASS** | ✅ 真实，**已修复** |
| F-11 (Low) | changed_fields 恒空 | `test_versions_audit.VersionSnapshotTests.test_changed_fields_records_actual_changes` | FAIL（`'' != 'station_name'`） | **PASS** | ✅ 真实，**已修复**（`views.py:521` 现写入 `','.join(changed_fields)`） |
| F-12 (Low) | `validateFields()` 无 `.catch` | `radioLicense/__tests__/Form.validation-rejection.test.js`（**本次新增**） | 进程 `ERR_UNHANDLED_REJECTION` 崩溃实证 | **FAIL**（校验拒绝仍未处理，`Form.js:60` 无 catch） | ⚠️ 真实，**未修复** |
| F-13 (Low) | 业务失败双重提示/文案错误 | `radioLicense/__tests__/Form.behavior.test.js` 提交失败用例 | FAIL（收到通用兜底文案） | **PASS**（透传字符串错误，`Form.js:97-103`） | ✅ 真实，**已修复** |
| F-14 (Med) | store 旧请求覆盖新结果 | `store.request.test.js` 旧请求用例（执照+批复各一） | FAIL ×2 | **PASS ×2**（`_fetchSeq` 时序守卫 + `_active` 卸载守卫） | ✅ 真实，**已修复** |
| F-15 (Low) | 删除最后一页不回退 | `store.request.test.js` 空页回退用例 | FAIL | **PASS**（空页自动回退上一页） | ✅ 真实，**已修复** |
| F-16 (Low) | 附件下载按钮无权限门控 | `radioLicense/__tests__/Attachment.downloadPerm.test.js`（**本次新增**，真实渲染 AttachmentManager） | 代码级实证（`canDownload` 恒真） | **FAIL**（无权限仍显示下载按钮；批复侧对照组 PASS） | ⚠️ 真实，**未修复** |
| F-17 (Low) | 详情弹窗窄屏溢出 | E2E `rg_responsive_badge.spec.js` 详情弹窗用例（375px 实测） | FAIL（溢出 125px） | **FAIL（溢出 215px，较首轮加剧）** | ⚠️ 真实，**未修复** |
| F-18 (Low) | 批复操作列对仅查看用户不渲染 | 对照用例：执照 `Table.resizable.test.js`（仅查看→有「查看」按钮）vs 批复 `Table.perms.test.js`（仅查看→无操作列） | 行为不一致实证 | **两侧用例均 PASS（不一致仍在）**，`Table.js:126` 条件仍为 `edit|del` | ⚠️ 真实，**未修复** |

## 二、修复验证后的全量回归

| 套件 | 结果 |
|---|---|
| 后端全量（`apps.radio_license`，含修复会话新增用例） | **292 用例全部 OK**（`backend_verify_after_fix.log`） |
| 前端全量（radioLicense + stationFrequencyApproval + home/ExpiryOverview） | 42 用例：40 PASS，2 FAIL（即 F-12、F-16 两个未修复项的验证用例，`frontend_verify_after_fix.log`） |
| E2E（响应式+徽标+既有 CRUD） | 14 用例：13 PASS，1 FAIL（即 F-17 未修复项） |
| F-09 并发稳定性 | 连续 5 轮全 OK（修复前行锁缺失时 4 轮中 2 轮失败） |

## 三、修复实现抽查（与用例结果互证）

- **F-01~F-03**：`views.py:700` 新增 `_get_license_attachment_for_user`（校验 `module='radio_license' AND object_type='license'`），下载/删除/预览三个视图接入——与我报告建议的批复侧桥接模式一致。
- **F-04**：删除视图改为软删前持有附件实例，证据事件恢复写入。
- **F-09**：`views.py:378` `qs.select_for_update().get(pk=record_id)` 行锁串行化并发编辑。
- **F-11**：`views.py:521` `changed_fields=','.join(changed_fields)`。
- **F-13**：`Form.js:97-103` 按字符串错误透传文案。
- **F-14/F-15**：store 增加 `_fetchSeq`/`_active` 守卫与空页回退。

## 四、复验后的上线结论修订

**BLOCKED → CONDITIONAL**

- 4 项 High 阻断项（F-01~F-04）与全部 Medium 项均已修复并通过用例验证，后端全量 292 用例 0 失败。
- 剩余 4 项**未修复**缺陷均为 Low：F-12（表单校验拒绝未处理，控制台报错）、F-16（下载按钮权限门控缺失，后端会正确拒绝，仅前端展示问题）、F-17（窄屏弹窗溢出 215px，建议加 `max-width: calc(100vw - 32px)` 类响应式约束）、F-18（批复表仅查看用户无操作列，行为不一致）。
- 按门禁标准「CONDITIONAL：仅存在已批准的中低风险问题」——若相关方接受上述 4 项 Low 风险（建议随下一批次修复），可按 CONDITIONAL 放行；否则修复后即可 PASS。

## 四（补）、剩余 4 项 Low 缺陷修复记录（2026-09-12）

| 编号 | 修复内容 | 修复位置 | 验证 |
|---|---|---|---|
| F-12 | `validateFields()` 链尾补 `.catch(() => {})`，消化校验失败的 Promise 拒绝（错误提示仍由 antd Form 展示） | `radioLicense/Form.js`、`stationFrequencyApproval/Form.js` 的 handleSubmit | `Form.validation-rejection.test.js` PASS（修复前 FAIL）；同时移除 Form.behavior.test.js 中的测试侧包装器，回归走真实路径 |
| F-16 | 执照详情 AttachmentManager 补 `downloadPerm="radio_license.attachment.download"`，无权限用户不再显示下载按钮 | `radioLicense/Form.js` | `Attachment.downloadPerm.test.js` PASS（修复前 FAIL） |
| F-17 | 四个 Modal（执照详情 900/编辑 800、批复详情 900/编辑 720）加 `style={{maxWidth: 'calc(100vw - 32px)'}}` + `bodyStyle={{overflowX: 'auto'}}`：弹窗钳制在视口内，超宽内容（附件表格）在弹窗体内部横向滚动，桌面端无溢出时无滚动条 | 两个 Form.js | E2E 375px 实测：弹窗溢出 **399px → 0**，`rg_responsive_badge.spec.js` 全套 14/14 PASS |
| F-18 | 批复表操作列渲染条件 `edit\|del` → `view\|edit\|del`，仅查看用户保留「查看」入口，与执照表口径一致 | `stationFrequencyApproval/Table.js:128` | `Table.perms.test.js` 用例更新为断言新行为（仅查看→操作列+仅查看按钮+点击进详情），PASS |

**修复后全量回归**：前端 jest 42/42 全绿；E2E 14/14 全绿（前端已重新构建并部署至 tdyw-test）；后端无改动。**至此 18 项缺陷全部修复，上线结论可按 PASS 记录（后端 292 + 前端 42 + E2E 14 全部通过）。**

## 五、验证产物

- `backend_verify_after_fix.log` / `frontend_verify_after_fix.log`（本目录）
- 新增验证用例：`spug_web/src/pages/radioLicense/__tests__/Form.validation-rejection.test.js`、`Attachment.downloadPerm.test.js`（F-12/F-16 修复后应转 PASS，可直接作为回归门禁）
- E2E 溢出测量截图：`e2e-artifacts/`（本目录下）

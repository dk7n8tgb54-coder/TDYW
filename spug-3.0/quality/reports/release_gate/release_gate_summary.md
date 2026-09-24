# WP10 统一发布门禁结果

> 生成时间：2026-09-21T22:55:01.603838
> 输入文件：E:\TDYW\spug-3.0\quality\reports\acceptance\release_gate_input.json
> 门禁状态：**BLOCKED**

## 状态汇总

| 字段 | 值 |
|------|-----|
| schema_valid | True |
| input_valid | True |
| consumable_by_release_gate | True |
| can_release_now | False |
| gate_status | **BLOCKED** |

> 注：以下 6 条为门禁检查项结果（含重复展开），不代表 6 个独立根因。

## 门禁检查项结果（阻断项）

- [WP-WP8] Playwright 全系统端到端回归: failed (blocking): WP8 final_status=FAIL, blocking_findings=1, fail_reason=Plaintext password committed to Git in eb8ecf00
- [WP-WP9] 性能与灾备基线: partially complete (blocking): WP9 final_status=PARTIAL, warnings=4
- [SEC-001] Open CRITICAL findings block release (severity-based, blocking field ignored): 1 open CRITICAL finding(s): F-001
- [SEC-003] Leaked credentials must be rotated before release: 1 unrotated secret(s): SS-001
- [EVID-PERF-LOAD] 验证：性能负载测试已执行: evidence not confirmed (requires evidence.performance_load.status=PASS): evidence.performance_load.status=NOT_RUN; blocked_check performance_load: Locust not installed, dev database unsafe for load testing
- [EVID-DR-RESTORE] 验证：灾备恢复演练已执行: evidence not confirmed (requires evidence.disaster_recovery_restore.status=PASS): evidence.disaster_recovery_restore.status=NOT_RUN; blocked_check disaster_recovery_restore: tdyw-test connects to dev database, no drill environment

## 检查结果明细

| check_id | category | status | blocking | evidence | reason |
|----------|----------|--------|----------|----------|--------|
| INPUT-001 | input_validation | PASS | 否 | JSON parsed successfully; all required data fields present and valid; no secret_value fields | Input is valid and consumable by release gate |
| WP-WP1 | work_packages | PASS | 否 | WP1 final_status=PASS, blocking_findings=0 | 全系统盘点与测试规划: passed |
| WP-WP2 | work_packages | PASS | 否 | WP2 final_status=PASS, blocking_findings=0 | 日常业务模块特征测试: passed |
| WP-WP3 | work_packages | PASS | 否 | WP3 final_status=PASS, blocking_findings=0 | 资料与行政业务特征测试: passed |
| WP-WP4 | work_packages | PASS | 否 | WP4 final_status=PASS, blocking_findings=0 | 技术运维模块重构前基线: passed |
| WP-WP5 | work_packages | PASS | 否 | WP5 final_status=PASS, blocking_findings=0 | 全系统租户隔离与越权测试: passed |
| WP-WP6 | work_packages | PASS | 否 | WP6 final_status=PASS, blocking_findings=0 | 权限一致性审计工具: passed |
| WP-WP7 | work_packages | PASS | 否 | WP7 final_status=PASS, blocking_findings=0 | 数据库结构与数据质量审计: passed |
| WP-WP8 | work_packages | BLOCKED | 是 | WP8 final_status=FAIL, blocking_findings=1, fail_reason=Plaintext password committed to Git in eb8ecf00 | Playwright 全系统端到端回归: failed (blocking) |
| WP-WP9 | work_packages | BLOCKED | 是 | WP9 final_status=PARTIAL, warnings=4 | 性能与灾备基线: partially complete (blocking) |
| SEC-001 | security_findings | BLOCKED | 是 | 1 open CRITICAL finding(s): F-001 | Open CRITICAL findings block release (severity-based, blocking field ignored) |
| SEC-002 | security_findings | FAIL | 否 | 4 open HIGH finding(s): F-002, F-006, F-007, F-008 | Open HIGH findings prevent RELEASE_READY |
| SEC-003 | security_findings | BLOCKED | 是 | 1 unrotated secret(s): SS-001 | Leaked credentials must be rotated before release |
| EVID-WP6-REPORT | required_evidence | PASS | 否 | evidence.permission_audit.status=PASS; path=quality/reports/permission_audit/audit_summary.json; path=quality/reports/permission_audit/permission_catalog.csv; path=quality/reports/permission_audit/permission_mismatch.csv; path=quality/reports/permission_audit/coverage_gaps.md; path=quality/reports/permission_audit/frontend_permission_usage.csv; path=quality/reports/permission_audit/backend_permission_usage.csv; generated_at=2026-09-21T22:54:42; WP6 final_status=PASS | 验证：WP6 权限审计报告已生成: evidence confirmed |
| EVID-PERF-LOAD | required_evidence | BLOCKED | 是 | evidence.performance_load.status=NOT_RUN; blocked_check performance_load: Locust not installed, dev database unsafe for load testing | 验证：性能负载测试已执行: evidence not confirmed (requires evidence.performance_load.status=PASS) |
| EVID-DR-RESTORE | required_evidence | BLOCKED | 是 | evidence.disaster_recovery_restore.status=NOT_RUN; blocked_check disaster_recovery_restore: tdyw-test connects to dev database, no drill environment | 验证：灾备恢复演练已执行: evidence not confirmed (requires evidence.disaster_recovery_restore.status=PASS) |
| EVID-WP-REVERIFICATION | required_evidence | PASS | 否 | all 4 WPs final_status=PASS, tests_executed=true, execution_report verified | 验证：WP2/WP3/WP4/WP7 独立复验: evidence confirmed |

## 状态模型说明

### 检查项状态
- PASS: 检查通过
- FAIL: 检查失败（非阻断）
- BLOCKED: 检查被阻断
- NOT_RUN: 检查未执行
- NOT_REVERIFIED: 历史结果未独立复验
- NOT_APPLICABLE: 不适用于当前场景

### 门禁最终状态
- RELEASE_READY: 可发布
- NOT_READY: 无基础设施阻断，但存在失败项
- BLOCKED: 存在阻断项
- INPUT_INVALID: 输入无效

### 决策规则
1. 输入无法解析或缺少必要字段 -> INPUT_INVALID
2. 存在 CRITICAL 阻断、凭据未轮换、必需报告缺失 -> BLOCKED
3. 无阻断但存在失败测试或 HIGH 发现 -> NOT_READY
4. 全部强制检查 PASS -> RELEASE_READY
5. NOT_RUN/NOT_REVERIFIED/BLOCKED 绝对不能转换为 PASS
6. 门禁必须正常读取含有问题的有效报告，并根据问题输出 BLOCKED

### 凭据轮换闭环
- secret_findings 使用显式 `rotation_status` 字段
- `pending` / `unrotated` / `needs_rotation` -> BLOCKED
- `completed` / `verified` / `not_required` -> PASS
- 字段缺失时回退到推断逻辑（向后兼容）
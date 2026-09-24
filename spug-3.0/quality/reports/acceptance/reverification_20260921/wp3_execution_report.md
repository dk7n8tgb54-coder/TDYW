# WP3 资料与行政业务特征测试 — 独立复验执行报告

- 执行时间：2026-09-21（tdyw-test 容器，test_spug，--keepdb --parallel 1）
- 范围与结果：
  - contract_agreement：**224 通过**（含当日新增 9 个变异测试杀伤用例）
  - radio_license：**295 通过**（复验发现并发创建死锁缺陷，当日修复后复验通过）
  - document：**347 通过**（test_no_instant_upload 一处过期用例当日修正，单测复验 OK）
  - regulation：316 通过（skipped=1）
  - coop_task：149 通过
- 当日发现并修复的缺陷：
  1. radio_license 并发创建死锁（HIGH，已修复）：AuditLogSequence 惰性首写唯一键竞态 + save_audit_log 吞异常毒化事务。修复 = 迁移 0012 存量租户补建序列行 + Tenant post_save 预建信号 + 执照创建/编辑显式事务死锁重试 + urls 豁免请求级事务；并发用例 3 次复验通过。
  2. document test_no_instant_upload.test_10 过期用例（LOW，已修正）：PUBLIC 模型 2026-08-11 起无 tenant_id 字段。

# WP2 日常业务模块特征测试 — 独立复验执行报告

- 执行时间：2026-09-21（tdyw-test 容器，test_spug，--keepdb --parallel 1）
- 范围：apps.department_duty_log.tests apps.duty.tests apps.runlog.tests apps.reminder.tests apps.home.tests
- 结果：**OK（expected failures=7）**，约 279 用例（272 通过 + 7 个用例标记的预期失败）
- 备注：7 个 expectedFailure 为用例自身标记的预期行为，非回归

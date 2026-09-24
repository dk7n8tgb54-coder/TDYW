# WP4 技术运维模块重构前基线 — 独立复验执行报告

- 执行时间：2026-09-21（tdyw-test 容器，test_spug，--keepdb --parallel 1）
- 范围与结果（legacy_characterization）：
  - device：9 通过（skipped=1）
  - upgrade：9 通过
  - alert：6 通过
  - fault：**应用已删除**（2026-09 重构并入设备全生命周期模块），不在复验范围
  - interference：legacy_characterization 为空目录（0 用例）
- 结论：现存基线全部通过；范围变化为重构的有意结果，非遗漏

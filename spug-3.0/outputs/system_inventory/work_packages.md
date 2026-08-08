# 后续测试工作包

> 本文件定义后续独立测试对话的边界、范围和冲突文件。每个工作包可独立执行，但需遵守统一测试规范。

---

## WP-1: 日常业务模块特征测试

- **目标**: 为 fault、interference、duty、runlog、device 等日常业务模块补充特征测试
- **模块范围**: fault、interference、duty、runlog、device
- **输入**: `module_inventory.csv`、`api_inventory.csv`、`model_table_inventory.csv`
- **允许修改的目录**:
  - `spug_api/apps/fault/tests/`
  - `spug_api/apps/interference/tests/`
  - `spug_api/apps/duty/tests/`
  - `spug_api/apps/runlog/tests/`
  - `spug_api/apps/device/tests/`
  - `spug_api/tests/conftest.py`（公共 fixture）
- **禁止修改的目录**: 所有非 tests 目录的业务代码、前端代码、其他模块的测试
- **交付物**:
  - 各模块新增测试文件（按统一命名规范）
  - 测试覆盖率报告
- **验收标准**:
  - 每个模块至少覆盖：列表/详情/新增/编辑/删除/参数边界/权限拒绝/租户隔离/软删除/重复提交
  - 所有测试在 Docker 容器内通过
- **前置依赖**: 无
- **是否可以并行**: 是（与其他 WP 不冲突）
- **容易冲突的文件**: `spug_api/tests/conftest.py`（公共 fixture，需先创建）

---

## WP-2: 资料与行政业务特征测试

- **目标**: 为 document、regulation、contract_agreement、radio_license、department_duty_log 补充特征测试
- **模块范围**: document、regulation、contract_agreement、radio_license、department_duty_log
- **输入**: `module_inventory.csv`、`api_inventory.csv`、`risk_register.csv`
- **允许修改的目录**:
  - `spug_api/apps/document/tests/`
  - `spug_api/apps/regulation/tests/`
  - `spug_api/apps/contract_agreement/tests/`
  - `spug_api/apps/radio_license/tests/`
  - `spug_api/apps/department_duty_log/tests/`
- **禁止修改的目录**: 所有非 tests 目录、前端代码
- **交付物**:
  - 分片上传/合并/断点续传完整测试
  - 附件集成测试
  - 文件夹层级软删除测试
  - 公共空间权限测试
- **验收标准**:
  - document: 分片上传全链路（init→chunk→merge→completed）、物理删除+is_pending_clean、公共空间权限
  - regulation: 独立 storage.py 附件流程
  - contract_agreement: 到期提醒 Beat 任务
  - radio_license: 执照/批复双模型全量覆盖
  - department_duty_log: 签署幂等+CheckConstraint
- **前置依赖**: 无
- **是否可以并行**: 是
- **容易冲突的文件**: `spug_api/tests/conftest.py`

---

## WP-3: 技术运维模块特征测试

- **目标**: 为 upgrade、logs、alert、setting、reminder、signature、evidence、home 补充特征测试
- **模块范围**: upgrade、logs、alert、setting、reminder、signature、evidence、home
- **输入**: `module_inventory.csv`、`api_inventory.csv`、`risk_register.csv`
- **允许修改的目录**:
  - `spug_api/apps/upgrade/tests/`
  - `spug_api/apps/logs/tests/`
  - `spug_api/apps/alert/tests/`
  - `spug_api/apps/setting/tests/`
  - `spug_api/apps/reminder/tests/`
  - `spug_api/apps/signature/tests/`
  - `spug_api/apps/evidence/tests/`
  - `spug_api/apps/home/tests/`
- **禁止修改的目录**: 所有非 tests 目录、前端代码
- **交付物**:
  - 哈希链完整性测试
  - 告警 Beat 任务测试
  - 签名事务锁+SHA256 测试
  - 附件多态测试
  - 导航/公告排序事务测试
- **验收标准**:
  - logs: 哈希链校验、归档/清理、序列号
  - alert: 磁盘/DB 监控、数据质量巡检
  - signature: apply_signature 事务锁、超管限制
  - evidence: 多态附件、preview_token
  - home: 导航排序事务、公告过期同步
- **前置依赖**: 无
- **是否可以并行**: 是
- **容易冲突的文件**: `spug_api/tests/conftest.py`

---

## WP-4: 租户隔离与越权测试

- **目标**: 系统性验证所有业务模块的租户隔离和越权防护
- **模块范围**: 全部业务模块（account、document、fault、interference 等）
- **输入**: `risk_register.csv`（R005-R008）、`model_table_inventory.csv`
- **允许修改的目录**:
  - `spug_api/tests/tenant_isolation/`（新建目录）
- **禁止修改的目录**: 所有业务代码、所有现有测试
- **交付物**:
  - 租户 A/B 跨租户访问测试套件
  - 越权访问测试矩阵（每模块每 API）
  - 公共空间权限边界测试
- **验收标准**:
  - 租户 A 无法访问租户 B 的任何数据
  - 跨租户 ID 注入失败
  - 公共空间操作需 check_public_space_permission
  - GLOBAL 模块（alert/logs/setting）无租户隔离属预期
- **前置依赖**: WP-1/2/3 的公共 fixture（conftest.py）
- **是否可以并行**: 部分并行（依赖 conftest.py 创建后）
- **容易冲突的文件**: `spug_api/tests/conftest.py`、`spug_api/tests/tenant_isolation/conftest.py`

---

## WP-5: 权限一致性审计工具

- **目标**: 自动化比对后端 @auth 权限、前端路由权限、角色权限定义的一致性
- **模块范围**: 全部模块
- **输入**: `permission_inventory.csv`
- **允许修改的目录**:
  - `scripts/permission_audit.py`（新建脚本）
  - `outputs/permission_audit/`（输出目录）
- **禁止修改的目录**: 所有业务代码、所有测试
- **交付物**:
  - 权限一致性扫描脚本
  - 不一致报告（后端有/前端无、前端有/后端无、拼写冲突）
- **验收标准**:
  - 脚本能扫描所有 @auth 装饰器和 PERM_MAP
  - 脚本能扫描前端 routes.js 和 hasPerm 调用
  - 报告列出所有不一致项
- **前置依赖**: 无
- **是否可以并行**: 是
- **容易冲突的文件**: 无

---

## WP-6: 数据库结构与数据质量审计

- **目标**: 验证模型定义与数据库表结构一致性，检查数据质量
- **模块范围**: 全部模型（45 个实体模型）
- **输入**: `model_table_inventory.csv`
- **允许修改的目录**:
  - `scripts/db_structure_audit.py`（新建脚本）
  - `outputs/db_audit/`（输出目录）
- **禁止修改的目录**: 所有业务代码、所有迁移文件
- **交付物**:
  - 模型 vs 迁移一致性报告
  - 逻辑外键孤儿数据检测脚本
  - 索引覆盖率报告
  - 状态值分布报告
- **验收标准**:
  - 识别模型与迁移不一致的字段
  - 检测逻辑外键（device_id、file_id、template_id 等）的孤儿数据
  - 列出缺少索引的高频查询字段
- **前置依赖**: 无
- **是否可以并行**: 是
- **容易冲突的文件**: 无

---

## WP-7: Playwright 全系统端到端回归

- **目标**: 使用 Playwright 覆盖所有前端页面的主流程
- **模块范围**: 全部前端页面（19 个页面目录）
- **输入**: `module_inventory.csv`（frontend_path 列）
- **允许修改的目录**:
  - `spug_web/tests/e2e/`（新建目录）
  - `spug_web/playwright.config.js`（新建配置）
- **禁止修改的目录**: 所有业务代码、所有现有测试、后端代码
- **交付物**:
  - Playwright 配置和 fixture
  - 每个页面的冒烟测试（列表→新增→编辑→删除）
  - trace/截图/视频输出
- **验收标准**:
  - 所有正式页面可访问
  - CRUD 主流程通过
  - 窄屏布局检查
  - 权限按钮可见性验证
- **前置依赖**: WP-1/2/3 测试数据准备
- **是否可以并行**: 否（依赖测试数据）
- **容易冲突的文件**: `spug_web/tests/e2e/fixtures.js`、`spug_web/playwright.config.js`

---

## WP-8: 性能与灾备基线

- **目标**: 建立性能基线和灾备验证流程
- **模块范围**: document（上传）、data_analysis（聚合查询）、logs（审计日志）、列表分页
- **输入**: `risk_register.csv`（R026-R029）
- **允许修改的目录**:
  - `locustfile/baseline/`（新建目录）
  - `scripts/backup_restore_test.py`（新建脚本）
- **禁止修改的目录**: 所有业务代码、所有现有 locustfile
- **交付物**:
  - 大文件上传 Locust 基线
  - 列表分页性能基线
  - 跨 app 聚合查询基线
  - 备份/恢复验证脚本（不执行真实恢复）
- **验收标准**:
  - 上传 100MB 文件 P95 < 30s
  - 列表 10000 条 P95 < 500ms
  - 备份/恢复脚本可 dry-run
- **前置依赖**: 无
- **是否可以并行**: 是
- **容易冲突的文件**: 无

---

## WP-9: 统一发布门禁

- **目标**: 定义 CI/CD 发布门禁的检查项和通过标准
- **模块范围**: 全系统
- **输入**: 所有 CSV 清单和风险登记表
- **允许修改的目录**:
  - `scripts/release_gate.py`（新建脚本）
  - `outputs/release_gate/`（输出目录）
- **禁止修改的目录**: 所有业务代码、Docker 配置
- **交付物**:
  - 发布门禁检查脚本（Django check、迁移验证、测试收集、lint）
  - 门禁通过标准文档
  - 回滚检查清单
- **验收标准**:
  - 脚本自动执行所有只读检查
  - 输出 PASS/FAIL 报告
  - 门禁标准可配置
- **前置依赖**: WP-1~8 基本完成
- **是否可以并行**: 否（依赖其他 WP 的测试存在）
- **容易冲突的文件**: 无

---

## WP-10: 可选的 API 数据字典和用户手册

- **目标**: 生成 API 数据字典和用户操作手册
- **模块范围**: 全部 API
- **输入**: `api_inventory.csv`
- **允许修改的目录**:
  - `outputs/api_dictionary/`（输出目录）
  - `outputs/user_manual/`（输出目录）
- **禁止修改的目录**: 所有业务代码
- **交付物**:
  - API 数据字典（JSON + Markdown）
  - 用户操作手册（Markdown）
- **验收标准**:
  - API 字典包含所有 URL、方法、参数、响应
  - 用户手册覆盖所有前端页面操作
- **前置依赖**: 无
- **是否可以并行**: 是
- **容易冲突的文件**: 无

---

## 并行关系矩阵

| 工作包 | 可并行 | 依赖 | 冲突文件 |
|--------|--------|------|----------|
| WP-1 | WP-2,3,5,6,8,10 | 无 | conftest.py |
| WP-2 | WP-1,3,5,6,8,10 | 无 | conftest.py |
| WP-3 | WP-1,2,5,6,8,10 | 无 | conftest.py |
| WP-4 | 部分 | WP-1/2/3 的 conftest | conftest.py |
| WP-5 | 全部 | 无 | 无 |
| WP-6 | 全部 | 无 | 无 |
| WP-7 | 无 | WP-1/2/3 | e2e/fixtures.js |
| WP-8 | 全部 | 无 | 无 |
| WP-9 | 无 | WP-1~8 | 无 |
| WP-10 | 全部 | 无 | 无 |

## 建议执行顺序

1. **第一批（并行）**: WP-1 + WP-2 + WP-3 + WP-5 + WP-6 + WP-8 + WP-10
2. **第二批**: WP-4（依赖第一批的 conftest.py）
3. **第三批**: WP-7（依赖第一批的测试数据）
4. **第四批**: WP-9（依赖前八批的测试完成）

## 公共文件冲突管理

- `spug_api/tests/conftest.py`: WP-1/2/3/4 共享，**必须由第一个启动的 WP 创建**，后续 WP 只追加不覆盖
- `spug_web/tests/e2e/fixtures.js`: WP-7 独占
- `outputs/`: 各 WP 有独立子目录，不冲突

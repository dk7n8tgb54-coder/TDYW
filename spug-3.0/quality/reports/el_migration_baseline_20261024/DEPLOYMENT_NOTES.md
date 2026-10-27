# equipment_lifecycle 迁移基线重建——部署与数据操作说明（2026-10-24）

## 1. 迁移基线终态

- `equipment_lifecycle` 迁移图只有一个节点：`0001_initial`（由当前注册的 19 个模型
  重新生成，`options` 块折叠为单行以符合门禁 800 行限制，语义与 makemigrations
  原始输出等价）。旧 0001–0029 全部删除（备份见本目录之外的
  `%TEMP%/el_mig_backup_20261024/`，29 个文件）。
- `0001` 依赖 `account.0014_remove_tenant_is_active`；`upgrade.0022` 对
  `('equipment_lifecycle', '0001_initial')` 的依赖保留且已验证可解析。
- EL 未上线（生产库无 el 迁移记录、无 el 表），新 0001 **不含任何
  RunPython/RunSQL**：历史回填（runtime_record 状态归一、台账期次物化、
  原生路线清数、附件重指、角色权限换发等）全部不进入基线。
- `layout_models.py`（仅为旧迁移 0001 序列化引用保留的 LongTextField 兼容模块）
  随基线重建删除；Excel 路线使用 `excel_field_types.LongTextField`（独立定义，
  不受影响）。

## 2. 生产库（tdyw-db / tdyw）已执行的数据操作（2026-10-24）

| 操作 | 对象 | 结果 |
|---|---|---|
| DDL 备份 | 8 张旧空表（device/fault/duty/runlog） | `ddl_backup_all.sql` + 单表文件 |
| 行数快照 | 同上 | `row_counts_before.tsv`（全部 0） |
| Role.page_perms 清理 | 9 个角色：移除顶层 device/fault/duty/runlog 组、equipment_lifecycle.device/.relation、data_analysis.device/.fault | 走 `Role.save()` 既有路径，perms_version 全部 +1，二次执行幂等（**含完整 page_perms 的前后快照属敏感数据，不入 Git**：存于仓库外 `%TEMP%\el_migration_baseline_20261024_sensitive\roles_page_perms_before/after.tsv`；仓库内仅保留脱敏汇总 `role_perms_change_summary_sanitized.tsv`——角色/版本前后值/移除组清单，不含权限内容） |
| 四表 DROP | `tdyw_device_event`、`tdyw_device_resume`、`tdyw_fault_parts`、`tdyw_fault_records` | fail-closed 脚本 `drop_legacy_tables_20261024.sh`（表存在/0 行/无入向外键预检 + 每轮 DROP 前重验 + 后置复核；口令经环境变量 `DB_PASS` 注入，不写入文件；预检与 DROP 为不同连接，非单会话原子保证，已如实注明）；duty/runlog 四表**未动**，由 duty.0007 与 runlog.0015 迁移随下次部署 migrate 自动 DROP |
| 旧内容类型/权限清理 | django_content_type 8 条 + auth_permission 32 条 | 先删权限后删内容类型（外键顺序），执行前后核实 `auth_user_user_permissions`/`auth_group_permissions` 为 0 行；审计日志/EvidenceEvent 不引用 content_type（字符串标签），哈希链未触碰（`content_type_cleanup_result.txt`） |
| 未动 | django_migrations 中 device(10)/fault(6) 孤儿记录 | 按任务要求不直接修改；Django 对未安装 app 的记录忽略 |

### 安全说明（2026-10-24 复核整改）

- `drop_legacy_tables_20261024.sh` 原硬编码口令已移除：口令必须经环境变量
  `DB_PASS` 注入，缺失即拒绝执行；脚本从未被提交（整改时仍为未跟踪状态，
  无外泄面），本次事件不强制轮换口令。
- 遗留提示（既有问题、超出本任务范围）：仓库中 `SECURITY_MEASURES.md`、
  `borgbackup/borg.env`、`backups/tdyw_backup.cnf` 等已跟踪文件含同一生产
  口令，建议另行评审轮换与出库。
- 含完整 page_perms 的角色快照已移出仓库
  （`%TEMP%\el_migration_baseline_20261024_sensitive\`），仓库内仅保留
  `role_perms_change_summary_sanitized.tsv` 脱敏汇总（角色/版本/移除组清单）。

## 3. 部署注意事项（关键）

1. **必须移除 `RELEASE_PENDING_APPS=equipment_lifecycle`**（部署主机
   `docker/.env`）。新代码中 `apps/upgrade/models.py` 与
   `models_template.py` 直接 `from apps.equipment_lifecycle.models import
   LifecycleSystem`；el 被摘出 INSTALLED_APPS 时该导入即失败（模型类无显式
   app_label，注册失败抛异常），整个应用无法启动。当前生产容器为旧镜像
   （tdyw:0917，upgrade 模型尚无该导入），故当前共存无恙；新镜像上线时该
   开关必须清空。el 模块随之正式上线（新 0001 首次在生产库建 19 张表）。
2. `docker/config/entrypoint.sh` 已修复 migrate 失败掩盖（`|| echo` 改为
   显式 `exit 1`），部署验证可可靠发现迁移失败；`migrate-entrypoint.sh`
   本就 fail-fast，无需改动。
3. 部署时 `migrate` 将自动执行：`equipment_lifecycle.0001_initial`（建表）、
   `duty.0007` + `runlog.0015`（DROP 各自旧表）、`upgrade.0022–0024`。
   upgrade 0022 的回填在真实生产数据上按名称匹配 LifecycleSystem——上线时
   系统档案尚为空，1 条升级记录与 1 条方案的 `system_name='晋江系统'` 快照
   保留、外键为空（预期）；随后按正常流程在「系统档案」新建正式系统档案
   （如"晋江系统"），并在升级记录/方案编辑中重新选择系统即可回填外键。
   `tdyw_upgrade_systems`（11 个通用候选）由 0022 按设计删除，其候选语义由
   系统档案承接，**不得**把通用候选伪造成正式档案。
4. 上线后务必执行 `makemigrations equipment_lifecycle --check --dry-run`
   作为部署验证之一（应返回 No changes detected）。

## 4. 验证记录

- 隔离库 `spug_el_baseline`（tdyw-db-test）：从空库分阶段 migrate
  （el 0001 → upgrade 0021 → 播种生产镜像数据 → upgrade 0022–0024 → 全量）
  全部成功；el 19 表集合与模型 db_table 完全一致；8 张退役族表不存在；
  upgrade 数据保留验证通过（records=1、templates=1、快照不变、system_id=NULL
  为预期、systems 表已删）。
- `makemigrations equipment_lifecycle --check --dry-run`：No changes detected。
- **全量后端复跑**（`backend_test_run_full_20261024_v2.log`，settings_test_isolated，
  测试库从空重建，含修复后的基线测试）：899 例 = **29 失败 + 0 错误 + 1 跳过**。
- **既有漂移独立证实**（`head_worktree_period_tests.log`）：以 `git worktree`
  检出纯净 HEAD（旧迁移链 0001-0029 + 原始模型 + 原始测试）在一次性容器中对
  同样 4 个失败模块重跑 67 例 = 29 失败，失败用例清单与当前树**逐条完全一致**
  （diff 为空）。即该 29 项失败在本次改动之前即存在于 HEAD，与本基线重建无关；
  根因均为期次生成 API 的 `maintenance_cycles` 必填校验（ledger_period_services
  `请选择维护周期`）与测试预期漂移，修复属期次业务范畴、不在本任务内处理。
- `apps.upgrade` 独立套件 129/129 绿；新基线测试
  （test_migration_baseline + test_native_ledger_removal）12/12 绿。
- 代码质量门禁：0 错误 0 警告（0001 的 options 块折叠后 732 行）。
- 对照运行曾用一次性容器（镜像自带 entrypoint 对 dev `spug` 库执行了 HEAD
  代码的 migrate——因 dev 库 django_migrations 已覆盖完整旧链，为预期 no-op；
  事后核验：el 迁移记录 82 条含全部哨兵名、19 张 el 表、
  `makemigrations --check` 干净，dev 库无任何变化）。

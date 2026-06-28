# Django Migration Squash 规范

本文档用于规范项目中 Django migration 的压缩、保留、删除和验证流程。

## 核心原则

`squashmigrations` 的作用是把一段已经稳定的 migration 历史压缩成一个等价的新 migration 文件。

它不是清空 migrations，也不是直接删除线上历史。正确使用时，它可以让新环境初始化更快、迁移历史更清爽，并减少长期维护旧 migration 的成本。

简单理解：

```text
squash 前：数据库按 0001、0002、0003... 一步步迁移到当前状态
squash 后：新环境可以直接执行压缩后的 migration，旧环境也能识别自己已经执行过旧 migration
```

## 什么时候适合 squash

适合 squash 的情况：

- 某个 app 的 migration 数量明显增多，例如超过 20 到 30 个。
- 一个功能阶段或版本周期已经结束，表结构相对稳定。
- 存在大量中间过程 migration，例如反复加字段、改字段、删除字段。
- 新环境初始化明显变慢。
- 历史 migration 开始依赖已经废弃的代码、函数或字段，导致维护成本升高。

不适合 squash 的情况：

- 功能仍在频繁改表。
- 最近刚上线，还不能确认所有环境都已经执行完迁移。
- migration 中包含复杂的 `RunPython`、`RunSQL` 或 `SeparateDatabaseAndState`，且尚未人工确认。
- 团队成员、测试环境、生产环境的迁移状态不一致。
- 只是觉得 migrations 文件多，但还没有实际维护压力。

## 标准操作流程

以下以 `radio_license` app 为例。

先查看当前迁移状态：

```powershell
cd E:\TDYW\spug-3.0\spug_api
python manage.py showmigrations radio_license
```

确认需要压缩到的目标 migration，例如 `0007`：

```powershell
python manage.py squashmigrations radio_license 0007
```

Django 会生成一个新的 squashed migration 文件，文件中通常包含类似内容：

```python
replaces = [
    ('radio_license', '0001_initial'),
    ('radio_license', '0002_add_attachment_model'),
    ('radio_license', '0003_add_reminder_model'),
    ('radio_license', '0004_remove_is_deleted'),
    ('radio_license', '0005_add_reminder_ack'),
    ('radio_license', '0006_auto_20260627_0807'),
    ('radio_license', '0007_evidence_attachment_version'),
]
```

这个 `replaces` 表示新的 squashed migration 可以替代这一组旧 migration。

## 人工检查清单

生成 squashed migration 后，必须人工 review。重点检查：

- 是否包含 `RunPython`。
- 是否包含 `RunSQL`。
- 是否包含 `SeparateDatabaseAndState`。
- 是否引用了已经删除或计划删除的旧函数、旧 model、旧字段。
- 是否存在数据修复逻辑被错误优化或顺序改变。
- 是否正确保留必要的索引、唯一约束、外键、默认值。
- 是否把“先添加后删除”的历史字段正确优化掉。
- 是否与当前 `models.py` 的最终结构一致。

注意：Django 对普通 schema 操作的优化通常比较可靠，但它不一定能完全理解业务数据迁移逻辑。凡是涉及数据迁移的 migration，都要更谨慎。

## 验证流程

至少执行以下命令：

```powershell
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py migrate
```

推荐同时用两类数据库验证：

```text
旧库验证：已经执行过旧 migrations 的数据库，切换到 squash 后代码，确认 migrate 无异常。
新库验证：空数据库直接执行 squash 后代码，确认可以完整建表并生成正确结构。
```

如果项目存在自动化测试，应在 squash 后运行相关测试，至少覆盖被压缩 app 的模型、接口和关键业务流程。

## 旧 migration 的删除策略

不要在生成 squashed migration 后立刻删除旧 migration 文件。

推荐采用分阶段策略：

```text
第一阶段：提交 squashed migration，同时保留旧 migration 文件。
第二阶段：等待所有开发、测试、生产环境都部署并执行过包含 squash 的版本。
第三阶段：在后续版本中删除被 replaces 替代的旧 migration 文件。
第四阶段：确认没有环境依赖旧 migration 后，可以清理 squashed migration 中的 replaces。
```

这样可以同时兼容：

```text
旧环境：已经执行过 0001 到 0007。
新环境：从零开始直接执行 squashed migration。
```

## 团队约定

建议本项目采用以下约定：

- 单个 app 超过 20 到 30 个 migration，且模块稳定后，再考虑 squash。
- 每次大版本发布前检查一次 migration 数量。
- 每个功能分支尽量只提交必要的 migration。
- migration 文件尽量使用有意义的名称，避免大量无语义的 `auto_xxx` 文件。
- schema migration 和 data migration 尽量分开。
- 含 `RunPython`、`RunSQL`、`SeparateDatabaseAndState` 的 migration 必须人工 review。
- 生产环境未确认完成迁移前，禁止删除旧 migration。
- 禁止手动修改 `django_migrations` 表，除非是在明确的灾难恢复场景。

## 常见误区

### 误区一：squash 就是删除旧 migrations

不是。squash 会生成一个新的替代 migration，旧 migration 需要保留一段时间，等所有环境都稳定后再删除。

### 误区二：当前 models.py 里都有 migration 的内容

不一定。`models.py` 表示当前最终结构，migration 表示数据库从过去一步步变到现在的过程。历史字段、已删除字段、数据迁移、手写 SQL 不一定会出现在当前 `models.py` 中。

### 误区三：migration 文件越少越好

不是。migration 的首要目标是可靠地记录数据库演进过程。只有当历史迁移数量造成实际维护成本时，才需要 squash。

### 误区四：squash 后不用测试

不行。squash 后必须验证旧库和新库两种路径，否则容易出现“老环境没问题，新环境初始化失败”或相反的问题。

## 当前项目建议

当前项目中单个 app 的 migration 数量还不算高，暂时没有必要立即大规模 squash。

建议先建立规范，在后续大版本发布前检查各 app 的 migration 数量。等某些模块达到 20 到 30 个 migration，且表结构进入稳定期后，再按本文档流程进行 squash。

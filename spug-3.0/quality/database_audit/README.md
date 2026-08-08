# 数据库结构与数据质量审计工具

> 本目录存放跨系统数据库审计工具。针对单个业务模型的迁移和回归测试应放回该业务 app。

## 目录结构

```
quality/database_audit/
├─ README.md                    # 本文件
├─ audit_database.py            # 统一审计入口
├─ database_rules.yml           # 数据库检查规则和阈值
├─ model_exceptions.yml         # 经确认的模型特殊情况
├─ checks/                      # 各专项检查脚本
│  ├─ model_table_consistency.py
│  ├─ migration_consistency.py
│  ├─ tenant_fields.py
│  ├─ soft_delete.py
│  ├─ orphan_records.py
│  ├─ foreign_keys.py
│  ├─ unique_constraints.py
│  ├─ indexes.py
│  ├─ datetime_queries.py
│  ├─ data_quality.py
│  └─ stale_module_objects.py
├─ queries/
│  └─ read_only/                # 只允许 SELECT/SHOW/EXPLAIN
├─ tests/
│  ├─ unit/
│  ├─ fixtures/
│  └─ integration/
└─ baselines/
   ├─ schema_baseline.json
   └─ approved_findings.yml
```

## 使用方法

```bash
# 在 Docker 容器内执行（通过 manage.py shell）
cat audit_database.py | docker exec -i -e PYTHONIOENCODING=utf-8 \
  -w /data/spug/spug_api tdyw-test python manage.py shell

# 或复制到容器后执行
docker cp audit_database.py tdyw-test:/tmp/
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api \
  tdyw-test python manage.py shell -c "exec(open('/tmp/audit_database.py').read())"
```

## 安全约束

- **只允许** SELECT / SHOW / EXPLAIN
- **禁止** INSERT / UPDATE / DELETE / DROP / TRUNCATE / ALTER
- **禁止** manage.py migrate / makemigrations / flush
- **禁止** 导出真实业务数据、密码、Token
- **禁止** 连接生产数据库

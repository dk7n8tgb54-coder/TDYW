# 租户隔离与越权专项测试

## 目录结构

```
quality/tenant_isolation/
├─ README.md               ← 本文件
├─ tenant_matrix.yml       ← 模型租户分类矩阵
├─ run_tenant_tests.py     ← 专用运行入口
├─ factories/
│  ├─ __init__.py
│  ├─ tenants.py           ← 租户 A/B 创建
│  ├─ users.py             ← 用户/角色创建
│  └─ business_objects.py  ← 各模块业务对象创建
├─ helpers/
│  ├─ __init__.py
│  ├─ api_assertions.py    ← API 响应解析与断言
│  ├─ file_assertions.py   ← 文件隔离断言(含源码审查结论)
│  └─ cache_assertions.py  ← 缓存隔离断言(含源码审查结论)
└─ tests/
   ├─ __init__.py
   ├─ test_cross_tenant_crud.py          ← CRUD 跨租户测试(8模块)
   ├─ test_cross_tenant_relations.py     ← 跨租户外键关联测试
   ├─ test_cross_tenant_files.py         ← 文件/附件隔离测试
   ├─ test_cross_tenant_statistics.py    ← 统计/数据泄露测试
   ├─ test_cross_tenant_cache.py         ← 缓存隔离测试
   ├─ test_cross_tenant_tasks.py         ← Celery 任务隔离测试
   └─ test_global_data_boundaries.py     ← 全局数据边界测试
```

## 运行方式

### 前置条件

- Docker 容器 `tdyw-test` 运行中
- 容器内有 bind mount 挂载 `spug_api/` 到 `/data/spug/spug_api`
- 容器连的是 dev 库（不是独立测试库）

### 执行命令

```powershell
# Windows PowerShell (WSL)
wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONUNBUFFERED=1 -w /data/spug/spug_api tdyw-test python /data/spug/spug_api/quality_tenant_isolation_runner.py'
```

或手动将 `quality/tenant_isolation/` 复制到容器内执行：

```bash
# 复制测试文件到容器
docker cp quality/tenant_isolation tdyw-test:/data/spug/spug_api/quality_tenant_isolation

# 在容器内执行
docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONUNBUFFERED=1 -w /data/spug/spug_api tdyw-test python quality_tenant_isolation/run_tenant_tests.py

# 清理
docker exec tdyw-test rm -rf /data/spug/spug_api/quality_tenant_isolation
```

### 测试输出

测试结果输出到 stdout，包含：
- 每个测试的 PASS/FAIL 状态
- 汇总统计（总计/通过/失败）
- 失败项详情
- JSON 格式结果（供报告生成）

## 测试覆盖

### 已执行行为测试的模块 (7 个)

| 模块 | 测试文件 | 覆盖操作 |
|---|---|---|
| home/navigation | test_cross_tenant_crud.py | 列表/修改/删除 |
| reminder | test_cross_tenant_crud.py | 列表/用户列表/修改/删除/租户伪造 |
| runlog | test_cross_tenant_crud.py | 列表/详情/修改/删除 |
| fault | test_cross_tenant_crud.py | 列表/修改/删除 |
| account | test_cross_tenant_crud.py | 列表/修改/删除 |
| dashboard | test_cross_tenant_statistics.py | 统计隔离 |
| regulation | test_global_data_boundaries.py | 模型审查 |

### 仅源码审查的模块 (11 个)

radio_license, contract_agreement, interference, device, upgrade,
department_duty_log, duty, document, evidence, logs, data_analysis

### 已确认漏洞

| ID | 严重度 | 模块 | 漏洞 |
|---|---|---|---|
| TI-001 | CRITICAL | home/navigation | NavView 完全无 apply_tenant_filter |
| TI-003 | HIGH | reminder | ReminderUsersView 泄露全部租户用户 |

## 安全保证

- [x] 未修改生产业务代码
- [x] 未修改模型和迁移
- [x] 未修改权限配置/菜单/路由/中间件
- [x] 未接触生产数据（测试数据使用 ti_ 前缀，自动清理）
- [x] 未接触真实附件
- [x] 未创建 Git commit

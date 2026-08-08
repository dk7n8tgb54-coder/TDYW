# WP10 统一发布门禁

> 只读工具：读取验收报告和配置，输出发布门禁判断。不修改业务数据，不连接数据库，不自动修复问题。
> 依赖：仅 Python 标准库（json/csv/os/sys/datetime）。不依赖 PyYAML 或 jsonschema。

## 目录结构

```
quality/release_gate/
├─ README.md                          # 本文件
├─ gate.py                            # 门禁主入口
├─ policy.json                       # 门禁策略配置（JSON 格式）
├─ schemas/
│  └─ release_gate_input.schema.json  # 输入 JSON Schema（参考文档）
├─ checks/
│  ├─ __init__.py                     # 共享数据模型（CheckResult/GateResult/常量）
│  ├─ input_validation.py             # 输入校验（JSON 解析 + 手动 schema 校验）
│  ├─ work_packages.py                # 工作包状态检查
│  ├─ security_findings.py            # 安全发现检查（含凭据轮换闭环）
│  ├─ required_evidence.py            # 必需证据检查（正面证据驱动）
│  └─ release_decision.py             # 最终决策
└─ tests/
   ├─ __init__.py
   ├─ test_input_validation.py        # 输入校验测试
   ├─ test_release_decision.py        # 决策逻辑测试
   └─ fixtures/                       # 测试用例 JSON
```

## 输入与门禁输出职责分离

输入 JSON 只需包含数据字段（packages、confirmed_findings、secret_findings、verified_test_results 等）。
门禁输出字段（schema_valid、input_valid、consumable_by_release_gate、can_release_now、gate_status）
由门禁计算，不属于输入必需字段。如果输入中包含这些字段，仅做类型检查，门禁不信任其值。

## 必需证据检查

门禁要求**正面证据**，而非仅检查负面信号缺失：

| 检查项 | 正面证据要求 |
|--------|------------|
| WP6 权限审计报告 | `missing_artifacts` 无 WP6 条目 + `blocked_checks` 无 `permission_audit_report` + `artifacts_complete=true` |
| 性能负载测试 | `blocked_checks` 无 `performance_load` + `verified_test_results.total_verified_executed > 0` |
| 灾备恢复演练 | `blocked_checks` 无 `disaster_recovery_restore` |
| WP2/WP3/WP4/WP7 复验 | 全部 `final_status != NOT_REVERIFIED` + `total_verified_executed > 0` |

## 凭据轮换闭环

`secret_findings` 使用显式 `rotation_status` 字段：

| rotation_status | 含义 | 门禁行为 |
|----------------|------|---------|
| `pending` / `unrotated` / `needs_rotation` | 需要轮换但未完成 | BLOCKED |
| `completed` | 已轮换 | PASS |
| `verified` | 已轮换并验证 | PASS |
| `not_required` | 不需要轮换 | PASS |
| 字段缺失 | 回退到推断逻辑 | 视推断结果 |

## 状态模型

### 检查项状态

| 状态 | 含义 |
|------|------|
| PASS | 检查通过 |
| FAIL | 检查失败（非阻断） |
| BLOCKED | 检查被阻断（无法执行或条件不满足） |
| NOT_RUN | 检查未执行 |
| NOT_REVERIFIED | 历史结果未独立复验 |
| NOT_APPLICABLE | 不适用于当前场景 |

### 门禁最终状态

| 状态 | 含义 |
|------|------|
| RELEASE_READY | 全部强制检查通过，可发布 |
| NOT_READY | 无基础设施阻断，但存在失败测试或 HIGH 发现 |
| BLOCKED | 存在 CRITICAL 阻断项、凭据未轮换或必需报告缺失 |
| INPUT_INVALID | 输入 JSON 无法解析或缺少必要字段 |

### 决策规则

1. **INPUT_INVALID**：输入 JSON 无法解析、缺少必要字段或不符合 schema
2. **BLOCKED**：存在 CRITICAL 阻断漏洞、泄露凭据未轮换、强制报告缺失或必需环境不可用
3. **NOT_READY**：无基础设施阻断，但存在失败测试、HIGH 阻断发现或强制检查未通过
4. **RELEASE_READY**：全部强制检查为 PASS 且不存在阻断发现
5. NOT_RUN、NOT_REVERIFIED、BLOCKED 和缺失报告**绝对不能**转换为 PASS
6. 门禁必须正常读取含有问题的有效报告，并根据问题输出 BLOCKED

## 使用方法

```bash
# 使用当前验收输入运行门禁
python quality/release_gate/gate.py quality/reports/acceptance/release_gate_input.json

# 输出保存到 quality/reports/release_gate/
# - release_gate_result.json   (机器可读)
# - release_gate_summary.md    (人工阅读)
# - check_results.csv          (逐项结果)

# 运行单元测试（不依赖任何第三方库）
python -m pytest quality/release_gate/tests/ -v
# 或
python -m unittest quality/release_gate/tests/test_input_validation.py -v
python -m unittest quality/release_gate/tests/test_release_decision.py -v
```

## 安全约束

- 门禁只读取报告和配置文件，不修改任何业务数据
- 不连接开发数据库
- 不自动修复问题
- 报告不包含密码、Cookie、Token 或其他凭据
- JSON 输出使用 UTF-8 编码
- `schemas/release_gate_input.schema.json` 是参考文档，实际校验由 `checks/input_validation.py` 执行

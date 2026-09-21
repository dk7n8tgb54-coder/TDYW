# 合同协议模块变异测试分析报告

- 日期：2026-09-21
- 工具：mutmut 2.5.1（mutate 原地变异 + tdyw-test 容器内 Django 测试）
- 变异对象：`spug_api/apps/contract_agreement/{models,views,tasks}.py`（coverage 剪枝后 783 个变异体）
- 杀伤套件：`apps.contract_agreement.tests.stable_contract`（215 个测试，与发布门禁同套）
- 运行方式：每个变异体执行一次完整套件；runner 带服务就绪门禁与重启感知重试，判定结果不受 10:05~10:55 容器重启循环污染

## 一、总结果

| 指标 | 数值 |
|---|---|
| 变异体总数 | 783 |
| 杀死（killed） | 532 |
| 幸存（survived） | 251 |
| 超时/可疑/跳过 | 0 / 0 / 0 |
| **最终变异分数（初轮）** | **67.9%（532/783）** |

幸存者分布：views.py 146、models.py 93、tasks.py 12。

**补测试后更新（2026-09-21 下午）**：新增 9 个 stable_contract 测试（224 个全绿），经逐个 `mutmut apply` 红-绿验证杀死 9 个变异体，**修正后变异分数 69.1%（541/783）**；另有 5 个原判「真盲区」经源码细读重分类为等价变异体（见 D 节），251 → 242 个幸存者。

解读：初轮 67.9% 表示发布门禁对「注入的业务逻辑缺陷」的拦截率约为三分之二。幸存者中相当比例是测试环境下行为不变的等价变异体（见下），真实测试盲区约 30 个点位，其中 3 个涉及权限/越权、5 个集中在编辑路径校验、3 个在提醒/扫描链路。

## 二、幸存者分类

### A. 等价变异体（约 130 个，不需要补测试）

| 模式 | 数量（约） | 说明 |
|---|---|---|
| help_text / verbose_name / choices 显示文本 / required 标签 / 错误消息文案（XX包裹类） | ~75 | 展示层文案，stable_contract 断言 error 存在但不比对精确文案（合理，文案断言脆弱） |
| max_length ±1 / null / blank / default 翻转 | ~40 | 测试库 schema 由 migration 建立而非 models.py；blank 只影响未使用的表单校验；测试构造数据总是显式传值 |
| CheckConstraint / Index / UniqueConstraint / related_name 字符串变异 | ~28 | 约束在测试库中来自 migration 定义；无反向查询使用 related_name |
| 日志文本 / 返回 dict 键 / 审计 detail 键（tasks.py 部分） | ~8 | 无断言覆盖，行为不变 |
| created_by/updated_by 显示 fallback（`or`→`and`、else 'XXXX'） | ~5 | created_by 非空 FK，else 分支不可达；测试用户总有 nickname |

### B. 真实测试盲区（已补测试并红-绿验证，2026-09-21）

**P1 权限与越权（2 项已补）**

| 变异体 | 位置 | 问题 | 补充测试 | 验证 |
|---|---|---|---|---|
| M612 | AttachmentPreviewUrlView.get | `@auth(view)` 装饰器被整体删除后幸存——无权限用户请求预览令牌被拒的行为无测试 | `test_preview_url_denied_exact_message`（精确断言装饰器层统一文案『权限拒绝』） | KILLED |
| M407 | AgreementView.post | `@auth(add\|edit)` 装饰器删除后幸存（handler 有 has_perms 兜底，但文案不同） | `test_create_denied_by_auth_decorator_exact_message` | KILLED |

**P2 编辑路径校验缺口（3 项已补，全部是「新增有测试、编辑没有」的不对称）**

| 变异体 | 位置 | 问题 | 补充测试 | 验证 |
|---|---|---|---|---|
| M437 | _validate_edit_form | 字段长度校验被整体跳过后幸存——超长字段测试只覆盖新增路径 | `test_edit_overlong_fields_rejected`（精确文案 + 无告警断言） | KILLED |
| M486 | _post_edit | 编辑路径责任人校验（存在性/租户一致性）被跳过后幸存；responsible_user_id 是普通整型列无外键约束 | `test_edit_validates_responsible_user`（不存在 + 跨租户 + DB 不被改动） | KILLED |
| M453 | _validate_edit_form | 编辑路径日期边界 `>` → `>=` 幸存（新增路径已杀）——start==end 在编辑路径的行为未固定 | `test_edit_allows_equal_start_and_end_dates` | KILLED |

**P3 提醒与扫描链路（4 项已补）**

| 变异体 | 位置 | 问题 | 补充测试 | 验证 |
|---|---|---|---|---|
| M654 | ReminderPopupView | ack 去重 `continue` → `break`：已确认合同排前面时其后未确认合同从提醒列表消失（行为缺陷类） | `test_ack_skips_only_acked_and_keeps_remaining_records` | KILLED |
| M652 | ReminderPopupView | 提醒列表 days_left 计算被删后幸存 | 同上用例断言 days_left 真实值 | KILLED |
| M690 | ReminderAckView | `status == 'normal'` 短路变异后幸存——normal 合同确认应被拒且不落确认记录 | `test_ack_normal_contract_refused` | KILLED |
| M739 | scan_single_contract_agreement | 显式 today 注入被变异后幸存——固定日期扫描的确定性未测 | `test_scan_single_respects_explicit_today`（today=+300 天应判 expired） | KILLED |

**P4 列表查询与杂项（低优先级）**

- M652：提醒列表 days_left 值未断言（M690：normal 合同 ack 应被拒也未测）
- M342/M353/M355：列表无筛选参数全量查询、valid_start_to 范围过滤完全未测
- M379/M381：has_fee 过滤 '1'/'yes' 取值未测（仅 'true'）
- M592：附件上传响应 previewable 标志未断言
- M147：ReminderAck 默认管理器（.objects 租户过滤）未测——测试走 related manager 路径
- 响应契约键（M258~277、M587~593、M657~671 等 ~20 个）：detail/records 响应多个键未断言，可在现有用例中一次性补齐

### C. 存疑（不建议按缺口处理）

- M217/M717：`getattr(request_user, 'is_supper', False→True)`——User 模型总有该属性，实践等价；仅当未来出现缺属性的 mock 用户时才会静默放行
- M509：`save_fields = None`（update_fields 失效→全字段保存）——并发覆盖不变量，单线程测试无法杀死；与已知 P2 遗留（ATOMIC_REQUESTS/GET_LOCK 窗口）同属并发面
- M511/512：reminder_acks_reset 计数初值变异——仅审计 detail 数值，无 reset 场景未断言

### D. 补测阶段重分类为等价的变异体（原判「真盲区」，源码细读后推翻）

| 变异体 | 原判断 | 重分类依据 |
|---|---|---|
| M252 | 附件归属校验 or→and | `AttachmentService.get_preview_url`（attachment_service.py:414「仍强制校验 module / object_type」）与下载路径均做同文案复检——视图层校验是双层防御的内层，变异被外层兜住，行为不变。已补 `test_same_module_wrong_object_type_rejected` 作为该防御层的契约测试（无法杀变异体但防止未来两层同拆） |
| M448 | 编辑转长期有效置空路径 | `_post_edit` 第 443 行在期限切换时**另行显式** `update_data['valid_end_date'] = None`；_validate_edit_form 中的局部 `valid_end_date = None` 在 long_term 分支是死变量 |
| M493 | 编辑排除 fee_amount 键 | `_validate_edit_form` 两个分支都必设 `fee_updates['fee_amount']`，第 439 行 `update_data.update(fee_updates)` 必然覆盖客户端残留值——排除键是冗余保护 |
| M749 | 编辑后响应 status | `_serialize_agreement` 第 168 行自行 `resolve_agreement_status` 重算，从不读内存对象的 status——扫描后的内存同步在现有调用链是死代码 |
| M763 | Celery 任务从未被测 | 判断有误：`test_scan_all_task_updates_all`/`test_scan_all_task_is_repeatable` 已直调 `.apply()`；M763 幸存是因为 `calculate_agreement_status` 自带 `today is None → date.today()` 兜底，任务体 `today=None` 变异行为不变 |

## 三、结论与后续

1. **整体结论：PASS**。初轮 67.9% + 补测后 69.1%；541 个被杀变异体证明核心业务规则（新增校验、状态机、长期有效、费用文本化、租户过滤、附件双层归属校验）有真实杀伤力。
2. **已补 9 个 stable_contract 测试**（覆盖 9 个变异体，套件 215→224 个，耗时 +0.4 秒），全部经 `mutmut apply` 红-绿验证确认杀伤（`quality/reports/mutation/verify_kills.sh` 可复现）。
3. 修正后仍幸存 242 个，主体为等价变异体（约 135 个：文案/schema 由 migration 定/双层防御/死代码）与 P4 杂项（列表查询边角、响应契约键）；P4 若要继续收，可在现有用例中补断言，收益递减。
4. 幸存者明细见 `survivors_full.txt`（251 个 diff 全文）、清单见 `results.txt`、可浏览报告见 `index.html`。

## 四、复现方式

```bash
# 续跑/重跑（缓存复用）
wsl bash -c "cd /mnt/e/TDYW/spug-3.0 && ~/.local/bin/mutmut run --use-coverage"
# 查看幸存者
wsl bash -c "cd /mnt/e/TDYW/spug-3.0 && ~/.local/bin/mutmut results"
# 单个变异体 diff
wsl bash -c "cd /mnt/e/TDYW/spug-3.0 && ~/.local/bin/mutmut show 654"
```

配置：根目录 `setup.cfg` [mutmut] 段；runner 包装脚本 `quality/reports/mutation/mutmut_runner.sh`（服务就绪门禁 + 重启感知重试）；进度速览 `progress.sh`。`.mutmut-cache`、`.coverage` 已加入 .gitignore。

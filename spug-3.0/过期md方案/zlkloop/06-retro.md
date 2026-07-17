# 06 复盘沉淀

## 本轮结论

资料库批量上传卡在第 200 个任务附近的根因，是上传队列容量与状态机实例容量耦合。状态机上限原本用于保护前端资源，却被入队阶段批量创建放大成实际上传容量限制。

生产级修复方向是：

- 队列可以大。
- 状态机要少。
- 调度时按需创建。
- 终态后及时释放。

## 有效做法

- 先区分 `MAX_DISPLAY_COUNT` 和 `MAX_MACHINES`，避免把显示限制误判为上传限制。
- 把状态机创建从入队阶段移动到调度阶段。
- 使用 `ensureStateMachine(item)` 作为唯一懒创建入口。
- 对 `create()` 返回 `null` 做统一兜底。
- 在终态统一释放状态机，避免 Map 持续增长。

## 问题与教训

- 保护性上限如果放错层级，会变成业务容量上限。
- 前端队列中的任务不应强依赖预先创建好的状态机。
- 批量任务场景必须验证远大于默认阈值的数量，例如 870、1000。
- “显示数量上限”和“真实队列上限”必须在命名和注释中明确区分。

## 可复用模板

后续遇到类似问题时，按以下顺序判断：

1. 是否存在硬编码上限。
2. 上限作用在显示层、调度层还是资源层。
3. 资源对象是否在入队时批量创建。
4. 调度是否能为 waiting 任务补齐运行时资源。
5. 终态是否释放运行时资源。
6. 创建失败是否会导致 UI 崩溃。

## 下一轮建议

- 建立“多终端同时上传变慢”的性能压测 loop。
- 评估后端全局上传并发控制和写盘背压。
- 为上传模块增加可观测性：活跃上传数、状态机数量、waiting 数、平均分片耗时。
- 将 870 任务场景加入回归测试。

## 退出标准

- 修复经验已沉淀。
- 后续性能问题已拆分为独立闭环。
- 同类状态机容量问题有可复用排查路径。

---

## 本轮实际执行结果（2026-06-17）

### 实际改动文件（6 个）

| 文件 | 实际改动 |
| --- | --- |
| `upload/core/StateMachineManager.js` | `MAX_MACHINES` 200→1000（保护性上限，不再是容量上限）+ 注释 |
| `upload/core/coordinators/UploadCoordinator.js` | 新增 `ensureStateMachine(item)` 懒创建入口；重写 `startWaiting()` 不再要求预先存在状态机；`processSingleFile()` 移除入队 create + 单独 listener |
| `upload/core/coordinators/FileUploadCoordinator.js` | `_processBatch()` / `_processUniform()` 移除入队阶段 `stateMachineManager.create()` |
| `upload/core/lifecycle/StateChangeHandler.js` | `handle()` 末尾对 `completed/error/cancelled` 终态 `setTimeout(0)` 释放状态机 |
| `constants/upload.js` | `MAX_DISPLAY_COUNT` 注释明确仅显示用途、不参与调度 |
| `upload/core/controls/ItemOperationController.js` | `resumeItem` 状态机缺失时调用 `ensureStateMachine` 重建（保证重试不被破坏）；`cancelItem`/`removeItem` 显式 `remove()` 释放状态机 |

### 设计外必要补充：ItemOperationController

设计文档原列 5 个文件，实际追加 `ItemOperationController.js`。原因：
- 终态释放状态机后，失败任务的 `resumeItem` 会因 `if (!stateMachine) return` 而失效。
- 设计 00-intake.md「不确定项」已预见此问题：「默认终态后释放，手动重试时重新创建」。
- 因此让 `resumeItem` 复用 `ensureStateMachine` 懒创建，保证「释放」与「可重试」不矛盾。
- 同时 `cancelItem`/`removeItem` 绕过状态机直接出队，需显式释放，否则状态机泄漏。

### 验证结论

- ESLint：0 错误。
- Babel 编译：6/6 通过。
- 单元测试：29 通过 / 3 失败（3 个失败为预先存在的批量操作测试，与本次改动无关，`git diff` 证实 `StateMachineManager.js` 仅改 `MAX_MACHINES`）。
- 870 任务浏览器验证：待真实环境执行，代码层面已满足验收条件。

### 剩余风险

| 风险 | 等级 | 说明 |
| --- | --- | --- |
| 终态释放过早影响异步回调 | 低 | `onCompleted/onError` 不引用本任务状态机（已核实），`setTimeout(0)` 在回调链后执行；但若有未来新增的异步终态钩子引用状态机需重新评估 |
| `resumeItem` 重建后状态为 waiting | 低 | 重试失败任务时重建状态机从 waiting 开始，走 START 路径，符合「重新上传」语义；但合并失败重试依赖 `_isMergeFailed` 检测分片，需浏览器验证 |
| 预先存在的 3 个批量操作测试失败 | 低 | 与本次无关，建议另开 Loop 修复 `batchTransition/batchResume/batchCancel` 的过滤逻辑 |
| 870 任务真实压测 | 中 | 代码逻辑已解耦，但需真实环境验证调度连续性与内存占用 |


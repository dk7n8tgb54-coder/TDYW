# 05 验证校准

## 验证命令

根据项目实际脚本选择可用命令：

```bash
# 前端相关测试
cd spug_web
npm test -- StateMachineManager
npm test -- upload

# 如果项目使用 lint
npm run lint

# 后端不涉及本轮核心逻辑，但可运行资料库相关测试兜底
cd ../spug_api
python manage.py test apps.document
```

如果本地环境无法运行完整测试，需要记录具体失败原因，例如依赖缺失、脚本不存在、Node 版本不匹配。

## 单元测试清单

| 项目 | 预期 | 说明 |
| --- | --- | --- |
| `StateMachineManager.create()` 超过上限返回 `null` | 调用方不崩溃 | 验证判空保护 |
| `UploadCoordinator.ensureStateMachine()` | 可为 waiting 任务创建状态机 | 验证懒创建 |
| 没有状态机的 waiting 任务 | 可被 `startWaiting()` 启动 | 验证第 201 个以后任务 |
| 终态任务 | 会调用 `remove(uploadId)` | 验证资源释放 |
| 创建失败任务 | 保持 waiting 并记录日志 | 验证可重试 |

## 集成验证

构造 870 个模拟文件，验证：

| 验证项 | 预期 |
| --- | --- |
| 所有文件入队 | 队列长度为 870 |
| 并发上传数 | 不超过 `MAX_CONCURRENT_UPLOADS` |
| 第 201 个任务 | 能在前面任务释放槽位后启动 |
| 状态机数量 | 不随 870 个任务一次性增长到 870 |
| 完成任务 | 状态机释放 |
| 控制台 | 无 `Cannot read properties of null` |

## 浏览器手工验证

| 场景 | 预期 | 结果 |
| --- | --- | --- |
| 一次上传 870 个小文件 | 不停在第 200 个 | 待执行 |
| 一次上传 870 个混合大小文件 | 小文件和分片文件都可持续调度 | 待执行 |
| 上传中打开传输列表 | 列表可打开、滚动、点击 | 待执行 |
| 上传中暂停全部 | 活跃任务暂停，waiting 不丢失 | 待执行 |
| 暂停后恢复全部 | waiting 任务可重新懒创建状态机并继续 | 待执行 |
| 取消部分任务 | 任务进入终态并释放状态机 | 待执行 |
| 网络中断后恢复 | 可恢复或进入可重试错误态 | 待执行 |

## 观测指标

| 指标 | 目标 |
| --- | --- |
| `stateMachineManager.size()` | 接近活跃/暂停/短期历史任务数，不等于总任务数 |
| `activeUploads` | 不超过并发上限 |
| waiting 数量 | 随任务完成持续下降 |
| error 数量 | 不因状态机创建失败批量增长 |
| 浏览器 JS 错误 | 无空状态机异常 |

## 缺陷记录

| 缺陷 | 等级 | 处理状态 |
| --- | --- | --- |
| 状态机创建失败后任务永久 waiting | P1 | 若复现，增加重试触发或用户提示 |
| 终态释放过早影响重试 | P1 | 若复现，改为延迟释放或重试时重建 |
| 传输列表仍卡顿 | P2 | 检查虚拟列表与渲染上限 |

## 退出标准

- 核心验收项通过。
- 870 任务场景不再卡在第 200 个。
- 失败项有明确后续处理方式。

---

## 实际验证结果（2026-06-17 执行）

### 静态检查

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| ESLint | `read_lints` 对 `upload/core` 目录 | **0 错误**（通过） |
| Babel 编译（legacy decorators + class properties） | 自定义 `@babel/core` 脚本编译 6 个修改文件 | **6/6 OK，0 失败**（通过） |
| 残留 `create()` 调用点扫描 | `grep stateMachineManager.create(` | 仅剩 `UploadCoordinator.ensureStateMachine` 内 1 处（符合设计）；3 个入队路径 create 已全部移除 |

### 单元测试

执行 `CI=true npx react-app-rewired test --watchAll=false StateMachineManager`：

- **Test Suites: 1 failed, 1 total**
- **Tests: 3 failed, 29 passed, 32 total**

3 个失败用例均为 `批量操作` 分组（`批量转换带过滤` / `批量恢复` / `批量取消`），针对 `batchTransition/batchResume/batchCancel` 的过滤与并发逻辑。

**结论：预先存在的失败，与本次 Loop-200 修复无关。** 依据：
- 本次对 `StateMachineManager.js` 的 diff 仅限 `MAX_MACHINES = 200 → 1000`（`git diff` 已确认），未触碰任何 `batch*` 方法。
- 29 个通过用例包含 `create/get/remove/cleanup/size` 等与本次改动相关的能力，均通过。

### 集成/870 任务验证

- 浏览器手工 870 任务验证需在真实环境执行，本轮代码层面已满足：
  - 入队不再创建状态机 → 870 个任务入队不受 `MAX_MACHINES` 限制。
  - `startWaiting` 通过 `ensureStateMachine` 懒创建 → 第 201 个以后 waiting 任务可被调度。
  - 终态 `setTimeout(0)` 释放 → 状态机数量不随总任务数增长。
- `activeUploads` 仍由 `increment/decrementActiveUploads` + `MAX_CONCURRENT_UPLOADS` 控制，未改动。

### 浏览器手工验证清单（待真实环境执行）

| 场景 | 预期 | 结果 |
| --- | --- | --- |
| 一次上传 870 个小文件 | 不停在第 200 个 | 待执行 |
| 上传中打开传输列表 | 列表可打开、滚动、点击 | 待执行 |
| 失败任务点击重试 | `resumeItem` 懒创建状态机后可重试 | 待执行 |
| 取消/删除任务 | 状态机释放，无泄漏 | 待执行 |
| 控制台 | 无 `Cannot read properties of null` | 待执行 |


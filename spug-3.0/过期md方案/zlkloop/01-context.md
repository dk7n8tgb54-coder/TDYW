# 01 现状读取

## 仓库结构

本轮聚焦资料库前端上传模块：

```text
spug_web/src/pages/document/stores/
  constants/upload.js
  upload/core/StateMachineManager.js
  upload/core/coordinators/FileUploadCoordinator.js
  upload/core/coordinators/UploadCoordinator.js
  upload/core/lifecycle/StateChangeHandler.js
  upload/core/queue.js
```

相关方案文档：

```text
批量上传200任务卡住修复方案.md
资料库代码改造/批量上传200任务卡住修复方案.md
```

## 当前行为

1. 用户一次选择大量文件。
2. `FileUploadCoordinator` 将所有文件加入前端上传队列。
3. 入队过程中立即为每个文件调用 `stateMachineManager.create(uploadId, context)`。
4. `StateMachineManager` 最多允许 200 个状态机实例。
5. 超过上限后 `create()` 返回 `null`。
6. `UploadCoordinator.startWaiting()` 只启动已经存在状态机且可 `START` 的 waiting 任务。
7. 没有状态机的 waiting 任务永远不会被启动。

## 可复用能力

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 上传队列 | `upload/core/queue.js` | 已按租户维护队列，可继续承载大量 waiting 任务 |
| 上传调度 | `UploadCoordinator.js` | 可作为懒创建状态机的统一入口 |
| 状态机管理 | `StateMachineManager.js` | 已提供 `create/get/remove/cleanup/size` |
| 终态处理 | `StateChangeHandler.js` | 可统一释放状态机 |
| 显示配置 | `constants/upload.js` | `MAX_DISPLAY_COUNT` 只应影响显示，不参与调度 |

## 技术约束

- 前端并发上传数由 `MAX_CONCURRENT_UPLOADS` 控制，默认值为 3。
- 状态机负责状态流转，上传业务由生命周期处理器触发。
- waiting 队列可能远大于可并发上传数。
- 批量上传任务数不应等于状态机实例数。
- 状态机创建失败不能导致 UI 或调度流程崩溃。

## 风险识别

| 风险 | 说明 | 规避方式 |
| --- | --- | --- |
| 空状态机异常 | `create()` 返回 `null` 后继续调用方法 | 所有创建点判空 |
| waiting 任务丢调度 | 没有状态机就被过滤 | 调度时调用 `ensureStateMachine(item)` |
| 状态机泄漏 | 任务完成后仍留在 Map 中 | 终态统一释放 |
| UI 显示限制误伤队列 | `MAX_DISPLAY_COUNT` 被用于真实队列截断 | 明确只用于渲染层 |

## 与当前方案的关系

本轮采用《批量上传200任务卡住修复方案.md》中的生产级方案：队列不受状态机数量限制，状态机懒创建，终态及时释放，定时 cleanup 仅作为兜底。

## 退出标准

- 已识别 200 卡住的关键链路。
- 已识别可以复用的队列、调度、状态机、生命周期能力。
- 已确认生产级方向是懒创建而不是单纯调大 `MAX_MACHINES`。

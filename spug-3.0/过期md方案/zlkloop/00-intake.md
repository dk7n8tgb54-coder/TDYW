# 00 任务接收

## 原始需求

根据《批量上传200任务卡住修复方案.md》，对资料库上传模块执行 Loop Engineering 改造，解决一次上传 870 个任务时在第 200 个附近停止调度、传输列表无响应的问题。

## 问题摘要

批量上传大量文件时，前端上传队列可以继续追加任务，但上传状态机存在 `MAX_MACHINES = 200` 的硬上限。超过上限后 `StateMachineManager.create()` 可能返回 `null`，而部分调用方没有判空，导致后续 waiting 任务没有状态机、无法被调度，甚至触发前端异常。

## 目标摘要

- 支持一次性选择 800、1000 或更多文件进入上传队列。
- 上传调度不再受 200 个状态机实例上限阻断。
- 状态机改为按需创建，任务完成、失败、取消后及时释放。
- 所有 `stateMachineManager.create()` 调用点具备空值兜底。
- 上传并发仍受 `MAX_CONCURRENT_UPLOADS` 控制，不因批量任务数扩大而失控。
- 传输列表可正常打开、滚动、点击，不因状态机异常卡死。

## 范围边界

### 本轮要做

- 改造前端上传状态机创建策略。
- 调整 `UploadCoordinator.startWaiting()`，允许没有状态机的 waiting 任务被懒创建并启动。
- 从入队流程中移除批量状态机创建。
- 在终态后释放状态机。
- 补充必要日志和判空保护。
- 补充或更新 870 个任务级别的验证用例。

### 本轮不做

- 不改后端上传协议。
- 不改文件分片大小策略。
- 不改数据库表结构。
- 不处理多终端上传整体慢的问题，该问题另开性能压测闭环。
- 不做 UI 大改版，只保证传输列表稳定可用。

## 关键输入

| 输入 | 位置 | 说明 |
| --- | --- | --- |
| 修复方案 | `批量上传200任务卡住修复方案.md` | 本轮主依据 |
| 状态机管理器 | `spug_web/src/pages/document/stores/upload/core/StateMachineManager.js` | 存在 `MAX_MACHINES = 200` |
| 上传调度器 | `spug_web/src/pages/document/stores/upload/core/coordinators/UploadCoordinator.js` | waiting 任务调度入口 |
| 文件入队逻辑 | `spug_web/src/pages/document/stores/upload/core/coordinators/FileUploadCoordinator.js` | 当前入队时批量创建状态机 |
| 状态变化处理 | `spug_web/src/pages/document/stores/upload/core/lifecycle/StateChangeHandler.js` | 适合统一释放终态状态机 |

## 不确定项

| 问题 | 影响 | 处理方式 |
| --- | --- | --- |
| 失败任务是否需要保留状态机用于立即重试 | 影响终态释放时机 | 默认终态后释放，手动重试时重新创建 |
| UI 是否依赖状态机历史记录 | 影响释放延迟 | 若需要历史信息，则延迟 30-60 秒释放 |
| 现有测试是否能直接运行 | 影响验证效率 | 先运行相关前端测试，失败时记录环境问题 |

## 退出标准

- 已明确本轮修复目标和非目标。
- 已明确关键文件和改造边界。
- 已明确验收口径：870 个任务不在第 200 个停止。

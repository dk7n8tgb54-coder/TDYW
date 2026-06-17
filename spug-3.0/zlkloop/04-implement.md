# 04 实现落地

## 实现范围

本阶段用于记录实际代码改造结果。执行时按以下清单逐项落地，不跳步。

## 文件变更

| 文件 | 变更说明 |
| --- | --- |
| `spug_web/src/pages/document/stores/upload/core/StateMachineManager.js` | 保留上限保护，增强创建失败日志；可短期将 `MAX_MACHINES` 提高到 1000 或 2000 |
| `spug_web/src/pages/document/stores/upload/core/coordinators/FileUploadCoordinator.js` | `_processBatch()`、`_processUniform()` 入队时不再批量创建状态机 |
| `spug_web/src/pages/document/stores/upload/core/coordinators/UploadCoordinator.js` | 新增 `ensureStateMachine(item)`，`startWaiting()` 调度时懒创建状态机 |
| `spug_web/src/pages/document/stores/upload/core/lifecycle/StateChangeHandler.js` | completed/error/cancelled 后释放状态机 |
| `spug_web/src/pages/document/stores/constants/upload.js` | 注释明确 `MAX_DISPLAY_COUNT` 只用于显示 |

## 关键实现步骤

### 1. 状态机创建失败保护

所有 `stateMachineManager.create()` 调用点必须改成：

```js
const stateMachine = this.core.stateMachineManager?.create(uploadId, context);

if (!stateMachine) {
  console.error('[Upload] 状态机创建失败', {
    uploadId,
    machineCount: this.core.stateMachineManager?.size?.(),
    activeUploads: this.core.activeUploads,
  });
  return;
}
```

如果后面需要 `stateMachine.addListener(...)`，必须放在判空之后。

### 2. 入队流程不创建状态机

保留：

```js
this.core.queueStore.addToQueue(item, tenantId);
```

移除：

```js
this.core.stateMachineManager.create(uploadId, context);
```

说明：

- 队列 item 仍需保留 `file`、`folderId`、`isPublic`、`transferId`、`fileHash` 等字段。
- 这些字段会在 `ensureStateMachine(item)` 中作为 context 来源。

### 3. 调度时懒创建

在 `UploadCoordinator` 中新增：

```js
ensureStateMachine(item) {
  let stateMachine = this.core.stateMachineManager?.get(item.id);
  if (stateMachine) return stateMachine;

  stateMachine = this.core.stateMachineManager?.create(item.id, {
    queueStore: this.core.queueStore,
    transferStore: this.core.transferStore,
    md5Store: this.core.md5Store,
    file: item.file,
    folderId: item.folderId,
    item,
  });

  if (!stateMachine) {
    console.error('[UploadCoordinator] 状态机创建失败', {
      uploadId: item.id,
      name: item.name,
      machineCount: this.core.stateMachineManager?.size?.(),
      activeUploads: this.core.activeUploads,
    });
    return null;
  }

  return stateMachine;
}
```

### 4. 改造 `startWaiting()`

将 waiting 任务筛选从“必须已有状态机”改成“调度时确保状态机”：

```js
const waitingItems = queue.filter(item => item.status === 'waiting');

for (const item of waitingItems) {
  if (startedCount >= availableSlots) break;

  const stateMachine = this.ensureStateMachine(item);
  if (!stateMachine) continue;

  if (stateMachine.canTransition('START')) {
    stateMachine.transition('START');
    startedCount++;
  }
}
```

### 5. 终态释放

在 `StateChangeHandler.handle()` 中处理：

```js
if (['completed', 'error', 'cancelled'].includes(toState)) {
  setTimeout(() => {
    this.core.stateMachineManager?.remove(uploadId);
  }, 0);
}
```

建议放在终态分支处理完成之后，避免当前回调流程中途失去状态机。

## 关键决策

| 决策 | 原因 | 影响 |
| --- | --- | --- |
| 不再入队时批量创建状态机 | 防止 870 个任务瞬间占满状态机上限 | 根除第 200 个任务卡住 |
| 调度时懒创建 | 只为即将运行的任务创建状态机 | 降低内存与状态机压力 |
| 终态释放 | 防止状态机 Map 无限增长 | 长批量任务更稳定 |
| 创建失败保持 waiting | 避免临时资源不足导致任务永久失败 | 后续调度仍可重试 |

## 未完成项记录

| 项目 | 原因 | 后续处理 |
| --- | --- | --- |
| 多终端上传慢 | 属于性能容量问题，不是本轮状态机 bug | 新建压测 loop |
| 后端全局上传限流 | 需要压测数据支撑 | 性能闭环中评估 |
| UI 虚拟列表优化 | 当前问题不由 UI 渲染引起 | 如仍卡顿再处理 |

## 退出标准

- 代码已按 T1-T5 完成。
- waiting 任务可懒创建状态机并启动。
- 终态状态机可释放。
- 所有创建失败路径有日志和兜底。

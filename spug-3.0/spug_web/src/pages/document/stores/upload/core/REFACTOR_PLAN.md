# UploadCoreStore 重构拆分方案

## 1. 现状分析

### 1.1 当前文件规模
- **index.js**: ~1630 行
- **职责混杂**: 组合逻辑 + 状态机协调 + 任务调度 + 网络管理 + 防抖控制 + 状态同步

### 1.2 现有架构
```
core/
├── index.js                 # 主文件（1630行，过于臃肿）
├── queue.js                 # 队列管理（已拆分）
├── fileUpload.js            # 普通文件上传（已拆分）
├── chunkUpload.js           # 分片上传（已拆分）
├── folderUpload.js          # 文件夹上传（已拆分）
├── md5.js                   # MD5计算（已拆分）
├── transfer.js              # 传输记录（已拆分）
└── StateMachineManager.js   # 状态机管理（已拆分）
```

### 1.3 核心问题
1. **单一文件职责过多**: index.js 同时处理协调、调度、网络、同步等
2. **方法过长**: `processUploadQueue` (~200行), `onStateChange` (~100行)
3. **内聚性低**: 防抖逻辑、网络监听、状态同步混杂在一起
4. **可测试性差**: 难以单独测试某个功能模块

---

## 2. 目标架构

### 2.1 拆分后结构
```
core/
├── index.js                          # 仅保留组合逻辑和API入口 (~200行)
├── StateMachineManager.js            # 状态机管理（不变）
├── constants.js                      # 核心常量提取
│
├── coordinators/                     # 协调器层 - 负责任务调度
│   ├── index.js                      # 统一导出
│   ├── UploadCoordinator.js          # 上传任务协调（processUploadQueue）
│   ├── DisplayCoordinator.js         # 显示队列协调（replenishDisplayQueue）
│   └── RecoveryCoordinator.js        # 恢复协调（schedulePendingUploadsRecovery）
│
├── lifecycle/                        # 生命周期层 - 负责状态变更处理
│   ├── index.js                      # 统一导出
│   ├── StateChangeHandler.js         # 状态变更处理（onStateChange）
│   ├── UploadLifecycle.js            # 上传生命周期（onUploadCompleted/onUploadError）
│   └── NetworkLifecycle.js           # 网络生命周期（在线/离线处理）
│
├── controls/                         # 控制层 - 负责防抖、并发控制
│   ├── index.js                      # 统一导出
│   └── DebounceController.js         # 防抖控制器
│
├── sync/                             # 同步层 - 负责前后端状态同步
│   ├── index.js                      # 统一导出
│   └── StatusSynchronizer.js         # 状态同步器
│
└── utils/                            # 工具层
    └── index.js                      # 统一导出
```

### 2.2 职责划分

| 层级 | 职责 | 文件 |
|-----|------|------|
| **API层** | 对外暴露统一接口，组合各模块 | `index.js` |
| **协调器层** | 任务调度、队列管理、并发控制 | `coordinators/*.js` |
| **生命周期层** | 状态变更回调、事件处理 | `lifecycle/*.js` |
| **控制层** | 防抖、限流、开关控制 | `controls/*.js` |
| **同步层** | 前后端状态同步、数据一致性 | `sync/*.js` |

---

## 3. 详细拆分方案

### 3.1 新建文件

#### 3.1.1 `core/constants.js`
提取核心常量，避免重复定义。

```javascript
/**
 * UploadCore 常量定义
 */

// 并发控制
export const MAX_CONCURRENT_UPLOADS = 3;

// 分片上传阈值
export const NORMAL_UPLOAD_THRESHOLD = 32 * 1024 * 1024; // 32MB（与实际代码一致）

// 批量警告阈值
export const BATCH_WARNING_THRESHOLD = 100;

// 清理配置
export const CLEANUP_INTERVAL = 30000;           // 30秒
export const COMPLETED_ITEM_MAX_AGE = 5 * 60000; // 5分钟
export const STATE_MACHINE_CLEANUP_INTERVAL = 60000; // 1分钟

// 状态映射
export const BACKEND_STATUS_MAP = {
  'UPLOADING': 'uploading',
  'PAUSED': 'paused',
  'MERGING': 'merging',
  'COMPLETED': 'completed',
  'FAILED': 'error',
  'CANCELED': 'cancelled',
  'PENDING': 'waiting',
};

// 终态集合
export const FINAL_STATES = ['completed', 'error', 'cancelled'];

// 活跃状态集合
export const ACTIVE_STATES = ['calculating', 'uploading', 'merging'];
```

#### 3.1.2 `core/coordinators/UploadCoordinator.js`
负责上传任务的调度和执行。

**迁移方法**:
- `processUploadQueue()` - 核心调度方法
- `startWaitingTasks()` - 启动等待任务
- `processPendingUploads()` - 处理待上传任务

**依赖**:
- `queueStore` - 队列操作
- `stateMachineManager` - 状态机管理
- `fileUploadStore` - 普通文件上传
- `chunkUploadStore` - 分片上传

#### 3.1.3 `core/coordinators/DisplayCoordinator.js`
负责传输列表的显示队列管理。

**迁移方法**:
- `replenishDisplayQueue()` - 补充显示队列

**依赖**:
- `queueStore` - 队列操作

#### 3.1.4 `core/coordinators/RecoveryCoordinator.js`
负责任务恢复和重试机制。

**迁移方法**:
- `schedulePendingUploadsRecovery()` - 调度恢复
- `recoverStuckUploads()` - 恢复卡住的传输

**依赖**:
- `queueStore` - 队列操作
- `stateMachineManager` - 状态机管理

#### 3.1.5 `core/lifecycle/StateChangeHandler.js`
负责处理状态机状态变更。

**迁移方法**:
- `onStateChange()` - 状态变更回调
- `handlePausedState()` - 处理暂停状态
- `handleCompletedState()` - 处理完成状态
- `handleWaitingState()` - 处理等待状态

**依赖**:
- `queueStore` - 更新队列项状态
- `stateMachineManager` - 状态机查询

#### 3.1.6 `core/lifecycle/UploadLifecycle.js`
负责上传生命周期事件处理。

**迁移方法**:
- `onUploadCompleted()` - 上传完成处理
- `onUploadError()` - 上传错误处理
- `onStateCalculating()` - 计算状态处理
- `cleanupAfterUpload()` - 上传后清理

**依赖**:
- `queueStore` - 队列操作
- `displayCoordinator` - 触发队列补充
- `uploadCoordinator` - 启动等待任务

#### 3.1.7 `core/lifecycle/NetworkLifecycle.js`
负责网络状态变化处理。

**迁移方法**:
- `initNetworkListener()` - 初始化网络监听
- `handleOffline()` - 离线处理
- `handleOnline()` - 在线处理

**依赖**:
- `queueStore` - 暂停/恢复任务

#### 3.1.8 `core/controls/DebounceController.js`
负责防抖控制逻辑。

**迁移方法**:
- `debouncePauseAll()` - 暂停全部防抖
- `debounceResumeAll()` - 恢复全部防抖
- `debounceItemOperation()` - 单任务操作防抖
- `cleanupDebounceTimers()` - 清理防抖定时器

**依赖**: 无外部Store依赖

#### 3.1.9 `core/sync/StatusSynchronizer.js`
负责前后端状态同步。

**迁移方法**:
- `syncTransferStatus()` - 同步传输状态
- `mapBackendStatus()` - 状态映射

**依赖**:
- `transferStore` - 获取后端状态
- `queueStore` - 更新前端状态

---

### 3.2 修改文件

#### 3.2.1 `core/index.js` 改造后结构

```javascript
/**
 * UploadCoreStore - 上传核心逻辑组合器
 * 职责：组合所有上传相关的子Store和协调器，提供统一的API
 */
import { observable, action } from 'mobx';
import { message } from 'antd';

// 子Store
import UploadQueueStore from './queue';
import FileUploadStore from './fileUpload';
import ChunkUploadStore from './chunkUpload';
import FolderUploadStore from './folderUpload';
import MD5Store from './md5';
import TransferStore from './transfer';

// 状态机
import { StateMachineManager } from './StateMachineManager';

// 协调器
import {
  UploadCoordinator,
  DisplayCoordinator,
  RecoveryCoordinator,
} from './coordinators';

// 生命周期
import {
  StateChangeHandler,
  UploadLifecycle,
  NetworkLifecycle,
} from './lifecycle';

// 控制器
import { DebounceController } from './controls';

// 同步器
import { StatusSynchronizer } from './sync';

class UploadCoreStore {
  // ===== 子Store实例 =====
  queueStore = null;
  fileUploadStore = null;
  chunkUploadStore = null;
  folderUploadStore = null;
  md5Store = null;
  transferStore = null;

  // ===== 状态机 =====
  stateMachineManager = null;

  // ===== 协调器 =====
  uploadCoordinator = null;
  displayCoordinator = null;
  recoveryCoordinator = null;

  // ===== 生命周期处理器 =====
  stateChangeHandler = null;
  uploadLifecycle = null;
  networkLifecycle = null;

  // ===== 控制器 =====
  debounceController = null;

  // ===== 同步器 =====
  statusSynchronizer = null;

  // ===== 全局状态 =====
  @observable isPaused = false;
  @observable isCancelled = false;
  
  // ===== 非observable =====
  cancelTokenSources = new Map();
  cleanupTimer = null;

  constructor(rootStore) {
    this.rootStore = rootStore;
    this._initStores();
    this._initStateMachine();
    this._initCoordinators();
    this._initLifecycleHandlers();
    this._initControllers();
    this._initSynchronizers();
    this._initGlobalListeners();
  }

  // ===== 初始化方法 =====
  _initStores() { /* ... */ }
  _initStateMachine() { /* ... */ }
  _initCoordinators() { /* ... */ }
  _initLifecycleHandlers() { /* ... */ }
  _initControllers() { /* ... */ }
  _initSynchronizers() { /* ... */ }
  _initGlobalListeners() { /* ... */ }

  // ===== 公共API（代理到各模块） =====
  
  // 队列操作 - 代理到 queueStore
  get uploadQueue() { return this.queueStore.uploadQueue; }
  get currentUploadQueue() { return this.queueStore.currentUploadQueue; }
  
  // 上传控制 - 代理到 uploadCoordinator
  async processUploadQueue() {
    return this.uploadCoordinator.processUploadQueue();
  }
  
  // 暂停/恢复 - 代理到 debounceController + queueStore
  async pauseAll() { /* ... */ }
  async resumeAll() { /* ... */ }
  
  // 状态同步 - 代理到 statusSynchronizer
  async syncTransferStatus(isPublic) {
    return this.statusSynchronizer.syncTransferStatus(isPublic);
  }
  
  // ... 其他公共API
}

export default UploadCoreStore;
```

---

## 4. 迁移映射表

### 4.1 方法迁移清单

| 原方法 | 原行数 | 目标文件 | 新类名 | 调用方式 |
|-------|-------|---------|-------|---------|
| `processUploadQueue` | ~200 | `coordinators/UploadCoordinator.js` | `UploadCoordinator.process()` | `this.uploadCoordinator.process()` |
| `startWaitingTasks` | ~50 | `coordinators/UploadCoordinator.js` | `UploadCoordinator.startWaiting()` | `this.uploadCoordinator.startWaiting()` |
| `processPendingUploads` | ~30 | `coordinators/UploadCoordinator.js` | `UploadCoordinator.processPending()` | `this.uploadCoordinator.processPending()` |
| `replenishDisplayQueue` | ~50 | `coordinators/DisplayCoordinator.js` | `DisplayCoordinator.replenish()` | `this.displayCoordinator.replenish()` |
| `schedulePendingUploadsRecovery` | ~50 | `coordinators/RecoveryCoordinator.js` | `RecoveryCoordinator.schedule()` | `this.recoveryCoordinator.schedule()` |
| `onStateChange` | ~100 | `lifecycle/StateChangeHandler.js` | `StateChangeHandler.handle()` | `this.stateChangeHandler.handle()` |
| `onUploadCompleted` | ~30 | `lifecycle/UploadLifecycle.js` | `UploadLifecycle.onCompleted()` | `this.uploadLifecycle.onCompleted()` |
| `onUploadError` | ~20 | `lifecycle/UploadLifecycle.js` | `UploadLifecycle.onError()` | `this.uploadLifecycle.onError()` |
| `onStateCalculating` | ~50 | `lifecycle/UploadLifecycle.js` | `UploadLifecycle.onCalculating()` | `this.uploadLifecycle.onCalculating()` |
| `initNetworkListener` | ~30 | `lifecycle/NetworkLifecycle.js` | `NetworkLifecycle.init()` | `this.networkLifecycle.init()` |
| `pauseAll` (防抖逻辑) | ~50 | `controls/DebounceController.js` | `DebounceController.pauseAll()` | `this.debounceController.pauseAll()` |
| `resumeAll` (防抖逻辑) | ~50 | `controls/DebounceController.js` | `DebounceController.resumeAll()` | `this.debounceController.resumeAll()` |
| `syncTransferStatus` | ~40 | `sync/StatusSynchronizer.js` | `StatusSynchronizer.sync()` | `this.statusSynchronizer.sync()` |
| `mapBackendStatus` | ~15 | `sync/StatusSynchronizer.js` | `StatusSynchronizer.mapStatus()` | `this.statusSynchronizer.mapStatus()` |

### 4.2 属性迁移清单

| 原属性 | 目标位置 | 说明 |
|-------|---------|------|
| `_pauseAllDebounceTimer` | `DebounceController` | 防抖定时器 |
| `_resumeAllDebounceTimer` | `DebounceController` | 防抖定时器 |
| `_itemDebounceTimers` | `DebounceController` | 单任务防抖Map |
| `_isPauseAllRunning` | `DebounceController` | 防抖状态标记 |
| `_isResumeAllRunning` | `DebounceController` | 防抖状态标记 |
| `_isItemOperationRunning` | `DebounceController` | 防抖状态Set |
| `_stateMachineCleanupTimer` | `StateMachineManager` | 移至状态机管理器 |
| `_lastSyncStatusMap` | `StatusSynchronizer` | 同步状态缓存 |
| `_handleOffline` | `NetworkLifecycle` | 离线处理器引用 |
| `_handleOnline` | `NetworkLifecycle` | 在线处理器引用 |

---

## 5. 实施步骤

### Step 1: 创建基础设施
1. 创建新目录结构
2. 创建 `constants.js` 提取常量
3. 创建各模块的 `index.js` 导出文件

### Step 2: 实现协调器层
1. 实现 `UploadCoordinator.js`
2. 实现 `DisplayCoordinator.js`
3. 实现 `RecoveryCoordinator.js`

### Step 3: 实现生命周期层
1. 实现 `StateChangeHandler.js`
2. 实现 `UploadLifecycle.js`
3. 实现 `NetworkLifecycle.js`

### Step 4: 实现控制和同步层
1. 实现 `DebounceController.js`
2. 实现 `StatusSynchronizer.js`

### Step 5: 重构主文件
1. 修改 `index.js` 使用新模块
2. 删除已迁移的方法
3. 验证所有公共API正常

### Step 6: 测试验证
1. 单元测试各模块
2. 集成测试上传流程
3. 回归测试边界场景

---

## 6. 预期效果

### 6.1 文件规模
| 文件 | 重构前 | 重构后 |
|-----|-------|-------|
| `index.js` | ~1630行 | ~200行 |
| `UploadCoordinator.js` | - | ~250行 |
| `DisplayCoordinator.js` | - | ~80行 |
| `RecoveryCoordinator.js` | - | ~100行 |
| `StateChangeHandler.js` | - | ~150行 |
| `UploadLifecycle.js` | - | ~120行 |
| `NetworkLifecycle.js` | - | ~60行 |
| `DebounceController.js` | - | ~150行 |
| `StatusSynchronizer.js` | - | ~80行 |
| **总计** | **~1630行** | **~1190行** |

### 6.2 收益
1. **单一职责**: 每个文件只负责一个明确的职责
2. **可测试性**: 各模块可以独立测试
3. **可维护性**: 定位问题更容易，修改影响范围可控
4. **可扩展性**: 新增功能只需在对应模块添加
5. **代码复用**: 协调器逻辑可以在其他场景复用

---

## 7. 风险与注意事项

### 7.1 潜在风险
1. **循环依赖**: 模块间调用需要小心处理依赖关系
2. **状态同步**: MobX observable 对象的跨模块引用需要保持一致
3. **this绑定**: 方法提取到类后需要正确处理this指向

### 7.2 注意事项
1. 保持公共API不变，避免影响上层组件
2. 每次迁移后运行测试验证
3. 保留原代码注释和关键日志
4. 注意MobX的@action装饰器在新类中的使用

---

## 8. 附录

### 8.1 模块依赖图

```
                    UploadCoreStore (index.js)
                           |
        +------------------+------------------+
        |                  |                  |
   queueStore      stateMachineManager    Coordinators
   fileUploadStore                        /      |      \
   chunkUploadStore         UploadCoordinator  DisplayCoordinator  RecoveryCoordinator
   folderUploadStore              |                  |                  |
   md5Store                       v                  v                  v
   transferStore          UploadLifecycle  StateChangeHandler  RecoveryCoordinator
                                 |                  |
                                 +------------------+                  
                                                    |
                                            DebounceController
                                            StatusSynchronizer
```

### 8.2 关键接口定义

```typescript
// UploadCoordinator 接口
interface IUploadCoordinator {
  process(): Promise<void>;
  startWaiting(): void;
  processPending(): void;
}

// StateChangeHandler 接口
interface IStateChangeHandler {
  handle(fromState: string, toState: string, event: string, payload: any, uploadId: string): void;
}

// DebounceController 接口
interface IDebounceController {
  pauseAll(): Promise<void>;
  resumeAll(): Promise<void>;
  itemOperation(uploadId: string, operation: () => Promise<void>): Promise<void>;
  cleanup(): void;
}
```

---

**方案制定日期**: 2026-03-29  
**预计实施工时**: 1-2天  
**建议优先级**: P2（重要不紧急，可在功能稳定后实施）

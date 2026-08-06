/**
 * UploadCoreStore - 上传核心逻辑组合器
 * 职责：组合所有上传相关的子Store和协调器，提供统一的API
 *
 * 【任务4.1】状态机与Store解耦改造
 * - 新增 EventBus 事件总线，替代隐式回调
 * - 新增 guards.js 和 actions.js 拆分状态机逻辑
 * - 新增 UploadStateMachineDecoupled 解耦版状态机
 * - 新增 StoreEventAdapter 连接事件总线与Store
 */
import { observable, action, computed } from 'mobx';
import {
  UPLOAD_CONSTANTS,
  UPLOAD_STATUS,
  DISPLAY_UPLOADING_STATUSES,
} from './upload-core-constants';
import { captureUploadTargetContext as captureUploadTargetContextFn } from './captureUploadTargetContext';

// 子Store
import UploadQueueStore from './queue';
import FileUploadStore from './fileUpload';
import ChunkUploadStore from './chunkUpload';
import FolderUploadStore from './folderUpload';
import MD5Store from './md5';
import TransferStore from './transfer';

// 状态机
import { StateMachineManager } from './StateMachineManager';
import { UploadStateMachine } from './UploadStateMachine';

// 【方向B 2026-06-27】已移除 EventBus/StoreEventAdapter/actions 解耦设施
// 原因：useDecoupledStateMachine 从未启用，adapter 半死不活，
// 状态机 entry/exit 现直接通过 context.queueStore 更新 item，不再经事件总线绕路
import * as guards from './guards';

// 协调器
import {
  UploadCoordinator,
  RecoveryCoordinator,
  FileUploadCoordinator,
  ChunkUploadCoordinator,
} from './coordinators';

// 生命周期
import {
  StateChangeHandler,
  UploadLifecycle,
  NetworkLifecycle,
} from './lifecycle';

// 控制器
import {
  DebounceController,
  ItemOperationController,
  QueueOperationController,
} from './controls';

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
  recoveryCoordinator = null;
  fileUploadCoordinator = null;
  chunkUploadCoordinator = null;

  // ===== 生命周期处理器 =====
  stateChangeHandler = null;
  uploadLifecycle = null;
  networkLifecycle = null;

  // ===== 控制器 =====
  debounceController = null;
  itemOperationController = null;
  queueOperationController = null;

  // ===== 同步器 =====
  statusSynchronizer = null;

  // ===== 全局状态 =====
  @observable isPaused = false;
  @observable isCancelled = false;
  @observable maxConcurrentUploads = UPLOAD_CONSTANTS.MAX_CONCURRENT_UPLOADS;

  // 【2026-07-02 动态降级】分片并发上限（当前分片串行，字段为预留/契约用，随压力更新）
  @observable maxConcurrentChunks = UPLOAD_CONSTANTS.MAX_CONCURRENT_CHUNKS;

  // 【P0修复 2026-06-27】是否使用解耦版状态机
  // 【方向B 2026-06-27】解耦设施已移除，此字段保留仅为向后兼容，值固定 false
  useDecoupledStateMachine = false;

  // ===== 上传冲突处理（参照阿里云盘/百度网盘）=====
  // 同名+不同大小 -> 弹窗让用户选：替换/保留两者/跳过
  @observable conflictDialogVisible = false;
  @observable pendingConflicts = [];
  // File 对象不可序列化，放非 observable 字段
  pendingConflictFiles = [];
  pendingConflictCtx = null;

  // ===== 非observable =====
  // 【方向B 2026-06-27】已删除 cancelTokenSources 字段（从未被写入，死代码）
  cleanupTimer = null;
  stateMachineCleanupTimer = null;
  failedSyncTransfers = [];

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

  _initStores() {
    this.queueStore = new UploadQueueStore(this);
    this.fileUploadStore = new FileUploadStore(this.queueStore, this);
    this.chunkUploadStore = new ChunkUploadStore(this.queueStore, this.fileUploadStore, this);
    this.folderUploadStore = new FolderUploadStore(this.queueStore, this.fileUploadStore, this);
    this.md5Store = new MD5Store(this);
    this.transferStore = new TransferStore(this);
  }

  _initStateMachine() {
    this.stateMachineManager = new StateMachineManager();
    this.stateMachineManager.addGlobalListener((fromState, toState, event, payload, uploadId) => {
      if (this.stateChangeHandler) {
        this.stateChangeHandler.handle(fromState, toState, event, payload, uploadId);
      }
    });
    this.stateMachineCleanupTimer = setInterval(() => {
      if (this.stateMachineManager) {
        this.stateMachineManager.cleanup();
      }
    }, 60000);
  }

  _initCoordinators() {
    this.uploadCoordinator = new UploadCoordinator(this);
    this.recoveryCoordinator = new RecoveryCoordinator(this);
    this.fileUploadCoordinator = new FileUploadCoordinator(this);
    this.chunkUploadCoordinator = new ChunkUploadCoordinator(this);
  }

  _initLifecycleHandlers() {
    this.stateChangeHandler = new StateChangeHandler(this);
    this.uploadLifecycle = new UploadLifecycle(this);
    this.networkLifecycle = new NetworkLifecycle(this);
  }

  _initControllers() {
    this.debounceController = new DebounceController(this);
    this.itemOperationController = new ItemOperationController(this);
    this.queueOperationController = new QueueOperationController(this);
  }

  _initSynchronizers() {
    this.statusSynchronizer = new StatusSynchronizer(this);
  }

  /**
   * 【方向B 2026-06-27】已移除事件总线适配器初始化
   * 状态机 entry/exit 直接通过 context.queueStore 更新 item
   */
  _initEventAdapter() {
    // no-op：解耦设施已移除
  }

  _initGlobalListeners() {
    this.initUploadQueueCleanup();
    this.networkLifecycle.init();
    // 【方向B 2026-06-27】不再初始化事件适配器
  }

  // ===== 代理属性 =====

  get uploadQueue() { return this.queueStore.uploadQueue; }
  /**
   * @deprecated 【7.2 统一并发槽位口径】不再参与调度决策。
   *   调度以 stateMachineManager.countByStates(['calculating','uploading']) 为唯一口径。
   *   保留此代理属性仅为向后兼容 UI/调试展示。
   */
  get activeUploads() { return this.queueStore.activeUploads; }
  get refreshTrigger() { return this.queueStore.refreshTrigger; }
  get uploadRefreshTrigger() { return this.queueStore.uploadRefreshTrigger; }
  get folderUploadProgress() { return this.queueStore.folderUploadProgress; }
  get currentUploadQueue() { return this.queueStore.currentUploadQueue; }
  get pendingFiles() { return this.queueStore.pendingFiles; }
  set pendingFiles(value) { this.queueStore.pendingFiles = value; }
  get pendingFolderFiles() { return this.queueStore.pendingFolderFiles; }
  set pendingFolderFiles(value) { this.queueStore.pendingFolderFiles = value; }

  // ===== Computed 属性（优化 render 中的 filter 计算）=====

  /**
   * 上传中的项目（包括等待、计算、上传、暂停、合并中）
   * 【P0修复 2026-06-27】使用 DISPLAY_UPLOADING_STATUSES 常量替代手工拼接
   */
  @computed
  get uploadingItems() {
    return this.currentUploadQueue.filter(
      item => DISPLAY_UPLOADING_STATUSES.includes(item.status)
    );
  }

  /**
   * 已完成的任务
   */
  @computed
  get completedItems() {
    return this.currentUploadQueue.filter(item => item.status === UPLOAD_STATUS.COMPLETED);
  }

  /**
   * 失败的任务（error + cancelled 合并为"失败"分组）
   * 【重构 2026-06-06】cancelled 不再单独成组，统一在"失败"Tab 展示
   */
  @computed
  get errorItems() {
    return this.currentUploadQueue.filter(item => item.status === UPLOAD_STATUS.ERROR);
  }

  /**
   * 已取消的任务（用户主动取消）
   * 【重构 2026-06-06】仍保留 computed 供旧代码使用，但 UI 统一归入 errorItems 展示
   * 推荐直接使用 errorItems（已包含 cancelled 项）
   */
  @computed
  get cancelledItems() {
    return this.currentUploadQueue.filter(item => item.status === UPLOAD_STATUS.CANCELLED);
  }

  /**
   * 等待中的任务数
   */
  @computed
  get waitingCount() {
    return this.currentUploadQueue.filter(item => item.status === UPLOAD_STATUS.WAITING).length;
  }

  /**
   * 活跃上传中的任务数（进行中页签中非暂停的任务数）
   * 【P0修复 2026-06-27】修复之前遗漏 waiting 状态的 bug
   * 之前 activeCount = ACTIVE_STATUSES = [calculating, uploading, merging]
   * 但 uploadingItems 包含 waiting，导致 uploadingTotal ≠ uploadingItems.length
   * 现在使用 DISPLAY_UPLOADING_STATUSES 减去 PAUSED，与 uploadingItems 对齐
   */
  @computed
  get activeCount() {
    return this.currentUploadQueue.filter(
      item => DISPLAY_UPLOADING_STATUSES.includes(item.status) &&
              item.status !== UPLOAD_STATUS.PAUSED
    ).length;
  }

  /**
   * 已暂停的任务数
   */
  @computed
  get pausedCount() {
    return this.currentUploadQueue.filter(item => item.status === UPLOAD_STATUS.PAUSED).length;
  }

  // ===== 工具方法 =====

  getCurrentTenantId() {
    if (this.rootStore.navigationStore?.isPublic) {
      return 'public';
    }
    return sessionStorage.getItem('tenant_id') || 'default';
  }

  getUploadTargetFolderId() {
    return this.rootStore.navigationStore?.getUploadTargetFolderId?.() || null;
  }

  /**
   * 【P1 修复】获取当前空间类型（公共/私有）
   * 提供清晰的代理方法，避免外部代码双重访问 rootStore
   */
  getIsPublic() {
    return this.rootStore.navigationStore?.isPublic ?? false;
  }

  /**
   * 【拖拽上传 - 5.2】捕获不可变上传目标上下文
   *
   * 在 drop 事件发生时（或按钮上传未显式传 targetContext 时）立即调用，
   * 把当前导航/租户/系统目录状态固化为快照，后续无论用户切换目录、
   * 切换空间、离开党建工作页面，本批任务都使用此快照。
   *
   * 返回对象经 Object.freeze 保护，所有上传相关请求（transfer create /
   * file upload / chunk upload / merge / merge_status / folder create）
   * 都从此快照读取 systemFolderCode/tenantId/isPublic/folderId，
   * 不再依赖可能变化的 systemFolderContext 全局变量或 navigationStore。
   *
   * @param {Object} [options]
   * @param {string|null} [options.systemFolderCode] - 显式系统目录 code（拖拽层会传）
   * @param {string} [options.targetPathLabel] - 用于 UI 提示的目标路径文本
   * @returns {Readonly<{folderId: number|null, isPublic: boolean, tenantId: string, systemFolderCode: string|null, targetPathLabel: string}>}
   */
  captureUploadTargetContext(options = {}) {
    // 委托给独立纯函数模块（便于单元测试，避免装饰器 babel 配置问题）
    return captureUploadTargetContextFn(this.rootStore, options);
  }

  // ===== 初始化方法 =====

  @action
  initUploadQueueCleanup() {
    const cleanup = () => {
      const tenantId = this.getCurrentTenantId();
      const queue = this.uploadQueue[tenantId];
      if (queue) {
        const inactiveItems = queue.filter(item =>
          ['completed', 'error', 'cancelled'].includes(item.status) &&
          Date.now() - (item.completedAt || 0) > UPLOAD_CONSTANTS.QUEUE_CLEANUP_INTERVAL
        );
        inactiveItems.forEach(item => {
          this.queueStore.removeFromQueue(item.id, tenantId);
        });
      }
    };
    this.cleanupTimer = setInterval(cleanup, UPLOAD_CONSTANTS.QUEUE_CLEANUP_INTERVAL);
  }

  // ===== 文件上传入口（代理到协调器）=====

  /**
   * 处理文件选择（按钮上传 / 拖拽上传 共用入口）
   * @param {File[]} files - 文件数组
   * @param {Object|null} [targetContext=null] - 拖拽上传时由 captureUploadTargetContext 生成的不可变快照；
   *   按钮上传不传时，由 coordinator 在入口立即捕获当前上下文（向后兼容）。
   */
  handleFileSelect(files, targetContext = null) {
    const ctx = targetContext || this.captureUploadTargetContext();
    return this.fileUploadCoordinator?.handleFileSelect(files, ctx);
  }

  // 【方向B 2026-06-27】已删除 processUploadQueue/uploadSingleFile 代理（0 调用方）

  // ===== 上传冲突处理方法 =====

  @action
  showConflictDialog(conflicts, files, ctx) {
    this.pendingConflicts = conflicts;
    this.pendingConflictFiles = files;
    this.pendingConflictCtx = ctx;
    this.conflictDialogVisible = true;
  }

  @action
  closeConflictDialog() {
    this.conflictDialogVisible = false;
    this.pendingConflicts = [];
    this.pendingConflictFiles = [];
    this.pendingConflictCtx = null;
  }

  @action
  updateConflictAction(index, action) {
    if (this.pendingConflicts[index]) {
      // 必须创建新对象引用，否则 antd Table 行级 memo 跳过重渲染
      this.pendingConflicts[index] = { ...this.pendingConflicts[index], action };
    }
  }

  @action
  setAllConflictActions(action) {
    // 同理：map 产生全新对象数组，触发 Table 行重渲染
    this.pendingConflicts = this.pendingConflicts.map(c => ({ ...c, action }));
  }

  /**
   * 用户确认冲突处理后，执行上传
   * 由 UploadConflictModal 的"确定"按钮调用
   */
  async resolveConflicts() {
    const ctx = this.pendingConflictCtx;
    const files = this.pendingConflictFiles;
    // 浅拷贝 conflicts（closeConflictDialog 会清空 pendingConflicts）
    const conflicts = this.pendingConflicts.map(c => ({ ...c }));
    this.closeConflictDialog();
    if (this.fileUploadCoordinator) {
      await this.fileUploadCoordinator.executeConflictResolution(conflicts, files, ctx);
    }
  }

  /**
   * 处理文件夹选择（按钮上传 webkitdirectory / 拖拽文件夹 共用入口）
   * @param {File[]} files - 带 webkitRelativePath 的文件数组
   * @param {Object|null} [targetContext=null] - 拖拽上传时显式传入的不可变上下文快照
   */
  handleFolderSelect(files, targetContext = null) {
    const ctx = targetContext || this.captureUploadTargetContext();
    return this.folderUploadStore.handleFolderSelect(files, ctx);
  }

  /**
   * 【拖拽上传专用】处理规范化后的文件夹条目
   *
   * 与 handleFolderSelect 的区别：
   *   - handleFolderSelect 接收带 webkitRelativePath 的 File[]（按钮上传 webkitdirectory 路径）
   *   - handleFolderEntries 接收 {file, relativePath, rootName}[]（拖拽 webkitGetAsEntry 路径）
   *
   * 两条路径最终都走 FolderStructureBuilder + FileUploadCoordinator._processBatch，
   * 不创建第二套队列或协调器。
   *
   * @param {Array<{file: File, relativePath: string, rootName: string}>} entries
   * @param {Object|null} [targetContext=null] - drop 时捕获的不可变上下文快照
   */
  handleFolderEntries(entries, targetContext = null) {
    const ctx = targetContext || this.captureUploadTargetContext();
    return this.folderUploadStore.handleFolderEntries(entries, ctx);
  }

  // ===== 队列控制 =====

  replenishDisplayQueue() {
    return this.uploadCoordinator?.startWaiting();
  }

  // 【方向B 2026-06-27】已删除 startWaitingTasks/processPendingUploads/schedulePendingUploadsRecovery
  // 原因：0 外部调用方，内部子模块已直接通过 this.core.uploadCoordinator.xxx 调用

  // ===== 批量操作（代理到控制器）=====

  pauseAll = async () => this.debounceController?.pauseAll();
  resumeAll = async () => this.debounceController?.resumeAll();
  removeAll = async () => this.queueOperationController?.removeAll();

  // ===== 单文件控制（代理到控制器，带防抖）=====

  pauseItem(itemId) {
    return this.debounceController?.wrapItemOperation(itemId, () =>
      this.itemOperationController?.pauseItem(itemId)
    );
  }

  resumeItem(itemId) {
    return this.debounceController?.wrapItemOperation(itemId, () =>
      this.itemOperationController?.resumeItem(itemId)
    );
  }

  cancelItem(itemId) {
    return this.itemOperationController?.cancelItem(itemId);
  }

  removeItem(itemId) {
    return this.itemOperationController?.removeItem(itemId);
  }

  abortUpload(uploadId) {
    return this.itemOperationController?.abortUpload(uploadId);
  }

  // ===== 断点续传 =====
  // 【P1修复】旧的 resumeChunkedUpload 已移除（旧的 Math.max+1 模式会漏传中间缺口分片）。
  // 断点续传统一走 chunkUploadStore.uploadFileChunked() 的"补缺分片"模型：
  //   1) 调用 checkUploadedChunks 获取后端已上传分片集合
  //   2) for 循环遍历所有分片
  //   3) 跳过 uploadedChunks.has(chunkIndex) 的分片，自动补齐中间缺口

  replaceFileAndResume(itemId, newFile) {
    return this.fileUploadCoordinator?.replaceFileAndResume(itemId, newFile);
  }

  // ===== 清理方法 =====

  @action
  destroy() {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = null;
    }
    if (this.stateMachineCleanupTimer) {
      clearInterval(this.stateMachineCleanupTimer);
      this.stateMachineCleanupTimer = null;
    }
    if (this.networkLifecycle) {
      this.networkLifecycle.cleanup();
    }
    if (this.debounceController) {
      this.debounceController.cleanup();
    }
    if (this.statusSynchronizer) {
      this.statusSynchronizer.cleanup();
    }
    // 【方向B 2026-06-27】已移除 storeEventAdapter 销毁逻辑
    // 【P1 修复】销毁文件夹上传Store，清理 beforeunload 事件监听器，防止内存泄漏
    if (this.folderUploadStore) {
      this.folderUploadStore.destroy();
    }
    // 清理队列Store定时器
    if (this.queueStore) {
      this.queueStore.destroy();
    }
    // 【方向B 2026-06-27】已删除 this.cancelAll() 调用
    // destroy 只应清理资源（定时器/监听器/Worker），不应取消用户正在进行的上传任务
    // 如未来 destroy 被实际调用且需要中止请求，应单独实现"中止所有请求"的资源清理逻辑
    this.md5Store.terminateAll();
  }

  // 【方向B 2026-06-27】已删除 cancelAllUploads/createCancelToken/cancelUpload/cancelTokenSources
  // 原因：cancelTokenSources 从未被写入（createCancelToken 0 调用方），
  // cancelAllUploads/cancelUpload 0 调用方，全部是死代码
  // 实际请求中止通过 item.abortToken.cancel() / item.abortController.abort() 实现

  // 【方向B 2026-06-27】已删除 transferStore/sync/md5 的 8 个纯转发代理方法
  // 原因：0 外部调用方 + 0 内部 this.core.xxx 调用，纯死代码
  // 内部子模块已直接通过 this.core.transferStore.xxx / this.core.statusSynchronizer.xxx 调用
  // 如需外部访问，可直接用 uploadCoreStore.transferStore.xxx
}

// 创建实例（用于兼容旧代码）
let uploadCoreStoreInstance = null;

export function getUploadCoreStore(rootStore) {
  if (!uploadCoreStoreInstance) {
    uploadCoreStoreInstance = new UploadCoreStore(rootStore);
  }
  return uploadCoreStoreInstance;
}

// 【方向B 2026-06-27】导出（已移除解耦设施 EventBus/StoreEventAdapter/actions）
export {
  // 状态机类
  UploadStateMachine,
  // 状态机管理器类
  StateMachineManager,
  // guards
  guards,
};

export default UploadCoreStore;

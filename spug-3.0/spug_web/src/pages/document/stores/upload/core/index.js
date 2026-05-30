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
import { UPLOAD_CONSTANTS } from './upload-core-constants';

// 子Store
import UploadQueueStore from './queue';
import FileUploadStore from './fileUpload';
import ChunkUploadStore from './chunkUpload';
import FolderUploadStore from './folderUpload';
import MD5Store from './md5';
import TransferStore from './transfer';

// 状态机（【任务4.1】已替换为解耦版）
import { StateMachineManager } from './StateMachineManager';
import { UploadStateMachine } from './UploadStateMachine';

// 【任务4.1】解耦相关导入
import { globalEventBus } from './EventBus';
import { StoreEventAdapter } from './StoreEventAdapter';
import * as guards from './guards';
import { createActions, UploadEvents } from './actions';

// 协调器
import {
  UploadCoordinator,
  DisplayCoordinator,
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
  displayCoordinator = null;
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

  // 【任务4.1】事件总线适配器
  storeEventAdapter = null;

  // ===== 全局状态 =====
  @observable isPaused = false;
  @observable isCancelled = false;
  @observable maxConcurrentUploads = UPLOAD_CONSTANTS.MAX_CONCURRENT_UPLOADS;

  // 【任务4.1】是否使用解耦版状态机（可通过配置切换）
  useDecoupledStateMachine = false;

  // ===== 非observable =====
  cancelTokenSources = new Map();
  cleanupTimer = null;
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
    setInterval(() => {
      if (this.stateMachineManager) {
        this.stateMachineManager.cleanup();
      }
    }, 60000);
  }

  _initCoordinators() {
    this.uploadCoordinator = new UploadCoordinator(this);
    this.displayCoordinator = new DisplayCoordinator(this);
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
   * 【任务4.1】初始化事件总线适配器
   * 连接事件总线与Store，实现状态机与Store的解耦
   */
  _initEventAdapter() {
    this.storeEventAdapter = new StoreEventAdapter({
      queueStore: this.queueStore,
      transferStore: this.transferStore,
      md5Store: this.md5Store
    });
    this.storeEventAdapter.init();
  }

  _initGlobalListeners() {
    this.initUploadQueueCleanup();
    this.networkLifecycle.init();
    // 【任务4.1】初始化事件适配器
    this._initEventAdapter();
  }

  // ===== 代理属性 =====

  get uploadQueue() { return this.queueStore.uploadQueue; }
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
   * 【P2优化】使用 computed 缓存，避免每次 render 重复 filter
   */
  @computed
  get uploadingItems() {
    return this.currentUploadQueue.filter(
      item => ['waiting', 'calculating', 'uploading', 'paused', 'merging'].includes(item.status)
    );
  }

  /**
   * 已完成的任务
   */
  @computed
  get completedItems() {
    return this.currentUploadQueue.filter(item => item.status === 'completed');
  }

  /**
   * 失败/取消的任务
   */
  @computed
  get errorItems() {
    return this.currentUploadQueue.filter(
      item => ['error', 'cancelled'].includes(item.status)
    );
  }

  /**
   * 等待中的任务数
   */
  @computed
  get waitingCount() {
    return this.currentUploadQueue.filter(item => item.status === 'waiting').length;
  }

  /**
   * 活跃上传中的任务数（计算、上传、合并中）
   */
  @computed
  get activeCount() {
    return this.currentUploadQueue.filter(
      item => ['calculating', 'uploading', 'merging'].includes(item.status)
    ).length;
  }

  /**
   * 已暂停的任务数
   */
  @computed
  get pausedCount() {
    return this.currentUploadQueue.filter(item => item.status === 'paused').length;
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

  handleFileSelect(files) {
    return this.fileUploadCoordinator?.handleFileSelect(files);
  }

  processUploadQueue(files, folderId) {
    return this.fileUploadCoordinator?.processUploadQueue(files, folderId);
  }

  uploadSingleFile(file, folderId, existingUploadId, isPublic) {
    return this.fileUploadCoordinator?.uploadSingleFile(file, folderId, existingUploadId, isPublic);
  }

  handleFolderSelect(files) {
    return this.folderUploadStore.handleFolderSelect(files);
  }

  // ===== 队列控制（代理到协调器）=====

  startWaitingTasks() {
    return this.uploadCoordinator?.startWaiting();
  }

  processPendingUploads() {
    return this.uploadCoordinator?.processPending();
  }

  replenishDisplayQueue() {
    return this.displayCoordinator?.replenish();
  }

  schedulePendingUploadsRecovery() {
    return this.recoveryCoordinator?.schedule();
  }

  // ===== 批量操作（代理到控制器）=====

  pauseAll = async () => this.debounceController?.pauseAll();
  resumeAll = async () => this.debounceController?.resumeAll();
  cancelAll = async () => this.queueOperationController?.cancelAll();
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

  // ===== 断点续传（代理到协调器）=====

  resumeChunkedUpload(file, folderId, item, chunkCount) {
    return this.chunkUploadCoordinator?.resumeChunkedUpload(file, folderId, item, chunkCount);
  }

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
    if (this.networkLifecycle) {
      this.networkLifecycle.cleanup();
    }
    if (this.debounceController) {
      this.debounceController.cleanup();
    }
    if (this.statusSynchronizer) {
      this.statusSynchronizer.cleanup();
    }
    // 【任务4.1】销毁事件适配器
    if (this.storeEventAdapter) {
      this.storeEventAdapter.destroy();
      this.storeEventAdapter = null;
    }
    this.cancelAll();
    this.md5Store.terminateAll();
  }

  cancelAllUploads() {
    this.cancelTokenSources.forEach((source, uploadId) => {
      source.cancel(`全局取消：${uploadId}`);
    });
    this.cancelTokenSources.clear();
  }

  async createCancelToken(uploadId) {
    const axios = await import('axios');
    const source = axios.default.CancelToken.source();
    this.cancelTokenSources.set(uploadId, source);
    return source.token;
  }

  cancelUpload(uploadId) {
    const source = this.cancelTokenSources.get(uploadId);
    if (source) {
      source.cancel(`上传取消：${uploadId}`);
      this.cancelTokenSources.delete(uploadId);
    }
  }

  // ===== 代理 transferStore 的方法 =====

  fetchTransfers(isPublic) { return this.transferStore.fetchTransfers(isPublic); }
  createTransfer(data) { return this.transferStore.createTransfer(data); }
  updateTransferStatus(transferId, status) { return this.transferStore.updateTransferStatus(transferId, status); }
  cancelTransfer(transferId) { return this.transferStore.cancelTransfer(transferId); }
  deleteTransfer(transferId) { return this.transferStore.deleteTransfer(transferId); }

  // ===== 状态同步（代理到同步器）=====

  syncTransferStatus(isPublic) {
    return this.statusSynchronizer?.syncTransferStatus(isPublic);
  }

  mapBackendStatus(backendStatus) {
    return this.statusSynchronizer?.mapBackendStatus(backendStatus);
  }

  // ===== 其他工具方法 =====

  cleanupMD5WorkerPool() {
    this.md5Store.terminateAll();
  }
}

// 创建实例（用于兼容旧代码）
let uploadCoreStoreInstance = null;

export function getUploadCoreStore(rootStore) {
  if (!uploadCoreStoreInstance) {
    uploadCoreStoreInstance = new UploadCoreStore(rootStore);
  }
  return uploadCoreStoreInstance;
}

// 【任务4.1】导出解耦相关组件
export {
  // 事件总线
  globalEventBus,
  // 事件适配器
  StoreEventAdapter,
  // 状态机类
  UploadStateMachine,
  // 状态机管理器类
  StateMachineManager,
  // guards
  guards,
  // actions
  createActions,
  UploadEvents
};

export default UploadCoreStore;

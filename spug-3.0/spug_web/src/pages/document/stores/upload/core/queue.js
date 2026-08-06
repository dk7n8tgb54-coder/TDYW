/**
 * UploadQueueStore - 上传队列管理
 * 职责：管理上传任务队列、并发控制
 */
import { observable, action, computed } from 'mobx';
import { UPLOAD_CONSTANTS } from './upload-core-constants';

export class UploadQueueStore {
  constructor(rootStore) {
    this.rootStore = rootStore;
  }

  // ============ Observable State ============
  @observable uploadQueue = {};  // 按租户分组的上传队列 { [tenantId]: [items] }
  /**
   * @deprecated 【7.2 统一并发槽位口径】不再参与调度决策。
   *   并发槽位以 stateMachineManager.countByStates(['calculating','uploading']) 为唯一口径。
   *   此字段保留仅为向后兼容 UI/调试指标，值不再被业务递增递减。
   *   后续如 UI 已迁移到状态机派生计数，可删除此字段。
   */
  @observable activeUploads = 0;  // 当前正在上传的文件数量
  @observable refreshTrigger = 0;  // 文件列表刷新触发器
  @observable uploadRefreshTrigger = 0;  // 上传进度刷新触发器
  @observable folderUploadProgress = { current: 0, total: 0 };  // 文件夹上传进度

  // 非observable状态
  uploadingUniqueKeys = new Set();  // 正在上传的文件唯一标识集合（防重复提交）
  pendingFiles = [];  // 待上传文件列表（用于暂停后继续）
  pendingFolderFiles = null;  // 文件夹上传的待处理文件
  existingFileItems = [];  // 当前文件夹的文件列表（由 useDataFetching 同步写入，用于重名检查）

  // ============ Computed ============
  @computed
  get currentUploadQueue() {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    return this.uploadQueue[tenantId] || [];
  }

  // ============ 队列查询方法 ============
  
  /**
   * 在队列中查找上传项（跨租户查找）
   */
  findUploadItem(uploadId) {
    for (const tenantId of Object.keys(this.uploadQueue)) {
      const item = this.uploadQueue[tenantId].find(i => i.id === uploadId);
      if (item) {
        return { item, tenantId };
      }
    }
    return { item: null, tenantId: null };
  }

  /**
   * 在当前租户队列中查找上传项
   */
  findUploadItemInCurrentTenant(uploadId) {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    const queue = this.uploadQueue[tenantId];
    if (!queue) return null;
    return queue.find(i => i.id === uploadId);
  }

  /**
   * 生成唯一标识
   */
  generateUniqueKey(file, targetFolderId, isPublic) {
    return `${file.size}-${file.name}-${file.lastModified}-${isPublic ? 'public' : 'private'}-${targetFolderId}`;
  }

  /**
   * 检查文件是否已在队列中
   */
  isFileInQueue(file, targetFolderId, isPublic) {
    const uniqueKey = this.generateUniqueKey(file, targetFolderId, isPublic);
    return this.uploadingUniqueKeys.has(uniqueKey);
  }

  /**
   * 添加唯一标识
   */
  addUniqueKey(file, targetFolderId, isPublic) {
    const uniqueKey = this.generateUniqueKey(file, targetFolderId, isPublic);
    this.uploadingUniqueKeys.add(uniqueKey);
    return uniqueKey;
  }

  /**
   * 移除唯一标识
   */
  removeUniqueKey(file, targetFolderId, isPublic) {
    const uniqueKey = this.generateUniqueKey(file, targetFolderId, isPublic);
    this.uploadingUniqueKeys.delete(uniqueKey);
  }

  // ============ 队列管理方法 ============

  /**
   * 添加上传项到队列
   */
  @action
  addToQueue(item, tenantId) {
    if (!this.uploadQueue[tenantId]) {
      this.uploadQueue[tenantId] = [];
    }
    
    // 【修复】如果 item 包含 file 属性，使用 Object.defineProperty 保护它
    // 避免 MobX 的 observable 转换导致 File 对象丢失
    if (item.file instanceof File) {
      const file = item.file;
      delete item.file;  // 先从对象中删除
      Object.defineProperty(item, 'file', {
        value: file,
        writable: true,
        enumerable: false,
        configurable: true
      });
    }
    
    this.uploadQueue[tenantId].push(item);
    this.uploadQueue = { ...this.uploadQueue };  // 触发响应
    
    // 【新增】自动清理旧已完成任务（防内存泄漏）
    this.cleanOldCompletedTasks(tenantId);
  }

  /**
   * 从队列中移除上传项
   */
  @action
  removeFromQueue(uploadId, tenantId) {
    if (!this.uploadQueue[tenantId]) return;
    this.uploadQueue[tenantId] = this.uploadQueue[tenantId].filter(i => i.id !== uploadId);
    if (this.uploadQueue[tenantId].length === 0) {
      delete this.uploadQueue[tenantId];
    }
    this.uploadQueue = { ...this.uploadQueue };
  }

  // 节流控制 - uploadRefreshTrigger 更新
  _refreshTriggerTimer = null;
  _pendingRefresh = false;

  /**
   * 更新上传项状态（带节流控制）
   */
  @action
  updateUploadItem(uploadId, updates) {
    const { item } = this.findUploadItem(uploadId);
    if (item) {
      Object.assign(item, updates);
      this._throttledRefreshTrigger();
    }
  }

  /**
   * 节流刷新触发器（500ms）
   */
  _throttledRefreshTrigger() {
    this._pendingRefresh = true;
    if (!this._refreshTriggerTimer) {
      this._refreshTriggerTimer = setTimeout(() => {
        this._refreshTriggerTimer = null;
        if (this._pendingRefresh) {
          this._pendingRefresh = false;
          this.uploadRefreshTrigger += 1;
        }
      }, 500);
    }
  }

  /**
   * 增加活跃上传计数
   * @deprecated 【7.2】不再参与调度决策，保留仅为向后兼容。调度以状态机计数为准。
   */
  @action
  incrementActiveUploads() {
    this.activeUploads += 1;
  }

  /**
   * 减少活跃上传计数
   * @deprecated 【7.2】不再参与调度决策，保留仅为向后兼容。调度以状态机计数为准。
   */
  @action
  decrementActiveUploads() {
    this.activeUploads = Math.max(0, this.activeUploads - 1);
  }

  /**
   * 触发文件列表刷新
   */
  @action
  triggerRefresh() {
    this.refreshTrigger += 1;
  }

  /**
   * 获取队列长度
   */
  getQueueLength(tenantId) {
    return this.uploadQueue[tenantId]?.length || 0;
  }

  /**
   * 清空已完成的上传项
   */
  @action
  clearCompleted() {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    if (this.uploadQueue[tenantId]) {
      this.uploadQueue[tenantId] = this.uploadQueue[tenantId].filter(
        item => item.status === 'uploading' || item.status === 'waiting'
      );
      this.uploadQueue = { ...this.uploadQueue };
    }
  }

  /**
   * 暂停上传
   * 【TODO 7.1 状态机唯一入口例外点 / 废弃方法】
   * 此方法直接写 status:'paused' 绕过状态机，且经核查无任何调用方（仅测试 mock 引用）。
   * 暂停应通过 ItemOperationController.pauseItem → stateMachine.transition('PAUSE') 完成。
   * 保留方法签名仅为向后兼容，后续应在确认无引用后删除。
   */
  @action
  pauseUpload(uploadId) {
    console.warn('[QueueStore] pauseUpload 已废弃，请使用 ItemOperationController.pauseItem（状态机 PAUSE 事件）');
    this.updateUploadItem(uploadId, { 
      status: 'paused',
      _resumeInfo: { canResume: true }
    });
  }

  /**
   * 恢复上传
   * 【TODO 7.1 状态机唯一入口例外点 / 废弃方法】
   * 此方法直接写 status:'waiting' 绕过状态机，且经核查无任何调用方（仅测试 mock 引用）。
   * 恢复应通过 ItemOperationController.resumeItem → stateMachine.transition('RESUME'/'START') 完成。
   */
  @action
  resumeUpload(uploadId) {
    console.warn('[QueueStore] resumeUpload 已废弃，请使用 ItemOperationController.resumeItem（状态机 RESUME/START 事件）');
    this.updateUploadItem(uploadId, { status: 'waiting' });
  }

  /**
   * 取消上传
   */
  @action
  cancelUpload(uploadId) {
    const { item, tenantId } = this.findUploadItem(uploadId);
    if (item) {
      // 如果正在上传，需要中断请求
      if (item.cancelToken) {
        item.cancelToken.cancel('用户取消上传');
      }
      this.removeFromQueue(uploadId, tenantId);
    }
  }

  // ============ 状态检查方法（新增）============

  /**
   * 【7.3 异步操作加版本号】递增并返回新操作版本号
   * 每次 START/RESUME/RETRY/CANCEL/PAUSE 时调用，使旧异步回调失效。
   * 版本号存储在 item.operationVersion 上，初始为 0。
   * @param {string} uploadId - 上传项ID
   * @returns {number} 新版本号；item 不存在时返回 0
   */
  bumpOperationVersion(uploadId) {
    const item = this.findUploadItemInCurrentTenant(uploadId);
    if (!item) return 0;
    const next = (item.operationVersion || 0) + 1;
    item.operationVersion = next;
    return next;
  }

  /**
   * 【7.3】获取当前操作版本号
   * @param {string} uploadId - 上传项ID
   * @returns {number} 当前版本号；item 不存在或未初始化时返回 0
   */
  getOperationVersion(uploadId) {
    const item = this.findUploadItemInCurrentTenant(uploadId);
    if (!item) return 0;
    return item.operationVersion || 0;
  }

  /**
   * 【7.3】判断某个异步回调是否仍属于当前操作
   * @param {string} uploadId - 上传项ID
   * @param {number} version - 异步操作启动时捕获的版本号
   * @returns {boolean} true 表示版本有效，回调可继续处理；false 表示已过期，应丢弃
   */
  isCurrentOperation(uploadId, version) {
    // 无版本号视为当前（向后兼容旧调用方/测试 mock）
    if (!version) return true;
    const current = this.getOperationVersion(uploadId);
    return current === version;
  }

  /**
   * 检查上传项是否处于暂停状态
   * @param {string} uploadId - 上传项ID
   * @returns {boolean} 是否暂停
   */
  isPaused(uploadId) {
    const item = this.findUploadItemInCurrentTenant(uploadId);
    return item && (item.status === 'paused' || item.isPausedByUser);
  }

  /**
   * 检查上传项是否处于取消状态
   * @param {string} uploadId - 上传项ID
   * @returns {boolean} 是否取消
   */
  isCancelled(uploadId) {
    const item = this.findUploadItemInCurrentTenant(uploadId);
    return item && (item.status === 'error' || item.isCancelledByUser);
  }

  /**
   * 检查上传项是否可以执行指定操作
   * @param {string} uploadId - 上传项ID
   * @param {string[]} validStatuses - 有效状态列表
   * @returns {boolean} 是否可以执行
   */
  canPerformAction(uploadId, validStatuses) {
    const item = this.findUploadItemInCurrentTenant(uploadId);
    return item && validStatuses.includes(item.status);
  }

  /**
   * 清理上传项资源（防止内存泄漏）
   * @param {string} uploadId - 上传项ID
   */
  cleanupUploadItem(uploadId) {
    const item = this.findUploadItemInCurrentTenant(uploadId);
    if (!item) return;

    // 清理中止控制器
    if (item.abortController) {
      try {
        item.abortController.abort();
      } catch (e) {
        // 忽略已中止的错误
      }
      item.abortController = null;
    }

    // 清理取消令牌
    if (item.abortToken) {
      try {
        item.abortToken.cancel();
      } catch (e) {
        // 忽略已取消的错误
      }
      item.abortToken = null;
    }

    // 清理大文件引用（completed或error状态）
    if (item.status === 'completed' || item.status === 'error') {
      item.file = null;
    }

    item.canAbort = false;
  }

  /**
   * 批量清理已完成/错误的上传项资源
   * @param {number} maxAge - 最大保留时间（毫秒），默认5分钟
   */
  @action
  cleanupCompletedItems(maxAge = 5 * 60 * 1000) {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    const queue = this.uploadQueue[tenantId];
    if (!queue) return;

    const now = Date.now();
    queue.forEach(item => {
      if ((item.status === 'completed' || item.status === 'error') &&
          item.completedAt && (now - item.completedAt > maxAge)) {
        this.cleanupUploadItem(item.id);
      }
    });
  }

  /**
   * 设置文件夹上传进度
   */
  @action
  setFolderUploadProgress(current, total) {
    this.folderUploadProgress = { current, total };
  }

  /**
   * 【新增】自动清理旧已完成任务（防内存泄漏）
   * @param {string} tenantId - 租户ID
   */
  @action
  cleanOldCompletedTasks(tenantId) {
    const { UPLOAD_CONSTANTS } = require('../../constants/upload');
    const queue = this.uploadQueue[tenantId] || [];
    const completedTasks = queue.filter(item => item.status === 'completed');
    
    const maxCompleted = UPLOAD_CONSTANTS.MAX_COMPLETED_TASKS || 100;
    
    if (completedTasks.length > maxCompleted) {
      // 保留最新的，删除旧的
      const toDelete = completedTasks.slice(0, completedTasks.length - maxCompleted);
      this.uploadQueue[tenantId] = queue.filter(item => !toDelete.includes(item));
      this.uploadQueue = { ...this.uploadQueue };
      
      console.log('[自动清理] 删除', toDelete.length, '个已完成任务，保留最新', maxCompleted, '个');
    }
  }

  /**
   * 清理定时器等资源，防止内存泄漏
   */
  destroy() {
    if (this._refreshTriggerTimer) {
      clearTimeout(this._refreshTriggerTimer);
      this._refreshTriggerTimer = null;
    }
    this._pendingRefresh = false;
  }
}

export default UploadQueueStore;

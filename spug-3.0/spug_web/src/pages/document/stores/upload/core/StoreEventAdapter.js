/**
 * StoreEventAdapter - Store 事件适配器
 * 【任务4.1】连接事件总线与 Store，实现状态机与 Store 的解耦
 * 
 * 职责：
 * - 监听事件总线的事件
 * - 调用对应的 Store 方法
 * - 管理事件订阅的生命周期
 */

import { globalEventBus } from './EventBus';
import { UploadEvents } from './actions';

export class StoreEventAdapter {
  constructor(stores) {
    this.stores = stores;
    this.unsubscribers = [];
    this.isInitialized = false;
  }

  /**
   * 初始化适配器，订阅所有相关事件
   */
  init() {
    if (this.isInitialized) {
      console.warn('[StoreEventAdapter] 已经初始化，请勿重复调用');
      return;
    }

    // 状态变更事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.STATUS_CHANGE, this.handleStatusChange.bind(this))
    );

    // 进度更新事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.PROGRESS_UPDATE, this.handleProgressUpdate.bind(this))
    );

    // 错误事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.ERROR_OCCUR, this.handleErrorOccur.bind(this))
    );

    // 完成事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.COMPLETE, this.handleComplete.bind(this))
    );

    // 取消事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.CANCEL, this.handleCancel.bind(this))
    );

    // MD5 计算事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.MD5_START, this.handleMD5Start.bind(this))
    );
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.MD5_CANCEL, this.handleMD5Cancel.bind(this))
    );

    // 上传中断事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.UPLOAD_ABORT, this.handleUploadAbort.bind(this))
    );

    // 资源清理事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.RESOURCES_CLEANUP, this.handleResourcesCleanup.bind(this))
    );
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.ALL_RESOURCES_CLEANUP, this.handleAllResourcesCleanup.bind(this))
    );

    // 传输状态更新事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.TRANSFER_STATUS_UPDATE, this.handleTransferStatusUpdate.bind(this))
    );

    // 恢复事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.RESUME_TO_WAITING, this.handleResumeToWaiting.bind(this))
    );
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.RESUME_TO_CALCULATING, this.handleResumeToCalculating.bind(this))
    );
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.RESUME_TO_UPLOADING, this.handleResumeToUploading.bind(this))
    );
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.RETRY, this.handleRetry.bind(this))
    );

    // 普通上传完成事件
    this.unsubscribers.push(
      globalEventBus.on(UploadEvents.NORMAL_UPLOAD_COMPLETE, this.handleNormalUploadComplete.bind(this))
    );

    this.isInitialized = true;
    console.log('[StoreEventAdapter] 初始化完成');
  }

  /**
   * 销毁适配器，取消所有事件订阅
   */
  destroy() {
    this.unsubscribers.forEach(unsubscribe => unsubscribe());
    this.unsubscribers = [];
    this.isInitialized = false;
    console.log('[StoreEventAdapter] 已销毁');
  }

  // ============ 事件处理器 ============

  /**
   * 处理状态变更
   */
  handleStatusChange({ uploadId, updates, state }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    // 如果有 state 字段，作为 status 更新
    if (state) {
      queueStore.updateUploadItem(uploadId, { ...updates, status: state });
    } else {
      queueStore.updateUploadItem(uploadId, updates);
    }
  }

  /**
   * 处理进度更新
   */
  handleProgressUpdate({ uploadId, percent, loaded, total }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    const updates = { percent };
    if (loaded !== undefined) updates.loaded = loaded;
    if (total !== undefined) updates.total = total;

    queueStore.updateUploadItem(uploadId, updates);
  }

  /**
   * 处理错误
   */
  handleErrorOccur({ uploadId, error, shouldRetry }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    queueStore.updateUploadItem(uploadId, {
      status: 'error',
      error,
      shouldRetry
    });
  }

  /**
   * 处理完成
   */
  handleComplete({ uploadId }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    queueStore.updateUploadItem(uploadId, {
      status: 'completed',
      percent: 100,
      canAbort: false
    });
  }

  /**
   * 处理取消
   */
  handleCancel({ uploadId }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    queueStore.updateUploadItem(uploadId, {
      error: '已取消'
    });

    // 清理资源
    this.cleanupResources(uploadId, true);
  }

  /**
   * 处理 MD5 开始
   */
  handleMD5Start({ uploadId }) {
    const { md5Store } = this.stores;
    if (md5Store?.startMD5Calculation) {
      md5Store.startMD5Calculation(uploadId);
    }
  }

  /**
   * 处理 MD5 取消
   */
  handleMD5Cancel({ uploadId }) {
    const { md5Store } = this.stores;
    if (md5Store?.cancelMD5) {
      md5Store.cancelMD5(uploadId);
    }
  }

  /**
   * 处理上传中断
   */
  handleUploadAbort({ uploadId, abortController, abortToken, reason }) {
    if (abortController) {
      try {
        abortController.abort(reason);
      } catch (e) {
        // 忽略错误
      }
    }
    if (abortToken) {
      try {
        abortToken.cancel(reason);
      } catch (e) {
        // 忽略错误
      }
    }
  }

  /**
   * 处理资源清理
   */
  handleResourcesCleanup({ uploadId }) {
    this.cleanupResources(uploadId, false);
  }

  /**
   * 处理全部资源清理
   */
  handleAllResourcesCleanup({ uploadId }) {
    this.cleanupResources(uploadId, true);
  }

  /**
   * 清理资源辅助方法
   */
  cleanupResources(uploadId, includeFile = false) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    const updates = {
      abortController: null,
      abortToken: null
    };

    if (includeFile) {
      updates.file = null;
    }

    queueStore.updateUploadItem(uploadId, updates);
  }

  /**
   * 处理传输状态更新
   *
   * 【P0修复 2026-06-27】此方法已降级为备用同步路径。
   * 状态机 entry 钩子（onPausedEntry/onCompletedEntry/onCancelledEntry）不再调用
   * actions.updateTransferStatus()，因此 TRANSFER_STATUS_UPDATE 事件不再被状态机触发。
   *
   * 权威同步链路：
   *   StateChangeHandler.handle() → StatusSynchronizer.syncStateToBackend()
   *
   * 本方法保留仅为向后兼容（如有新代码通过 actions.updateTransferStatus() 触发事件），
   * 但必须与 StatusSynchronizer 共用去重逻辑，避免同一状态重复请求后端。
   *
   * 去重策略：委托给 statusSynchronizer.markSynced / shouldSync，与权威链路共享同一个 _lastSyncStatusMap。
   */
  async handleTransferStatusUpdate({ uploadId, status }) {
    const { queueStore, transferStore, statusSynchronizer } = this.stores;
    if (!queueStore || !transferStore) return;

    const item = queueStore.findUploadItemInCurrentTenant(uploadId);
    if (!item?.transferId) return;

    // 与 StatusSynchronizer 共用去重逻辑
    if (statusSynchronizer && typeof statusSynchronizer.shouldSync === 'function') {
      if (!statusSynchronizer.shouldSync(item.transferId, status)) {
        return;
      }
      statusSynchronizer.markSynced(item.transferId, status);
    }

    try {
      await transferStore.updateTransferStatus(item.transferId, status);
    } catch (error) {
      console.warn(`[StoreEventAdapter] 更新传输状态失败: ${item.transferId}`, error);
    }
  }

  /**
   * 处理恢复到 waiting 状态
   */
  handleResumeToWaiting({ uploadId, needsReSelect }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    const updates = {
      status: 'waiting',
      canAbort: false
    };

    if (needsReSelect) {
      updates.error = '请重新选择文件后继续';
    } else {
      updates.error = null;
    }

    queueStore.updateUploadItem(uploadId, updates);
  }

  /**
   * 处理恢复到 calculating 状态
   */
  handleResumeToCalculating({ uploadId }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    // 恢复后重新计算MD5，状态会由状态机设置
  }

  /**
   * 处理恢复到 uploading 状态
   */
  handleResumeToUploading({ uploadId }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    // 恢复后继续上传，状态会由状态机设置
  }

  /**
   * 处理重试
   */
  handleRetry({ uploadId }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    queueStore.updateUploadItem(uploadId, {
      error: null,
      percent: 0
    });
  }

  /**
   * 处理普通上传完成
   */
  handleNormalUploadComplete({ uploadId }) {
    const { queueStore } = this.stores;
    if (!queueStore) return;

    queueStore.updateUploadItem(uploadId, {
      status: 'completed',
      percent: 100,
      canAbort: false,
      completedAt: Date.now()
    });
  }
}

export default StoreEventAdapter;

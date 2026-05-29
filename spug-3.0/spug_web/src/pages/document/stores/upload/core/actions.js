/**
 * Actions - 状态转换动作
 * 【任务4.1】从 UploadStateMachine 拆分出来，通过事件总线与Store通信
 * 
 * 设计原则：
 * - 通过事件总线触发业务逻辑，不直接调用Store
 * - 保持纯函数特性，副作用通过事件委托
 * - 可扩展，支持自定义 action
 */

import { globalEventBus } from './EventBus';

// 事件名称常量
export const UploadEvents = {
  // 状态变更事件
  STATUS_CHANGE: 'upload:status:change',
  PROGRESS_UPDATE: 'upload:progress:update',
  ERROR_OCCUR: 'upload:error:occur',
  COMPLETE: 'upload:complete',
  CANCEL: 'upload:cancel',

  // 资源管理事件
  MD5_START: 'upload:md5:start',
  MD5_CANCEL: 'upload:md5:cancel',
  UPLOAD_ABORT: 'upload:abort',
  RESOURCES_CLEANUP: 'upload:resources:cleanup',
  ALL_RESOURCES_CLEANUP: 'upload:allResources:cleanup',

  // 后端同步事件
  TRANSFER_STATUS_UPDATE: 'upload:transfer:statusUpdate',

  // 恢复事件
  RESUME_TO_WAITING: 'upload:resume:toWaiting',
  RESUME_TO_CALCULATING: 'upload:resume:toCalculating',
  RESUME_TO_UPLOADING: 'upload:resume:toUploading',
  RETRY: 'upload:retry',

  // 普通上传完成
  NORMAL_UPLOAD_COMPLETE: 'upload:normalUpload:complete',
};

/**
 * Action 创建器工厂
 * @param {string} uploadId - 上传任务ID
 * @returns {Object} action 方法集合
 */
export function createActions(uploadId) {
  const emit = globalEventBus.emit.bind(globalEventBus);

  return {
    // ============ 状态更新 Actions ============

    /**
     * 更新上传项状态
     */
    updateItem(updates) {
      emit(UploadEvents.STATUS_CHANGE, {
        uploadId,
        updates,
        timestamp: Date.now()
      });
    },

    /**
     * 更新上传进度
     */
    updateProgress(percent, loaded, total) {
      emit(UploadEvents.PROGRESS_UPDATE, {
        uploadId,
        percent,
        loaded,
        total,
        timestamp: Date.now()
      });
    },

    /**
     * 报告错误
     */
    reportError(error, shouldRetry = false) {
      emit(UploadEvents.ERROR_OCCUR, {
        uploadId,
        error: error instanceof Error ? error.message : String(error),
        shouldRetry,
        timestamp: Date.now()
      });
    },

    // ============ 资源管理 Actions ============

    /**
     * 启动MD5计算
     */
    startMD5Calculation() {
      emit(UploadEvents.MD5_START, { uploadId });
    },

    /**
     * 取消MD5计算
     */
    cancelMD5Calculation() {
      emit(UploadEvents.MD5_CANCEL, { uploadId });
    },

    /**
     * 中断上传
     */
    abortUpload(abortController, abortToken) {
      emit(UploadEvents.UPLOAD_ABORT, {
        uploadId,
        abortController,
        abortToken,
        reason: '状态转换'
      });
    },

    /**
     * 清理上传资源
     */
    cleanupUploadResources() {
      emit(UploadEvents.RESOURCES_CLEANUP, { uploadId });
    },

    /**
     * 清理所有资源
     */
    cleanupAllResources() {
      emit(UploadEvents.ALL_RESOURCES_CLEANUP, { uploadId });
    },

    // ============ 后端同步 Actions ============

    /**
     * 更新传输状态（后端同步）
     */
    updateTransferStatus(status) {
      emit(UploadEvents.TRANSFER_STATUS_UPDATE, {
        uploadId,
        status,
        timestamp: Date.now()
      });
    },

    // ============ 恢复 Actions ============

    /**
     * 恢复到 waiting 状态
     */
    onResumeToWaiting(needsReSelect) {
      emit(UploadEvents.RESUME_TO_WAITING, {
        uploadId,
        needsReSelect,
        timestamp: Date.now()
      });
    },

    /**
     * 恢复到 calculating 状态
     */
    onResumeToCalculating() {
      emit(UploadEvents.RESUME_TO_CALCULATING, { uploadId });
    },

    /**
     * 恢复到 uploading 状态
     */
    onResumeToUploading() {
      emit(UploadEvents.RESUME_TO_UPLOADING, { uploadId });
    },

    /**
     * 重试
     */
    onRetry() {
      emit(UploadEvents.RETRY, { uploadId });
    },

    /**
     * 普通上传完成
     */
    onNormalUploadComplete() {
      emit(UploadEvents.NORMAL_UPLOAD_COMPLETE, {
        uploadId,
        timestamp: Date.now()
      });
    },

    /**
     * 取消处理
     */
    onCancel() {
      emit(UploadEvents.CANCEL, { uploadId });
    },

    /**
     * 完成处理
     */
    onComplete() {
      emit(UploadEvents.COMPLETE, { uploadId });
    }
  };
}

/**
 * 创建状态进入 Action
 * @param {string} uploadId - 上传任务ID
 * @param {string} state - 状态名称
 * @param {Object} defaultUpdates - 默认更新
 * @returns {Function}
 */
export function createEntryAction(uploadId, state, defaultUpdates = {}) {
  return function entryAction(payload = {}) {
    globalEventBus.emit(UploadEvents.STATUS_CHANGE, {
      uploadId,
      state,
      updates: { ...defaultUpdates, ...payload },
      timestamp: Date.now()
    });
  };
}

/**
 * 创建状态退出 Action
 * @param {string} uploadId - 上传任务ID
 * @param {string} state - 状态名称
 * @returns {Function}
 */
export function createExitAction(uploadId, state) {
  return function exitAction(payload = {}) {
    globalEventBus.emit(`upload:${state}:exit`, {
      uploadId,
      state,
      ...payload,
      timestamp: Date.now()
    });
  };
}

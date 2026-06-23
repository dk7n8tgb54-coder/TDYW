/**
 * DebounceController - 防抖控制器
 * 负责管理批量操作和单任务操作的防抖逻辑
 */

import { action } from 'mobx';
import {
  DEBOUNCE_DELAY_BATCH,
  DEBOUNCE_DELAY_ITEM,
} from '../upload-core-constants';

class DebounceController {
  constructor(coreStore) {
    this.coreStore = coreStore;
    
    // 批量操作防抖定时器
    this._pauseAllDebounceTimer = null;
    this._resumeAllDebounceTimer = null;
    
    // 批量操作执行锁
    this._isPauseAllRunning = false;
    this._isResumeAllRunning = false;
    
    // 单任务操作防抖
    this._itemDebounceTimers = new Map();
    this._isItemOperationRunning = new Set();
  }

  /**
   * 包装 pauseAll 方法，添加防抖
   */
  @action
  async pauseAll() {
    // 防抖检查：如果300ms内已有调用，忽略本次
    if (this._pauseAllDebounceTimer) {
      clearTimeout(this._pauseAllDebounceTimer);
    }

    // 如果正在执行，延迟到下次
    if (this._isPauseAllRunning) {
      this._pauseAllDebounceTimer = setTimeout(() => {
        this._pauseAllDebounceTimer = null;
        this.pauseAll();
      }, DEBOUNCE_DELAY_BATCH);
      return;
    }

    this._isPauseAllRunning = true;

    try {
      await this._doPauseAll();
    } finally {
      // 延迟重置执行锁，防止立即重复点击
      setTimeout(() => {
        this._isPauseAllRunning = false;
      }, DEBOUNCE_DELAY_BATCH);
    }
  }

  /**
   * 实际的暂停逻辑
   */
  async _doPauseAll() {
    const { coreStore } = this;
    coreStore.isPaused = true;
    coreStore.isCancelled = false;

    // 使用状态机批量操作
    if (coreStore.stateMachineManager) {
      const results = coreStore.stateMachineManager.batchPause();

      // 收集需要同步到后端的transferIds
      const { FINAL_STATES } = require('../upload-core-constants');
      const transferIds = [];
      results.filter(r => r.success).forEach(({ uploadId }) => {
        const item = coreStore.queueStore.findUploadItemInCurrentTenant(uploadId);
        // 跳过终态任务，避免将已完成任务同步为暂停
        if (item?.transferId && !FINAL_STATES.includes(item.status)) {
          transferIds.push(item.transferId);
        }
      });

      // 同步到后端
      if (transferIds.length > 0) {
        try {
          await coreStore.transferStore.batchPauseTransfers(transferIds);
        } catch (error) {
          coreStore.failedSyncTransfers = transferIds;
          const { message } = require('antd');
          message.warning('部分任务状态同步失败，刷新页面后将自动校正');
        }
      }
    }
  }

  /**
   * 包装 resumeAll 方法，添加防抖
   */
  @action
  async resumeAll() {
    // 防抖检查：如果300ms内已有调用，忽略本次
    if (this._resumeAllDebounceTimer) {
      clearTimeout(this._resumeAllDebounceTimer);
    }

    // 如果正在执行，延迟到下次
    if (this._isResumeAllRunning) {
      this._resumeAllDebounceTimer = setTimeout(() => {
        this._resumeAllDebounceTimer = null;
        this.resumeAll();
      }, DEBOUNCE_DELAY_BATCH);
      return;
    }

    this._isResumeAllRunning = true;

    try {
      await this._doResumeAll();
    } finally {
      // 延迟重置执行锁，防止立即重复点击
      setTimeout(() => {
        this._isResumeAllRunning = false;
      }, DEBOUNCE_DELAY_BATCH);
    }
  }

  /**
   * 实际的恢复逻辑
   */
  async _doResumeAll() {
    const { coreStore } = this;
    const { MAX_CONCURRENT_UPLOADS } = require('../upload-core-constants');
    
    coreStore.isPaused = false;
    coreStore.isCancelled = false;

    // 使用状态机批量操作
    if (coreStore.stateMachineManager) {
      // 传入并发限制，防止一次性恢复所有任务突破限制
      // 【7.2 统一并发槽位口径】getActiveCount 改用状态机状态计数
      //   calculating + uploading 占用前端上传槽位；merging 不占
      const results = coreStore.stateMachineManager.batchResume(
        MAX_CONCURRENT_UPLOADS,
        () => coreStore.stateMachineManager.countByStates(['calculating', 'uploading'])
      );
      const successCount = results.filter(r => r.success).length;

      // 收集需要同步到后端的transferIds
      const transferIds = [];
      results.filter(r => r.success).forEach(({ uploadId }) => {
        const item = coreStore.queueStore.findUploadItemInCurrentTenant(uploadId);
        if (item?.transferId) {
          transferIds.push(item.transferId);
        }
      });

      // 同步到后端
      if (transferIds.length > 0) {
        try {
          await coreStore.transferStore.batchResumeTransfers(transferIds);
        } catch (error) {
          // 批量恢复后端记录失败，静默处理
        }
      }

      // 当任务完成时自动恢复等待中的任务，保持并发数
      if (successCount > 0 && coreStore.recoveryCoordinator) {
        coreStore.recoveryCoordinator.schedule();
      }
    }
  }

  /**
   * 单任务操作防抖包装
   * @param {string} itemId - 任务ID
   * @param {Function} operation - 要执行的操作
   */
  @action
  async wrapItemOperation(itemId, operation) {
    // 防抖检查：如果200ms内已有调用，忽略本次
    if (this._itemDebounceTimers.has(itemId)) {
      clearTimeout(this._itemDebounceTimers.get(itemId));
    }

    // 如果正在执行，延迟到下次
    if (this._isItemOperationRunning.has(itemId)) {
      this._itemDebounceTimers.set(itemId, setTimeout(() => {
        this._itemDebounceTimers.delete(itemId);
        this.wrapItemOperation(itemId, operation);
      }, DEBOUNCE_DELAY_ITEM));
      return;
    }

    this._isItemOperationRunning.add(itemId);

    try {
      await operation();
    } finally {
      // 延迟重置执行锁，防止立即重复点击
      setTimeout(() => {
        this._isItemOperationRunning.delete(itemId);
      }, DEBOUNCE_DELAY_ITEM);
    }
  }

  /**
   * 清理所有防抖定时器
   */
  cleanup() {
    if (this._pauseAllDebounceTimer) {
      clearTimeout(this._pauseAllDebounceTimer);
      this._pauseAllDebounceTimer = null;
    }
    if (this._resumeAllDebounceTimer) {
      clearTimeout(this._resumeAllDebounceTimer);
      this._resumeAllDebounceTimer = null;
    }
    
    this._itemDebounceTimers.forEach((timer) => {
      clearTimeout(timer);
    });
    this._itemDebounceTimers.clear();
    this._isItemOperationRunning.clear();
  }
}

export default DebounceController;

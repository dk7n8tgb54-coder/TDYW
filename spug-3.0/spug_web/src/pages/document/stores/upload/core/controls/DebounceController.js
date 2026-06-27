/**
 * DebounceController - 防抖控制器
 * 负责管理批量操作和单任务操作的防抖逻辑
 */

import { action } from 'mobx';
import {
  DEBOUNCE_DELAY_BATCH,
  DEBOUNCE_DELAY_ITEM,
} from '../upload-core-constants';
import { fetchBackendStatusMap, shouldResumeBackendPaused } from './resumeAllStatus';

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
   * 【P1强化 2026-06-27】批量恢复改为按队列 item 扫描，避免漏掉懒创建状态机的 paused 任务
   *
   * 处理规则：
   * - paused：无论有没有 machine，都纳入恢复处理；没有 machine 时先确认后端 PAUSED，再转回 waiting 调度
   * - waiting：不主动同步后端，交给 uploadCoordinator.startWaiting() 调度
   * - uploading/calculating/merging/completed/error/cancelled：跳过
   */
  async _doResumeAll() {
    const { coreStore } = this;
    const { UPLOAD_STATUS, TERMINAL_STATUSES } = require('../upload-core-constants');

    coreStore.isPaused = false;
    coreStore.isCancelled = false;

    if (!coreStore.stateMachineManager) {
      return;
    }

    // 1. 扫描当前租户队列，收集需要恢复的 paused 任务
    const tenantId = coreStore.getCurrentTenantId();
    const queue = coreStore.queueStore.uploadQueue[tenantId] || [];
    const pausedItems = [];
    const skippedTerminal = [];

    queue.forEach(item => {
      if (item.status === UPLOAD_STATUS.PAUSED) {
        pausedItems.push(item);
      } else if (TERMINAL_STATUSES.includes(item.status) ||
                 item.status === UPLOAD_STATUS.UPLOADING ||
                 item.status === UPLOAD_STATUS.CALCULATING ||
                 item.status === UPLOAD_STATUS.MERGING) {
        // 终态和进行中状态跳过
        skippedTerminal.push(item.id);
      }
      // waiting 不在这里处理，交给 startWaiting 调度
    });

    // 2. 为每个 paused item 尝试恢复（优先状态机路径）
    const resumeResults = [];
    const backendStatusMap = await this._fetchCurrentBackendStatusMap(pausedItems);

    for (const item of pausedItems) {
      let machine = coreStore.stateMachineManager.get(item.id);
      if (!machine) {
        // paused 但无状态机（懒创建场景下理论上少见，但防御性处理）
        machine = coreStore.uploadCoordinator?.ensureStateMachine?.(item) || null;
        if (!machine) {
          console.warn(`[DebounceController] resumeAll: ${item.id} 状态机重建失败，跳过`);
          continue;
        }

        if (shouldResumeBackendPaused(item, backendStatusMap)) {
          resumeResults.push({
            uploadId: item.id,
            success: true,
            state: machine.getState(),
            transferId: item.transferId,
            source: 'backend-paused-without-machine',
          });
        }

        // 重建后 machine 是 waiting；把本地 item 也切回 waiting，统一交给 startWaiting。
        coreStore.queueStore.updateUploadItem(item.id, {
          status: UPLOAD_STATUS.WAITING,
          error: null,
          canAbort: false,
          isPausedByUser: false,
        });
        continue;
      }

      if (machine.canTransition('RESUME')) {
        const success = machine.transition('RESUME');
        resumeResults.push({ uploadId: item.id, success, state: machine.getState() });
      }
    }

    const successCount = resumeResults.filter(r => r.success).length;

    // 3. 收集需要同步后端的 transferIds（仅同步实际恢复成功的）
    const transferIds = [];
    resumeResults.filter(r => r.success).forEach(({ uploadId }) => {
      const item = coreStore.queueStore.findUploadItemInCurrentTenant(uploadId);
      if (item?.transferId) {
        transferIds.push(item.transferId);
      }
    });

    if (transferIds.length > 0) {
      try {
        await coreStore.transferStore.batchResumeTransfers(transferIds);
      } catch (error) {
        // 批量恢复后端记录失败，静默处理
      }
    }

    // 4. 启动 waiting 任务（覆盖懒创建状态机场景 + 刚从 paused 恢复但因槽位不足未启动的）
    if (coreStore.uploadCoordinator) {
      coreStore.uploadCoordinator.startWaiting();
    }

    // 5. 调度恢复协调器，保持并发数
    if (successCount > 0 && coreStore.recoveryCoordinator) {
      coreStore.recoveryCoordinator.schedule();
    }
  }

  async _fetchCurrentBackendStatusMap(items) {
    const { coreStore } = this;
    const transferIds = items
      .map(item => item.transferId)
      .filter(Boolean);
    const isPublic = coreStore.rootStore?.navigationStore?.isPublic || false;
    return fetchBackendStatusMap({
      transferStore: coreStore.transferStore,
      transferIds,
      isPublic,
    });
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

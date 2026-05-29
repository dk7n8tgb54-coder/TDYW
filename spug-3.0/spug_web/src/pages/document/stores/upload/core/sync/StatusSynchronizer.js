/**
 * StatusSynchronizer - 状态同步器
 * 负责前后端传输状态的同步和映射
 */

import { action } from 'mobx';
import { BACKEND_STATUS_MAP } from '../upload-core-constants';

class StatusSynchronizer {
  constructor(coreStore) {
    this.coreStore = coreStore;
    this._lastSyncStatusMap = new Map();
  }

  /**
   * 同步前后端传输状态
   * 在页面初始化或检测到状态不一致时调用
   * @param {boolean} isPublic - 是否公共空间
   * @returns {Promise<void>}
   */
  @action
  async syncTransferStatus(isPublic = false) {
    const { coreStore } = this;
    
    try {
      const transfers = await coreStore.transferStore.fetchTransfers(isPublic);
      const uploadQueue = coreStore.queueStore.currentUploadQueue;

      let syncCount = 0;
      uploadQueue.forEach(item => {
        if (item.transferId) {
          const backendTransfer = transfers.find(t => t.id === item.transferId);
          if (backendTransfer) {
            const backendStatus = this.mapBackendStatus(backendTransfer.status);
            if (backendStatus && backendStatus !== item.status) {
              console.warn(`[syncTransferStatus] 状态不一致: ${item.name}, 前端=${item.status}, 后端=${backendStatus}`);
              // 【修复】使用 updateUploadItem 代替直接修改
              const updateData = { status: backendStatus };
              if (backendStatus === 'completed') {
                updateData.percent = 100;
                updateData.error = null;
              } else if (backendStatus === 'error') {
                updateData.error = backendTransfer.error || '上传失败';
              }
              coreStore.queueStore.updateUploadItem(item.id, updateData);
              syncCount++;
            }
          }
        }
      });

      // 清除已同步的失败记录
      if (coreStore.failedSyncTransfers) {
        coreStore.failedSyncTransfers = [];
      }
    } catch (error) {
      // 状态校对失败，静默处理
    }
  }

  /**
   * 后端状态映射到前端状态
   * @param {string} backendStatus - 后端状态
   * @returns {string|null} 前端状态
   */
  mapBackendStatus(backendStatus) {
    return BACKEND_STATUS_MAP[backendStatus] || null;
  }

  /**
   * 将前端状态同步到后端
   * @param {string} uploadId - 上传ID
   * @param {string} toState - 目标状态
   * @param {object} payload - 附加数据
   */
  @action
  async syncStateToBackend(uploadId, toState, payload) {
    const { coreStore } = this;
    const item = coreStore.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (!item?.transferId) {
      console.log(`[StatusSynchronizer] ${uploadId}: 无transferId，跳过同步`);
      return;
    }

    // waiting 是前端调度态，后端创建记录时已是 PENDING，不再重复回写避免状态回退
    if (toState === 'waiting') {
      return;
    }

    // 如果当前已经是终态，不允许状态回退
    const { FINAL_STATES } = require('../upload-core-constants');
    if (FINAL_STATES.includes(item.status)) {
      console.log(`[StatusSynchronizer] ${uploadId}: 已是终态(${item.status})，跳过同步`);
      return;
    }

    // 状态映射：前端状态 -> 后端状态
    const { FRONTEND_STATUS_MAP } = require('../upload-core-constants');
    const backendStatus = FRONTEND_STATUS_MAP[toState];
    if (!backendStatus) {
      console.log(`[StatusSynchronizer] ${uploadId}: 无法映射状态 ${toState}`);
      return;
    }

    try {
      // 避免重复同步相同状态
      const lastStatus = this._lastSyncStatusMap.get(item.transferId);
      if (lastStatus === backendStatus) {
        console.log(`[StatusSynchronizer] ${uploadId}: 状态未变化(${backendStatus})，跳过同步`);
        return;
      }
      this._lastSyncStatusMap.set(item.transferId, backendStatus);

      console.log(`[StatusSynchronizer] ${uploadId}: 同步状态 ${toState} -> ${backendStatus}`);
      await coreStore.transferStore.updateTransferStatus(item.transferId, backendStatus);
      console.log(`[StatusSynchronizer] ${uploadId}: 同步成功`);
    } catch (error) {
      console.error(`[StatusSynchronizer] ${uploadId}: 同步失败`, error);
      // 静默处理，不阻塞状态流转
    }
  }

  /**
   * 清理同步状态缓存
   */
  cleanup() {
    this._lastSyncStatusMap.clear();
  }
}

export default StatusSynchronizer;

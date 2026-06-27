/**
 * StatusSynchronizer - 状态同步器
 * 负责前后端传输状态的同步和映射
 *
 * 【P0修复 2026-06-27】移除 @action 装饰器
 * 原因：@action 需要 Babel decorator 插件支持，但 jest 测试环境未配置该插件，
 * 导致 StatusSynchronizer.test.js 无法加载。经检查，这两个方法不直接修改 MobX
 * observable（updateUploadItem 已在 queueStore 中被 @action 包裹，
 * failedSyncTransfers 是普通属性非 @observable），移除 @action 无副作用。
 */

import { BACKEND_STATUS_MAP, FINAL_STATES, FRONTEND_STATUS_MAP } from '../upload-core-constants';

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
  async syncStateToBackend(uploadId, toState, payload) {
    const { coreStore } = this;
    const item = coreStore.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (!item?.transferId) {
      return;
    }

    // waiting 是前端调度态，后端创建记录时已是 PENDING，不再重复回写避免状态回退
    if (toState === 'waiting') {
      return;
    }

    // 如果当前已经是终态，不允许非终态状态回退；终态自身仍必须同步到后端。
    if (FINAL_STATES.includes(item.status) && !FINAL_STATES.includes(toState)) {
      return;
    }

    const backendStatus = FRONTEND_STATUS_MAP[toState];
    if (!backendStatus) {
      return;
    }

    // 与 StoreEventAdapter 共用的去重检查
    if (!this.shouldSync(item.transferId, backendStatus)) {
      return;
    }
    this.markSynced(item.transferId, backendStatus);

    try {
      await coreStore.transferStore.updateTransferStatus(item.transferId, backendStatus);
    } catch (error) {
      console.error(`[StatusSynchronizer] ${uploadId}: 同步失败`, error);
      // 静默处理，不阻塞状态流转
    }
  }

  /**
   * 检查是否需要同步（与 StoreEventAdapter 共用，避免重复请求后端）
   * @param {number} transferId - 后端传输记录ID
   * @param {string} backendStatus - 目标后端状态（如 'COMPLETED'、'CANCELED'）
   * @returns {boolean} true 表示需要同步
   */
  shouldSync(transferId, backendStatus) {
    const lastStatus = this._lastSyncStatusMap.get(transferId);
    return lastStatus !== backendStatus;
  }

  /**
   * 标记某 transferId 已同步到指定后端状态
   * @param {number} transferId - 后端传输记录ID
   * @param {string} backendStatus - 已同步的后端状态
   */
  markSynced(transferId, backendStatus) {
    this._lastSyncStatusMap.set(transferId, backendStatus);
  }

  /**
   * 清理同步状态缓存
   */
  cleanup() {
    this._lastSyncStatusMap.clear();
  }
}

export default StatusSynchronizer;

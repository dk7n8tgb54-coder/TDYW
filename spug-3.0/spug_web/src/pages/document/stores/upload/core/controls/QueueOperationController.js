/**
 * QueueOperationController - 队列操作控制器
 * 负责处理批量操作：cancelAll, removeAll
 */
import { action } from 'mobx';
import { message } from 'antd';
import { DISPLAY_UPLOADING_STATUSES } from '../upload-core-constants';

export class QueueOperationController {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 取消所有任务
   */
  @action
  async cancelAll() {
    this.core.isCancelled = true;
    this.core.isPaused = false;
    this.core.pendingFiles = [];
    
    // 【移除】clearPendingDisplayQueue 调用，pendingDisplayQueue 已删除

    const transferIds = [];

    // 【TODO 7.1 状态机唯一入口例外点】cancelAll 批量取消直接写 status:'cancelled' 绕过状态机。
    // 原因：批量取消需要"立即中止所有网络请求 + 立即更新 UI"，逐个 transition('CANCEL') 难以保证
    // 正在 uploading/merging 的任务能立即中断请求（CANCEL 事件会触发 onUploadingExit → abortUpload，
    // 但异步链路较长）。当前实现直接 abortToken.cancel + updateUploadItem 是经过验证的可靠中断方式。
    // 风险：状态机 currentState 与 item.status 可能短暂不一致（assertStatusConsistency 会兜底修复）。
    // 后续优化：可改造为 stateMachineManager.batchCancel() + 统一资源清理，但需充分回归测试。
    // 详见《资料库并发上传与状态机修复方案.md》7.1 节。
    Object.keys(this.core.uploadQueue).forEach(tenantId => {
      this.core.uploadQueue[tenantId].forEach(item => {
        // 【7.3 异步操作加版本号】cancelAll 绕过状态机直接写状态，
        // 需为每个任务递增版本号，使旧异步回调失效
        this.core.queueStore.bumpOperationVersion(item.id);

        if (item.canAbort && item.abortToken) {
          item.abortToken.cancel('用户取消');
        }
        // 【修复】使用 updateUploadItem 代替直接修改
        this.core.queueStore.updateUploadItem(item.id, {
          status: 'cancelled',
          error: '已取消',
          errorCode: 'CANCELLED',
          canAbort: false,
          percent: 0,
        });

        if (item.transferId) {
          transferIds.push(item.transferId);
        }
      });
    });

    // 清理uniqueKeys
    Object.keys(this.core.uploadQueue).forEach(tenantId => {
      this.core.uploadQueue[tenantId].forEach(item => {
        if (item.uniqueKey && item.file) {
          const { file, folderId } = item;
          const isPublic = item.isPublic !== undefined ? item.isPublic : this.core.rootStore.navigationStore?.isPublic;
          this.core.queueStore.removeUniqueKey(file, folderId, isPublic);
        }
      });
    });

    // @deprecated 【7.2 统一并发槽位口径】activeUploads 不再参与调度决策。
    //   并发槽位以状态机状态计数为准，cancelAll 后所有状态机进入终态，
    //   countByStates 自然归零。此行保留为防御性清零，避免历史 UI 残留。
    this.core.queueStore.activeUploads = 0;

    // 使用批量API替代循环逐个调用
    if (transferIds.length > 0) {
      try {
        await this.core.transferStore.batchCancelTransfers(transferIds);
      } catch (error) {
        // 批量操作失败时，静默处理（前端状态已更新）
      }
    }
  }

  /**
   * 移除所有已完成/失败的任务
   * 【P0修复 2026-06-27】使用 DISPLAY_UPLOADING_STATUSES 常量替代硬编码
   * 之前 activeStatuses = ['uploading', 'calculating', 'merging'] 遗漏了 waiting 和 paused，
   * 导致 removeAll 会误删等待中和已暂停的任务
   */
  @action
  async removeAll() {
    const transferIds = [];

    const uploadQueue = this.core.queueStore.uploadQueue;

    Object.keys(uploadQueue).forEach(tenantId => {
      const queue = uploadQueue[tenantId];
      if (!queue || !Array.isArray(queue)) return;

      // 保留仍在进行中的任务（waiting/calculating/uploading/paused/merging）
      const itemsToRemove = queue.filter(item => !DISPLAY_UPLOADING_STATUSES.includes(item.status));

      itemsToRemove.forEach(item => {
        if (item.uniqueKey && item.file) {
          const { file, folderId } = item;
          const isPublic = item.isPublic !== undefined ? item.isPublic : this.core.rootStore.navigationStore?.isPublic;
          this.core.queueStore.removeUniqueKey(file, folderId, isPublic);
        }
        if (item.transferId) {
          transferIds.push(item.transferId);
        }
      });

      uploadQueue[tenantId] = queue.filter(item => DISPLAY_UPLOADING_STATUSES.includes(item.status));
    });

    if (transferIds.length > 0) {
      try {
        for (const id of transferIds) {
          await this.core.transferStore.deleteTransfer(id);
        }
      } catch (error) {
        message.warning('批量删除后端记录失败，请稍后重试');
      }
    }
  }
}

export default QueueOperationController;

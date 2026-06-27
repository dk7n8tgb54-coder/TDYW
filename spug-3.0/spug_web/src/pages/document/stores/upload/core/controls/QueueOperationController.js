/**
 * QueueOperationController - 队列操作控制器
 * 负责处理批量操作：removeAll（清空已结束任务）
 *
 * 【方向B 2026-06-27】已删除 cancelAll 方法
 * 原因：0 外部调用方（前端无批量取消按钮），仅在 destroy() 内部调用
 * destroy 场景不应取消用户任务，只应清理资源
 * 未来如需批量取消，应走 stateMachineManager.batchCancel()（逐个 transition('CANCEL')）
 */
import { action } from 'mobx';
import { message } from 'antd';
import { DISPLAY_UPLOADING_STATUSES } from '../upload-core-constants';

export class QueueOperationController {
  constructor(coreStore) {
    this.core = coreStore;
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

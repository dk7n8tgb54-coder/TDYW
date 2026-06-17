/**
 * UploadLifecycle - 上传生命周期管理
 * 负责处理上传完成、错误、计算状态等生命周期事件
 */
import { action } from 'mobx';

export class UploadLifecycle {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 【状态机】上传完成处理
   * @param {string} uploadId - 上传任务ID
   */
  @action
  onCompleted(uploadId) {
    // 【关键修复】不再在此处递减 activeUploads
    // handleUploadingState 的 finally 块已统一处理递减（成功/失败/异常均覆盖）
    // 此处再递减会导致双重递减（小文件直通 completed + 大文件 merging→completed 均受影响）

    // 【关键修复】上传完成后，检查是否有暂停的任务需要自动恢复
    if (this.core.recoveryCoordinator) {
      this.core.recoveryCoordinator.schedule();
    }
    
    // 【新增】从等待显示队列补充新任务到显示队列，并启动waiting任务
    const item = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
    
    // 【修复】使用setTimeout确保MobX状态更新完成后再补充队列和启动任务
    setTimeout(() => {
      if (this.core.displayCoordinator) {
        this.core.displayCoordinator.replenish();
      }
      // 【P0修复】强制重置暂停状态，确保新任务可以启动
      this.core.isPaused = false;
      // 【关键】补充队列后，启动所有可运行的waiting任务
      if (this.core.uploadCoordinator) {
        this.core.uploadCoordinator.startWaiting();
      }
    }, 100); // 【P0修复】增加延迟，确保状态完全更新
  }

  /**
   * 【状态机】上传错误处理
   * @param {string} uploadId - 上传任务ID
   * @param {Object} payload - 错误信息
   */
  @action
  onError(uploadId, payload) {
    // 错误处理逻辑
    // 【新增】从等待显示队列补充新任务到显示队列（即使失败也补充）
    // 【修复】使用setTimeout确保MobX状态更新完成后再补充队列和启动任务
    setTimeout(() => {
      if (this.core.displayCoordinator) {
        this.core.displayCoordinator.replenish();
      }
      // 【关键】补充队列后，启动所有可运行的waiting任务
      if (this.core.uploadCoordinator) {
        this.core.uploadCoordinator.startWaiting();
      }
    }, 0);
  }

  /**
   * 【状态机】处理calculating状态 - 触发MD5计算
   * 【优化】小于32MB的文件跳过MD5计算，直接转换到waiting状态
   * @param {string} uploadId - 上传任务ID
   * @param {string} fromState - 来源状态
   */
  @action
  async onCalculating(uploadId, fromState) {
    const item = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (!item) {
      console.error(`[UploadLifecycle] ${uploadId}: 未找到上传项!`);
      return;
    }
    if (item.status === 'paused') {
      return;
    }

    // 【优化】小于32MB的文件跳过MD5计算
    const SKIP_MD5_THRESHOLD = 32 * 1024 * 1024; // 32MB
    if (item.fileSize < SKIP_MD5_THRESHOLD) {
      // 小文件使用空hash，直接触发状态转换：calculating -> waiting
      const stateMachine = this.core.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        stateMachine.transition('MD5_COMPLETE', { fileHash: '' });
      }
      return;
    }

    try {
      // 更新状态为计算中
      this.core.queueStore.updateUploadItem(uploadId, {
        status: 'calculating',
      });

      // 计算MD5（仅大文件）
      const fileHash = await this.core.md5Store?.calculateFileMD5(item.file, uploadId);
      
      // 更新item的fileHash
      item.fileHash = fileHash;

      // 触发状态转换：calculating -> waiting
      const stateMachine = this.core.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        stateMachine.transition('MD5_COMPLETE', { fileHash });
      }
    } catch (error) {
      console.error(`[UploadLifecycle] ${uploadId}: MD5计算失败`, error);
      // 计算失败，触发错误状态
      const stateMachine = this.core.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        stateMachine.transition('ERROR', { error });
      }
    }
  }

  /**
   * 上传完成后清理资源
   * @param {string} uploadId - 上传任务ID
   */
  @action
  cleanupAfterUpload(uploadId) {
    // 清理AbortController
    const item = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (item?.abortController) {
      item.abortController = null;
    }
    
    // 清理cancelToken
    if (this.core.cancelTokenSources.has(uploadId)) {
      this.core.cancelTokenSources.delete(uploadId);
    }
  }
}

export default UploadLifecycle;

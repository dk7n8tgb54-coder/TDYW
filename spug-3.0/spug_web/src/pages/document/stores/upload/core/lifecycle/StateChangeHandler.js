/**
 * StateChangeHandler - 状态变更处理器
 * 负责处理状态机的状态变更回调
 */
import { FINAL_STATES, FRONTEND_STATUS_MAP } from '../upload-core-constants';

export class StateChangeHandler {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 【状态机】状态变更回调 - 主入口
   * @param {string} fromState - 来源状态
   * @param {string} toState - 目标状态
   * @param {string} event - 触发事件
   * @param {Object} payload - 附加数据
   * @param {string} uploadId - 上传任务ID
   */
  handle(fromState, toState, event, payload, uploadId) {
    // 【关键修复】如果目标状态是paused，检查当前任务是否已经是终态，防止终态任务被暂停
    if (toState === 'paused') {
      const item = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
      // 【严重修复 H-03】'cancelled' 现在是正式状态，保留在终态列表中
      if (item && FINAL_STATES.includes(item.status)) {
        console.log(`[StateChangeHandler] ${uploadId}: 跳过终态任务的暂停操作`);
        return;
      }
    }
    
    // 【P2修复】状态持久化同步：将状态变更同步到后端
    try {
      if (this.core.statusSynchronizer) {
        this.core.statusSynchronizer.syncStateToBackend(uploadId, toState, payload);
      }
    } catch (syncError) {
      console.error(`[StateChangeHandler] ${uploadId}: 状态同步失败`, syncError);
      // 继续处理，不阻塞状态流转
    }
    
    // 特殊处理
    if (toState === 'completed') {
      if (this.core.uploadLifecycle) {
        this.core.uploadLifecycle.onCompleted(uploadId);
      }
    } else if (toState === 'error') {
      if (this.core.uploadLifecycle) {
        this.core.uploadLifecycle.onError(uploadId, payload);
      }
    } else if (toState === 'cancelled') {
      // 取消状态不触发额外处理，由状态机entry钩子处理
    } else if (toState === 'uploading') {
      // 【关键修复】状态变为uploading时，触发实际上传逻辑
      this.handleUploadingState(uploadId, fromState);
    } else if (toState === 'calculating') {
      // 【关键修复】状态变为calculating时，触发MD5计算
      if (this.core.uploadLifecycle) {
        this.core.uploadLifecycle.onCalculating(uploadId, fromState);
      } else {
        console.error(`[StateChangeHandler] ${uploadId}: uploadLifecycle 未初始化!`);
      }
    } else if (toState === 'merging') {
      // 【关键修复】状态变为merging时，触发合并操作
      this.handleMergingState(uploadId, fromState);
      
      // 【关键修复】merging状态不占用并发槽位，立即启动等待中的任务
      if (this.core.uploadCoordinator) {
        this.core.uploadCoordinator.processPending();
      }
    }

    // 【Loop-200修复】终态释放状态机：completed/error/cancelled 后懒释放
    // 避免状态机数量随总任务数增长；onCompleted/onError 不引用本任务状态机，释放安全
    // setTimeout(0) 确保当前 handle 回调链执行完毕后再移除
    // 【Loop-1003修复】释放后立即触发 processPending，让 waiting 任务顶上来
    if (FINAL_STATES.includes(toState)) {
      const idToRemove = uploadId;
      setTimeout(() => {
        if (this.core.stateMachineManager) {
          this.core.stateMachineManager.remove(idToRemove);
        }
        // 释放后触发调度，让 waiting 任务顶上来
        if (this.core.uploadCoordinator) {
          this.core.uploadCoordinator.processPending();
        }
      }, 0);
    }
  }

  /**
   * 【状态机】处理uploading状态 - 触发实际上传
   * 【P2-架构说明】当前状态机回调中包含业务逻辑，建议未来重构为：
   *   1. 状态机只负责状态流转，通过事件通知外部
   *   2. 业务逻辑（上传/MD5计算）由 UploadCoreStore 订阅事件后执行
   *   3. 实现真正的状态机与业务逻辑解耦
   */
  async handleUploadingState(uploadId, fromState) {
    const item = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (!item) {
      return;
    }
    if (!item.file) {
      return;
    }

    // 【P0修复】检查是否所有分片已上传完成（从paused恢复时）
    const { UPLOAD_CONSTANTS } = require('../upload-core-constants');
    const chunkCount = Math.ceil(item.fileSize / UPLOAD_CONSTANTS.CHUNK_SIZE);
    const uploadedChunks = item.currentChunk || 0;
    if (fromState === 'paused' && uploadedChunks >= chunkCount && uploadedChunks > 0) {
      
      // 【关键修复】检查后端状态，如果已经在合并中，直接进入merging状态
      if (item.transferStatus === 'MERGING' || item.status === 'merging') {
        const stateMachine = this.core.stateMachineManager?.get(uploadId);
        if (stateMachine) {
          stateMachine.transition('UPLOAD_COMPLETE');
        }
        this.core.queueStore.decrementActiveUploads();
        return;
      }
      
      // 触发状态转换：uploading -> merging
      const stateMachine = this.core.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        stateMachine.transition('UPLOAD_COMPLETE');
      }
      // 【P0修复】递减activeUploads，因为跳过了实际上传
      this.core.queueStore.decrementActiveUploads();
      return;
    }

    // 【M-03修复】等待并发槽位
    const { MAX_CONCURRENT_UPLOADS, CONCURRENT_SLOT_WAIT_INTERVAL } = require('../upload-core-constants');
    while (this.core.activeUploads >= MAX_CONCURRENT_UPLOADS) {
      if (this.core.isCancelled || this.core.isPaused) {
        return;
      }
      await new Promise(resolve => setTimeout(resolve, CONCURRENT_SLOT_WAIT_INTERVAL));
    }

    // 【P0修复】占用一个并发槽位
    this.core.queueStore.incrementActiveUploads();

    // 更新item状态
    // 【7.1 状态机唯一入口】不写 status:'uploading'/canAbort/isPausedByUser/isCancelledByUser
    // - status/canAbort 由状态机 onUploadingEntry 写
    // - isPausedByUser/isCancelledByUser 由状态机 onUploadingEntry 重置
    // 此处仅做资源管理：创建 abortController（上传中止需要）
    this.core.queueStore.updateUploadItem(uploadId, {
      error: null,
      abortController: new AbortController()
    });

    // 【P0修复】统一处理所有可上传的源状态
    const { UPLOADABLE_FROM_STATES } = require('../upload-core-constants');
    if (UPLOADABLE_FROM_STATES.includes(fromState)) {
      try {
        await this.startUpload(item);
      } catch (error) {
        // 触发错误状态转换
        const stateMachine = this.core.stateMachineManager ? this.core.stateMachineManager.get(uploadId) : null;
        if (stateMachine) {
          stateMachine.transition('ERROR', { error });
        }
      } finally {
        // 【P0修复】确保activeUploads递减，并处理等待队列
        this.core.queueStore.decrementActiveUploads();
        if (this.core.uploadCoordinator) {
          this.core.uploadCoordinator.processPending();
        }
      }
    } else {
      // 未知来源状态，递减计数避免泄漏
      this.core.queueStore.decrementActiveUploads();
    }
  }

  /**
   * 【状态机】处理merging状态 - 触发合并操作
   * 【关键修复】将合并操作从uploadFileChunked中分离，让uploading状态先结束
   * @param {string} uploadId - 上传任务ID
   * @param {string} fromState - 来源状态
   */
  async handleMergingState(uploadId, fromState) {
    const item = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (!item) {
      console.error(`[StateChangeHandler] ${uploadId}: 未找到上传项，无法执行合并`);
      return;
    }

    console.log(`[StateChangeHandler] ${uploadId}: 开始执行合并操作`);

    try {
      const folderId = item.folderId !== null ? item.folderId : this.core.rootStore.navigationStore?.currentFolderId;
      
      // 执行合并操作
      const mergeResult = await this.core.chunkUploadStore.mergeChunks(
        item.file, 
        uploadId, 
        Math.ceil(item.fileSize / require('../upload-core-constants').UPLOAD_CONSTANTS.CHUNK_SIZE),
        item.fileHash,
        folderId,
        item.isPublic
      );
      
      // 【修复】合并成功，先更新资源/展示字段，再触发状态转换（让状态机 onCompletedEntry 写 status）
      if (mergeResult && mergeResult.success) {
        // 【7.1 状态机唯一入口】不写 status:'completed'/canAbort，由状态机 onCompletedEntry 写
        // 仅做资源清理与 completedAt 记录
        this.core.queueStore.updateUploadItem(uploadId, {
          percent: 100,
          abortToken: null,
          abortController: null,
          error: null,
          completedAt: Date.now(),
        });
        
        // 同步后端传输记录
        if (item.transferId && this.core.transferStore) {
          try {
            await this.core.transferStore.completeTransfer(item.transferId);
          } catch (error) {
            console.warn(`[StateChangeHandler] ${uploadId}: 传输记录同步失败`, error);
          }
        }
        
        // 触发刷新
        this.core.queueStore.triggerRefresh();
        
        // 触发 MERGE_SUCCESS 状态转换：merging -> completed（状态机 onCompletedEntry 写 status/canAbort）
        const stateMachine = this.core.stateMachineManager?.get(uploadId);
        if (stateMachine) {
          stateMachine.transition('MERGE_SUCCESS');
        }
      }
    } catch (error) {
      // 【修复】获取错误消息，处理多种可能的错误结构
      const errorMessage = error.message || error.response?.data?.error || error.error || String(error);
      
      // 【修复】如果错误是"正在合并中"，说明合并实际上在进行，尝试轮询状态
      if (errorMessage.includes('正在合并')) {
        console.log(`[StateChangeHandler] ${uploadId}: 文件正在合并中，开始轮询状态`);
        
        // 尝试从错误响应中获取task_id
        const existingTaskId = item.celeryTaskId || error.response?.data?.task_id;
        if (existingTaskId) {
          try {
            // 轮询合并状态
            await this.core.chunkUploadStore.pollMergeStatus(null, existingTaskId);
            
            // 轮询成功，更新资源/展示字段（不写 status，由状态机 onCompletedEntry 写）
            this.core.queueStore.updateUploadItem(uploadId, {
              percent: 100,
              abortToken: null,
              abortController: null,
              error: null,
              completedAt: Date.now(),
            });
            
            // 同步后端传输记录
            if (item.transferId && this.core.transferStore) {
              try {
                await this.core.transferStore.completeTransfer(item.transferId);
              } catch (syncError) {
                console.warn(`[StateChangeHandler] ${uploadId}: 传输记录同步失败`, syncError);
              }
            }
            
            this.core.queueStore.triggerRefresh();
            
            // 触发 MERGE_SUCCESS 状态转换：merging -> completed
            const stateMachine = this.core.stateMachineManager?.get(uploadId);
            if (stateMachine) {
              stateMachine.transition('MERGE_SUCCESS');
            }
            return;
          } catch (pollError) {
            console.error(`[StateChangeHandler] ${uploadId}: 轮询合并状态失败`, pollError);
            // 轮询失败，标记为错误
            const stateMachine = this.core.stateMachineManager?.get(uploadId);
            if (stateMachine) {
              stateMachine.transition('ERROR', { error: '合并状态查询失败: ' + pollError.message });
            }
            return;
          }
        }
        
        // 没有task_id，保持 merging 状态，依赖状态同步
        console.log(`[StateChangeHandler] ${uploadId}: 无法获取合并任务ID，等待状态同步`);
        return;
      }
      
      console.error(`[StateChangeHandler] ${uploadId}: 合并失败`, error);
      // 合并失败，触发 ERROR 状态转换
      const stateMachine = this.core.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        stateMachine.transition('ERROR', { error: errorMessage });
      }
    }
  }

  /**
   * 【状态机】开始实际上传
   * @param {Object} item - 上传队列项
   */
  async startUpload(item) {
    const folderId = item.folderId !== null ? item.folderId : this.core.rootStore.navigationStore?.currentFolderId;
    const { UPLOAD_CONSTANTS } = require('../upload-core-constants');
    
    try {
      if (item.fileSize > UPLOAD_CONSTANTS.NORMAL_UPLOAD_THRESHOLD) {
        // 大文件使用分片上传（分片上传完成后会触发UPLOAD_COMPLETE，然后handleMergingState执行合并）
        await this.core.chunkUploadStore.uploadFileChunked(item.file, folderId, item.id, item.isPublic);
      } else {
        // 小文件使用普通上传
        await this.core.fileUploadStore.uploadFileNormal(item.file, folderId, item.id, item.isPublic);
      }
    } catch (error) {
      // 错误已在具体方法中处理
      throw error; // 【P0修复】抛出错误供上层处理
    }
  }
}

export default StateChangeHandler;

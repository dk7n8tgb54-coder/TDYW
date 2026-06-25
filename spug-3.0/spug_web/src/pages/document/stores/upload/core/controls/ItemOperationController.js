/**
 * ItemOperationController - 单文件操作控制器
 * 负责处理单个上传任务的暂停、恢复、取消、删除等操作
 * 
 * 【P0-Day1修改】支持合并失败后直接重试
 * - 添加防重复点击保护
 * - 先检测分片，存在则直接触发合并
 * - 先调接口再改状态，防止界面卡死
 */
import { action } from 'mobx';
import { message } from 'antd';
import http from 'libs/http';
import { API_ENDPOINTS } from '../upload-core-constants';

export class ItemOperationController {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 暂停单个任务
   * @param {string} itemId - 任务ID
   */
  @action
  async pauseItem(itemId) {
    const stateMachine = this.core.stateMachineManager?.get(itemId);
    
    if (!stateMachine) return;

    // 提前检查是否允许转换，避免无效转换错误
    if (!stateMachine.canTransition('PAUSE')) {
      const currentState = stateMachine.getState();
      if (currentState === 'completed' || currentState === 'error') {
        message.warning(`当前任务已${currentState === 'completed' ? '完成' : '失败'}，无法暂停`);
      }
      return;
    }
    
    // 使用状态机进行转换
    stateMachine.transition('PAUSE');
  }

  /**
   * 恢复单个任务
   * @param {string} itemId - 任务ID
   * 
   * 【P0-Day1修改】合并失败后的智能重试
   * 1. 防重复点击保护
   * 2. 检测分片是否存在，存在则直接合并
   * 3. 先调接口再改状态，防止界面卡死
   */
  @action
  async resumeItem(itemId) {
    // 【Loop-200修复】终态状态机可能已被释放，重试时通过 ensureStateMachine 懒创建
    const item = this.core.queueStore.findUploadItemInCurrentTenant(itemId);
    if (!item) {
      console.warn(`[ItemOperationController] 未找到上传项: ${itemId}`);
      return;
    }

    let stateMachine = this.core.stateMachineManager?.get(itemId);
    if (!stateMachine) {
      // 状态机已被终态释放，重新懒创建（重建后状态为 waiting）
      stateMachine = this.core.uploadCoordinator?.ensureStateMachine?.(item) || null;
      if (!stateMachine) {
        console.warn(`[ItemOperationController] 状态机重建失败，无法重试: ${itemId}`);
        return;
      }
    }

    const currentState = stateMachine.getState();
    const eventName = currentState === 'waiting' ? 'START' : 'RESUME';

    if (!stateMachine.canTransition(eventName)) {
      message.warning(`当前状态(${currentState})不支持${eventName === 'START' ? '开始' : '恢复'}`);
      return;
    }

    // 【P0-Day1新增】防重复点击保护
    if (item.isRetrying) {
      console.log('[ItemOperationController] 重试进行中，忽略重复点击');
      return;
    }
    item.isRetrying = true;

    try {
      // 【P0-Day1新增】如果是合并失败，先检查分片
      if (this._isMergeFailed(item)) {
        console.log('[ItemOperationController] 检测到合并失败，先检查分片...');
        
        const checkResult = await this._checkChunks(item);
        
        if (checkResult.canMergeDirectly) {
          console.log('[ItemOperationController] 分片都存在，直接触发合并');
          
          // 【P0-Day1关键修复】先调用接口，成功后再更新状态
          const mergeSuccess = await this._directMerge(item);
          if (mergeSuccess) {
            return; // 直接合并成功，结束
          }
          // 直接合并失败，继续执行RESUME降级流程
          console.log('[ItemOperationController] 直接合并失败，降级为正常重试');
        } else {
          console.log(`[ItemOperationController] 分片不完整(${checkResult.uploadedCount}/${item.chunkCount})，需要重新上传`);
          
          // 【P1修复】不再用 Math.max(uploaded_chunks) + 1 推断起点——
          // 旧逻辑会跳过中间缺口（[0,2,3] 会被推断为"从4开始"，中间1永远不会上传）。
          // 主路径 ChunkUploadStore.uploadFileChunked() 会自己调 checkUploadedChunks
          // 并基于 uploaded_chunks 集合做"遍历所有分片 + 跳过已上传"的补缺模型。
          // 这里只更新显示进度，不维护 currentChunk 起点。
          if (checkResult.uploadedChunks && checkResult.uploadedChunks.length > 0) {
            item.progress = Math.floor(
              (checkResult.uploadedCount / item.chunkCount) * 100
            );
          } else {
            // 空数组保护
            item.progress = 0;
          }
        }
      }
      
      // 从后端同步 file_hash，确保状态机判断正确
      if (item?.transferId && !item.fileHash) {
        try {
          const transfers = await this.core.transferStore.fetchTransfers(
            this.core.rootStore.navigationStore?.isPublic
          );
          const currentTransfer = transfers.find(t => t.id === item.transferId);
          if (currentTransfer?.file_hash) {
            item.fileHash = currentTransfer.file_hash;
          }
        } catch (error) {
          // 同步失败，静默处理
        }
      }
      
      // 使用状态机进行转换
      const success = stateMachine.transition(eventName);
      
      if (!success) {
        message.warning(`当前状态(${currentState})不支持${eventName === 'START' ? '开始' : '恢复'}`);
      }
    } finally {
      // 【P0-Day1新增】重置重试标记
      item.isRetrying = false;
    }
  }

  /**
   * 【P0-Day1新增】判断是否合并失败（使用错误码替代字符串匹配）
   * @private
   */
  _isMergeFailed(item) {
    // 【修改】通过错误码判断（后端返回的标准错误码）
    if (item.errorCode === 'MERGE_FAILED' || item.errorCode === 'DISK_ERROR' || item.errorCode === 'TIMEOUT') {
      return true;
    }
    
    // 【保留】兼容旧版本：通过状态判断
    if (item.status === 'merging' && item.error) {
      return true;
    }
    
    // 【降级】通过错误信息判断（多语言环境下可能失效）
    if (item.error && (
      item.error.includes('合并') || 
      item.error.includes('merge') ||
      item.error.includes('文件写入')
    )) {
      console.warn('[ItemOperationController] 使用字符串匹配判断合并失败，建议后端返回错误码');
      return true;
    }
    
    return false;
  }

  /**
   * 【P0-Day1新增】检测分片是否存在
   * @private
   */
  async _checkChunks(item) {
    try {
      const response = await http.post(
        API_ENDPOINTS.CHECK_UPLOADED_CHUNKS,
        {
          file_hash: item.fileHash,
          total_chunks: item.chunkCount,
          transfer_id: item.transferId,
          is_public: item.isPublic !== undefined
            ? item.isPublic
            : this.core.rootStore.navigationStore?.isPublic
        }
      );
      
      return {
        allChunksReady: response.all_chunks_ready,
        canMergeDirectly: response.can_merge_directly,
        uploadedCount: response.uploaded_count || response.count || 0,
        missingChunks: response.missing_chunks || [],
        uploadedChunks: response.uploaded_chunks || []
      };
    } catch (error) {
      console.error('[ItemOperationController] 检测分片失败:', error);
      // 检测失败时，安全起见返回需要重新上传
      return {
        allChunksReady: false,
        canMergeDirectly: false,
        uploadedCount: 0,
        missingChunks: [],
        uploadedChunks: []
      };
    }
  }

  /**
   * 【P0-Day1新增】直接触发合并
   * @private
   * @returns {Promise<boolean>} 是否成功
   */
  async _directMerge(item) {
    try {
      const response = await http.post(
        API_ENDPOINTS.DIRECT_MERGE,
        {
          transfer_id: item.transferId,
          folder_id: item.folderId,
          file_name: item.fileName,
          file_hash: item.fileHash,
          total_chunks: item.chunkCount,
          is_public: item.isPublic !== undefined
            ? item.isPublic
            : this.core.rootStore.navigationStore?.isPublic
        }
      );
      
      console.log('[ItemOperationController] 直接合并任务已提交:', response);

      // 【P0-Day1关键修复】接口调用成功后，再更新UI状态
      if (response.is_idempotent) {
        // 幂等响应：任务已在进行中
        console.log('[ItemOperationController] 任务已在进行中，继续轮询');
      }

      // 更新UI状态
      // 【TODO 7.1 状态机唯一入口例外点】此处直接写 item.status='merging' 绕过状态机。
      // 原因：_directMerge 是合并失败后的"智能重试"快捷路径，此时状态机处于 error 终态，
      // 需先重建/转换状态机到 merging 才能合法写入。当前实现为快速恢复，直接写状态 + 轮询。
      // 风险：若轮询期间状态机仍为 error，countByStates 统计会偏差；assertStatusConsistency 会报警。
      // 后续优化：应通过 ensureStateMachine 重建后 transition('RESUME') → START → ... → UPLOAD_COMPLETE →
      // 进入 merging，由 onMergingEntry 统一写 status。详见《资料库并发上传与状态机修复方案.md》7.1 节。
      item.state = 'merging';
      item.status = 'merging';
      item.progress = 99;
      item.error = null;
      item.errorCode = null;
      item.taskId = response.task_id;
      
      // 开始轮询合并状态
      if (this.core.chunkUploadStore?.startMergePolling) {
        this.core.chunkUploadStore.startMergePolling(item);
      }
      
      return true; // 成功
      
    } catch (error) {
      console.error('[ItemOperationController] 直接合并失败:', error);
      message.error('直接合并失败，将尝试重新上传');
      
      // 直接合并失败，降级为正常重试流程
      item.error = null;
      item.errorCode = null;
      
      return false; // 失败，让调用方继续执行RESUME
    }
  }

  /**
   * 取消单个任务
   * @param {string} itemId - 任务ID
   */
  @action
  async cancelItem(itemId) {
    const { item, tenantId } = this.core.queueStore.findUploadItem(itemId);
    if (!item || !tenantId) return;

    // 【7.3 异步操作加版本号】取消时递增版本号，使所有旧异步回调失效
    // cancelItem 绕过状态机直接出队，需显式递增版本
    this.core.queueStore.bumpOperationVersion(itemId);

    // 【关键修复】立即从UI队列中移除，避免显示中间状态（如暂停/失败）
    this.core.queueStore.removeFromQueue(itemId, tenantId);

    // 【Loop-200修复】释放状态机（cancelItem 绕过状态机直接出队，需显式释放避免泄漏）
    if (this.core.stateMachineManager) {
      this.core.stateMachineManager.remove(itemId);
    }

    // 清理唯一标识
    if (item.uniqueKey && item.file) {
      const { file, folderId } = item;
      const isPublic = item.isPublic !== undefined ? item.isPublic : this.core.rootStore.navigationStore?.isPublic;
      this.core.queueStore.removeUniqueKey(file, folderId, isPublic);
    }

    // 尝试从等待队列补充新任务
    if (this.core.displayCoordinator) {
      this.core.displayCoordinator.replenish();
    }

    // 异步执行清理（不阻塞UI，即使用户看不到）
    this.cleanupAfterCancel(item);
  }

  /**
   * 取消后的清理工作
   * @param {Object} item - 上传任务项
   */
  async cleanupAfterCancel(item) {
    // 中止上传请求
    if (item.abortController) {
      try {
        item.abortController.abort('用户取消');
      } catch (e) {
        // 忽略错误
      }
    }
    if (item.canAbort && item.abortToken) {
      try {
        item.abortToken.cancel('用户取消');
      } catch (e) {
        // 忽略错误
      }
    }

    // 取消后端传输记录
    if (item.transferId) {
      try {
        await this.core.transferStore.cancelTransfer(item.transferId);
      } catch (error) {
        // 即使后端取消失败也忽略
      }
    }
  }

  /**
   * 删除单个任务
   * @param {string} itemId - 任务ID
   */
  @action
  async removeItem(itemId) {
    const { item, tenantId } = this.core.queueStore.findUploadItem(itemId);
    if (!item || !tenantId) return;

    const queue = this.core.uploadQueue[tenantId];
    const index = queue.findIndex(i => i.id === itemId);
    if (index === -1) return;

    // 如果正在上传，先中止
    if (item.status === 'uploading' && item.canAbort && item.abortToken) {
      item.abortToken.cancel('用户删除');
    }

    if (item.uniqueKey && item.file) {
      const { file, folderId } = item;
      const isPublic = item.isPublic !== undefined ? item.isPublic : this.core.rootStore.navigationStore?.isPublic;
      this.core.queueStore.removeUniqueKey(file, folderId, isPublic);
    }

    // 【修复】尝试删除后端传输记录，但即使失败也清理前端（记录可能已被批量删除）
    if (item.transferId) {
      try {
        await this.core.transferStore.deleteTransfer(item.transferId);
      } catch (error) {
        // 记录可能已被批量删除任务删除，忽略错误继续清理前端
        console.log('[ItemOperationController] 后端记录删除失败（可能已不存在）:', item.transferId);
      }
    }

    // 无论后端删除是否成功，都清理前端状态
    const shouldRefresh = item.status === 'completed';
    this.core.queueStore.removeFromQueue(itemId, tenantId);

    // 【Loop-200修复】释放状态机（删除任务后状态机不再需要，避免泄漏）
    if (this.core.stateMachineManager) {
      this.core.stateMachineManager.remove(itemId);
    }
    
    if (shouldRefresh) {
      this.core.queueStore.triggerRefresh();
    }
    
    // 删除任务后，尝试从等待队列补充新任务
    if (this.core.displayCoordinator) {
      this.core.displayCoordinator.replenish();
    }
  }

  /**
   * 中止上传（设置错误状态）
   * @param {string} uploadId - 上传ID
   */
  @action
  abortUpload(uploadId) {
    const { item } = this.core.queueStore.findUploadItem(uploadId);
    if (item) {
      // 【7.1 状态机唯一入口】优先通过状态机 ERROR 事件迁移，由 onErrorEntry 写 status:'error'
      const stateMachine = this.core.stateMachineManager?.get(uploadId);
      if (stateMachine && stateMachine.canTransition('ERROR')) {
        stateMachine.transition('ERROR', { error: '已中止' });
        return;
      }
      // 【例外点降级】状态机不存在或不可转换（如已终态被释放），直接写并记录
      // TODO 7.1: 此降级分支保留，因终态状态机可能已被清理，无法再 transition
      console.warn(`[ItemOperationController] ${uploadId}: abortUpload 降级直接写（状态机不可用）`);
      this.core.queueStore.updateUploadItem(uploadId, {
        status: 'error',
        error: '已中止',
      });
    }
  }
}

export default ItemOperationController;

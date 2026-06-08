/**
 * TransferStore - 传输记录管理
 * 职责：管理传输记录的CRUD和批量操作
 */
import { API_ENDPOINTS } from './upload-core-constants';
import { message } from 'antd';

export class TransferStore {
  constructor(rootStore) {
    this.rootStore = rootStore;
  }

  /**
   * 获取传输列表
   */
  async fetchTransfers(isPublic = false) {
    try {
      const { http } = await import('libs');
      const data = await http.get(API_ENDPOINTS.TRANSFER_LIST, {
        params: { is_public: isPublic }
      });
      if (data && Array.isArray(data)) {
        return data;
      }
      return [];
    } catch (error) {
      return [];
    }
  }

  /**
   * 创建传输记录
   */
  async createTransfer(transferData) {
    try {
      const { http } = await import('libs');
      const result = await http.post(API_ENDPOINTS.TRANSFER_CREATE, transferData);
      if (result && result.id) {
        return result.id;
      }
      return null;
    } catch (error) {
      return null;
    }
  }

  /**
   * 更新传输记录的 file_hash
   * @param {number} transferId - 传输记录ID
   * @param {string} fileHash - 文件MD5哈希
   */
  async updateTransferFileHash(transferId, fileHash) {
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_UPDATE_HASH(transferId), {
        file_hash: fileHash,
      });
      return true;
    } catch (error) {
      return false;
    }
  }

  /**
   * 更新传输进度
   * @param {Object} [options]
   * @param {boolean} [options.throwOnError=false] - 失败时是否抛错（默认 false 保持向后兼容）
   */
  async updateTransferProgress(transferId, progress, options = {}) {
    const { throwOnError = false } = options;
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_PROGRESS(transferId), { progress });
    } catch (error) {
      // 【M9 修复】不再静默吞错，至少记录到 console
      console.error('[TransferStore] updateTransferProgress 失败:', { transferId, error });
      if (throwOnError) {
        throw error;
      }
    }
  }

  /**
   * 完成传输
   * @param {Object} [options]
   * @param {boolean} [options.throwOnError=false] - 失败时是否抛错（默认 false 保持向后兼容）
   */
  async completeTransfer(transferId, filePath = null, options = {}) {
    const { throwOnError = false } = options;
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_COMPLETE(transferId), {
        file_path: filePath
      });
    } catch (error) {
      // 【M9 修复】不再静默吞错
      console.error('[TransferStore] completeTransfer 失败:', { transferId, error });
      if (throwOnError) {
        throw error;
      }
    }
  }

  /**
   * 更新传输状态
   */
  async updateTransferStatus(transferId, status) {
    try {
      const { http } = await import('libs');
      const result = await http.post(API_ENDPOINTS.TRANSFER_STATUS(transferId), { status });
      return result;
    } catch (error) {
      // 非法状态转换不再伪装为成功，避免前后端状态漂移被掩盖
      if (error?.message?.includes('无效的状态转换') || error?.message?.includes('状态转换')) {
        return {
          success: false,
          invalidTransition: true,
          transferId,
          status,
          error: error?.message || '无效的状态转换'
        };
      }
      return null;
    }
  }

  /**
   * 取消传输
   */
  async cancelTransfer(transferId) {
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_CANCEL(transferId));
    } catch (error) {
      throw error;
    }
  }

  /**
   * 删除传输记录
   */
  async deleteTransfer(transferId) {
    try {
      const { http } = await import('libs');
      await http.delete(API_ENDPOINTS.TRANSFER_DELETE(transferId));
      return true;
    } catch (error) {
      return false;
    }
  }

  /**
   * 批量删除传输记录
   */
  async batchDeleteTransfers(ids) {
    try {
      const { http } = await import('libs');
      const result = await http.post(API_ENDPOINTS.TRANSFERS_BATCH_DELETE, { transfer_ids: ids });
      console.log('[TransferStore] Batch delete response:', result);
      return true;
    } catch (error) {
      console.error('[TransferStore] Batch delete error:', error);
      throw error; // 抛出错误让上层处理
    }
  }

  /**
   * 批量暂停传输记录（含loading状态）
   * @param {number[]} ids - 传输记录ID列表
   * @returns {Promise<{success: boolean, updated: number, message?: string}>}
   */
  async batchPauseTransfers(ids) {
    if (!ids || ids.length === 0) {
      return { success: true, updated: 0 };
    }

    const hideLoading = message.loading(`正在暂停 ${ids.length} 个传输任务...`, 0);
    try {
      const { http } = await import('libs');
      const result = await http.post(API_ENDPOINTS.TRANSFERS_BATCH_PAUSE, { transfer_ids: ids });
      hideLoading();

      if (result && result.updated > 0) {
        message.success(`已暂停 ${result.updated} 个传输任务`);
        return { success: true, updated: result.updated, ...result };
      } else {
        message.info('没有可暂停的传输任务');
        return { success: true, updated: 0, ...result };
      }
    } catch (error) {
      hideLoading();

      // 【异常处理】区分不同类型的错误
      if (error?.status === 403) {
        message.error('批量暂停失败: 无权限操作');
      } else if (error?.status === 500) {
        message.error('批量暂停失败: 服务器错误，请稍后重试');
      } else {
        message.error(`批量暂停失败: ${error?.message || '未知错误'}`);
      }

      return { success: false, updated: 0, error: error?.message };
    }
  }

  /**
   * 批量恢复传输记录（含loading状态）
   * @param {number[]} ids - 传输记录ID列表
   * @returns {Promise<{success: boolean, updated: number, message?: string}>}
   */
  async batchResumeTransfers(ids) {
    if (!ids || ids.length === 0) {
      return { success: true, updated: 0 };
    }

    const hideLoading = message.loading(`正在恢复 ${ids.length} 个传输任务...`, 0);
    try {
      const { http } = await import('libs');
      const result = await http.post(API_ENDPOINTS.TRANSFERS_BATCH_RESUME, { transfer_ids: ids });
      hideLoading();

      if (result && result.updated > 0) {
        message.success(`已恢复 ${result.updated} 个传输任务`);
        return { success: true, updated: result.updated, ...result };
      } else {
        message.info('没有可恢复的传输任务');
        return { success: true, updated: 0, ...result };
      }
    } catch (error) {
      hideLoading();

      // 【异常处理】区分不同类型的错误
      if (error?.status === 403) {
        message.error('批量恢复失败: 无权限操作');
      } else if (error?.status === 500) {
        message.error('批量恢复失败: 服务器错误，请稍后重试');
      } else {
        message.error(`批量恢复失败: ${error?.message || '未知错误'}`);
      }

      return { success: false, updated: 0, error: error?.message };
    }
  }

  /**
   * 批量取消传输记录（含loading状态）
   * @param {number[]} ids - 传输记录ID列表
   * @returns {Promise<{success: boolean, task_id?: string, message?: string}>}
   */
  async batchCancelTransfers(ids) {
    if (!ids || ids.length === 0) {
      return { success: true };
    }

    const hideLoading = message.loading(`正在取消 ${ids.length} 个传输任务...`, 0);
    try {
      const { http } = await import('libs');
      const result = await http.post(API_ENDPOINTS.TRANSFERS_BATCH_CANCEL, { transfer_ids: ids });
      hideLoading();

      if (result && result.task_id) {
        message.success(`已提交批量取消任务 (任务ID: ${result.task_id})`);
        return { success: true, ...result };
      } else {
        message.info('批量取消任务已提交');
        return { success: true, ...result };
      }
    } catch (error) {
      hideLoading();

      // 【异常处理】区分不同类型的错误
      if (error?.status === 403) {
        message.error('批量取消失败: 无权限操作');
      } else if (error?.status === 500) {
        message.error('批量取消失败: 服务器错误，请稍后重试');
      } else {
        message.error(`批量取消失败: ${error?.message || '未知错误'}`);
      }

      return { success: false, error: error?.message };
    }
  }

  /**
   * 标记传输为失败
   * @param {Object} [options]
   * @param {boolean} [options.throwOnError=false] - 失败时是否抛错（默认 false 保持向后兼容）
   */
  async markTransferAsFailed(transferId, errorMessage, options = {}) {
    const { throwOnError = false } = options;
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_FAIL(transferId), {
        error_message: errorMessage
      });
    } catch (error) {
      // 【M9 修复】不再静默吞错
      console.error('[TransferStore] markTransferAsFailed 失败:', { transferId, errorMessage, error });
      if (throwOnError) {
        throw error;
      }
    }
  }

  /**
   * 清理已完成的传输记录
   */
  async clearCompletedTransfers() {
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFERS_BATCH_CANCEL);
      return true;
    } catch (error) {
      return false;
    }
  }

  /**
   * 检查已上传分片（断点续传）- 含边界处理和格式校验
   * @param {string} fileHash - 文件MD5哈希
   * @param {number} fileSize - 文件大小
   * @param {number} totalChunks - 总分片数
   * @param {boolean} isPublic - 是否公共空间
   * @returns {Promise<{exists: boolean, uploaded_chunks: number[], count: number}>}
   */
  async checkUploadedChunks(fileHash, fileSize, totalChunks, isPublic = false) {
    try {
      const { http } = await import('libs');
      const result = await http.post(API_ENDPOINTS.CHECK_UPLOADED_CHUNKS, {
        file_hash: fileHash,
        file_size: fileSize,
        total_chunks: totalChunks,
        is_public: isPublic
      });
      
      // 【边界处理】校验后端返回格式，避免异常导致前端崩溃
      if (!result || typeof result !== 'object') {
        return { exists: false, uploaded_chunks: [], count: 0 };
      }

      // 【边界处理】确保 uploaded_chunks 是数组
      if (!Array.isArray(result.uploaded_chunks)) {
        return { exists: false, uploaded_chunks: [], count: 0 };
      }

      // 【边界处理】过滤无效分片索引（超出范围或负数）
      const validChunks = result.uploaded_chunks.filter(idx =>
        Number.isInteger(idx) && idx >= 0 && idx < totalChunks
      );
      
      return {
        exists: result.exists === true,
        uploaded_chunks: validChunks,
        count: validChunks.length,
        merge_status: result.merge_status,
        merge_task_id: result.merge_task_id
      };
      
    } catch (error) {
      // 【降级处理】失败时返回空列表，从头开始上传
      return { exists: false, uploaded_chunks: [], count: 0 };
    }
  }

  /**
   * 更新传输记录的 file_hash（断点续传使用）
   * @param {number} transferId - 传输记录ID
   * @param {string} fileHash - 文件MD5哈希
   * @param {number} totalChunks - 总分片数
   */
  async updateTransferHash(transferId, fileHash, totalChunks = null) {
    try {
      const { http } = await import('libs');
      const payload = { file_hash: fileHash };
      if (totalChunks !== null) {
        payload.total_chunks = totalChunks;
      }
      await http.post(API_ENDPOINTS.TRANSFER_UPDATE_HASH(transferId), payload);
      return true;
    } catch (error) {
      return false;
    }
  }

  /**
   * 【M9 修复】带重试的同步传输记录（指数退避）
   * 用法：调用方把原本直接调 completeTransfer / markTransferAsFailed / updateTransferProgress
   *       换成这个方法，传入具体操作 + 参数
   * @param {Function} op - 实际操作函数，签名 `async () => Promise<void>`
   * @param {Object} [options]
   * @param {number} [options.maxRetries=3] - 最大重试次数
   * @param {number} [options.baseDelay=1000] - 基础延迟（ms），实际延迟 = baseDelay * 2^(attempt-1)
   * @param {string} [options.opName='sync'] - 操作名（用于日志）
   * @returns {Promise<{success: boolean, attempts: number, error?: Error}>}
   */
  async _syncTransferWithRetry(op, options = {}) {
    const { maxRetries = 3, baseDelay = 1000, opName = 'sync' } = options;
    let lastError = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        await op();
        if (attempt > 1) {
          console.log(`[TransferStore] ${opName} 第 ${attempt} 次重试成功`);
        }
        return { success: true, attempts: attempt };
      } catch (error) {
        lastError = error;
        // 4xx 客户端错误不重试（重试无意义）
        const status = error?.response?.status || error?.status;
        if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
          console.warn(`[TransferStore] ${opName} 客户端错误 ${status}，不重试:`, error);
          return { success: false, attempts: attempt, error };
        }
        if (attempt < maxRetries) {
          const delay = baseDelay * Math.pow(2, attempt - 1);  // 1s, 2s, 4s
          console.warn(`[TransferStore] ${opName} 第 ${attempt} 次失败，${delay}ms 后重试:`, error);
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }
    }
    console.error(`[TransferStore] ${opName} 重试 ${maxRetries} 次后仍失败:`, lastError);
    return { success: false, attempts: maxRetries, error: lastError };
  }
}

export default TransferStore;

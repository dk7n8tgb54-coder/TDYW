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
   */
  async updateTransferProgress(transferId, progress) {
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_PROGRESS(transferId), { progress });
    } catch (error) {
      // 静默处理
    }
  }

  /**
   * 完成传输
   */
  async completeTransfer(transferId, filePath = null) {
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_COMPLETE(transferId), {
        file_path: filePath
      });
    } catch (error) {
      // 静默处理
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
   */
  async markTransferAsFailed(transferId, errorMessage) {
    try {
      const { http } = await import('libs');
      await http.post(API_ENDPOINTS.TRANSFER_FAIL(transferId), {
        error_message: errorMessage
      });
    } catch (error) {
      // 静默处理
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
}

export default TransferStore;

/**
 * FileUploadStore - 普通文件上传
 * 职责：处理单文件上传（≤32MB）
 */
import { observable, action } from 'mobx';
import { message } from 'antd';
import { UPLOAD_CONSTANTS, API_ENDPOINTS, generateUploadId } from './upload-core-constants';
import * as UploadUtils from '../../../utils/upload-utils';

/**
 * 构建文件夹上传的文件名
 * @param {string} folderPath - 文件夹路径
 * @param {string} fileName - 文件名
 * @returns {string} 完整的文件路径
 */
function buildFolderFileName(folderPath, fileName) {
  if (!folderPath || folderPath === '/' || folderPath === '.') {
    return fileName;
  }
  return `${folderPath}/${fileName}`;
}

export class FileUploadStore {
  @observable uploadProgress = new Map();  // 上传进度 Map<uploadId, percent>
  @observable uploadSpeed = new Map();     // 上传速度 Map<uploadId, speed>

  constructor(queueStore, rootStore) {
    this.queueStore = queueStore;
    this.rootStore = rootStore;
  }

  /**
   * 普通文件上传（≤32MB）
   * @param {File} file - 文件对象
   * @param {number|null} folderId - 文件夹ID
   * @param {string} uploadId - 上传ID
   * @param {boolean} isPublic - 是否公共空间（传入的值，不使用导航状态）
   */
  @action
  async uploadFileNormal(file, folderId, uploadId, isPublic = null) {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';

    // 【新增】创建传输记录，与普通上传保持一致
    let transferId = null;
    try {
      const targetIsPublic = isPublic !== null ? isPublic : this.rootStore.navigationStore?.isPublic;
      transferId = await this.rootStore.transferStore.createTransfer({
        transfer_type: 'upload',
        file_name: file.name,
        file_size: file.size,
        is_public: targetIsPublic,
        total_chunks: 1, // 普通上传只有1个"分片"
        folder_id: folderId,
      });

      // 更新队列项，关联传输记录
      this.queueStore.updateUploadItem(uploadId, {
        transferId: transferId,
        canAbort: true,
        status: 'uploading',
      });
    } catch (error) {
      // 继续上传，不阻塞流程
      this.queueStore.updateUploadItem(uploadId, {
        canAbort: true,
        status: 'uploading',
      });
    }

    // 创建进度更新器
    const updateProgress = UploadUtils.createProgressUpdater
      ? UploadUtils.createProgressUpdater()
      : (id, queue, percent) => {
          const item = queue.find(i => i.id === id);
          if (item) item.percent = percent;
        };

    try {
      const formData = new FormData();
      formData.append('file', file);

      if (folderId !== null) {
        formData.append('folder_id', parseInt(folderId));
      }

      // 【修复】使用传入的isPublic，如果没有则回退到当前导航状态
      const targetIsPublic = isPublic !== null ? isPublic : this.rootStore.navigationStore?.isPublic;
      formData.append('is_public', targetIsPublic ? 'true' : 'false');

      // 【新增】传递传输记录ID
      if (transferId) {
        formData.append('transfer_id', transferId);
      }

      const tenantIdForRequest = targetIsPublic ? null : sessionStorage.getItem('tenant_id');
      if (tenantIdForRequest != null && tenantIdForRequest !== '') {
        formData.append('tenant_id', tenantIdForRequest);
      }

      const { http } = await import('libs');
      const axios = await import('axios');

      // 创建cancelToken
      const cancelTokenSource = axios.default.CancelToken.source();
      this.queueStore.updateUploadItem(uploadId, {
        abortToken: cancelTokenSource,
      });

      // 【速度计算】用于计算上传速度
      let lastProgressTime = Date.now();
      let lastProgressLoaded = 0;
      
      await http.post(API_ENDPOINTS.FILE_UPLOAD, formData, {
        timeout: UPLOAD_CONSTANTS.UPLOAD_TIMEOUT,
        cancelToken: cancelTokenSource.token,
        onUploadProgress: (e) => {
          if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            const queue = this.queueStore.uploadQueue[tenantId];
            if (queue) updateProgress(uploadId, queue, percent);
            
            // 【速度计算】计算上传速度
            const now = Date.now();
            const timeDiff = now - lastProgressTime;
            if (timeDiff >= 1000) {  // 每秒计算一次速度
              const bytesDiff = e.loaded - lastProgressLoaded;
              const speed = Math.round(bytesDiff / (timeDiff / 1000));  // 字节/秒
              this.uploadSpeed.set(uploadId, speed);
              lastProgressTime = now;
              lastProgressLoaded = e.loaded;
            }
          }
        },
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });

      // 上传成功
      this.queueStore.updateUploadItem(uploadId, {
        status: 'completed',
        canAbort: false,
        abortToken: null,
        abortController: null,
        completedAt: Date.now(),
      });

      // 【新增】完成传输记录
      if (transferId && this.rootStore.transferStore) {
        try {
          await this.rootStore.transferStore.completeTransfer(transferId);
        } catch (error) {
          // 完成传输记录失败，静默处理
        }
      }

      // 【新增】清理文件引用，防止内存泄漏
      setTimeout(() => {
        const completedItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
        if (completedItem) {
          completedItem.file = null;
        }
      }, 100);
      this.queueStore.triggerRefresh();

      return { success: true };

    } catch (error) {
      const axios = await import('axios');
      const isCancel = axios.default.isCancel(error);
      const errorMsg = error?.message || String(error);
      const isPauseMessage = errorMsg.includes('用户暂停') || errorMsg.includes('User paused');

      const item = this.queueStore.findUploadItemInCurrentTenant(uploadId);
      if (item) {
        // 【关键修复】检查是否是暂停，避免误标记为错误
        if (this.queueStore.isPaused(uploadId)) {
          // 已经是暂停状态，不修改状态，直接清理
          this.queueStore.updateUploadItem(uploadId, {
            canAbort: false,
            abortToken: null,
          });
          return;  // 【关键】暂停状态直接返回，不抛出错误
        } else if (isCancel || isPauseMessage) {
          // 【关键修复】如果是暂停导致的取消，标记为暂停而不是错误
          this.queueStore.updateUploadItem(uploadId, {
            status: 'paused',
            error: '已暂停',
            canAbort: false,
            abortToken: null,
          });
          return;  // 【关键】直接返回，不抛出错误
        } else {
          // 真正的错误
          const httpStatus = error?.response?.status;
          const errorCode = (
            httpStatus === 401 || httpStatus === 403 ? 'PERMISSION' :
            httpStatus === 413 ? 'QUOTA' :
            httpStatus >= 400 && httpStatus < 500 ? 'CLIENT' :
            httpStatus >= 500 ? 'SERVER' :
            'UNKNOWN'
          );
          this.queueStore.updateUploadItem(uploadId, {
            status: 'error',
            error: error.message || '上传失败',
            errorCode,
            canAbort: false,
          });
          
          // 标记传输记录为失败
          if (item.transferId && this.rootStore.transferStore) {
            this.rootStore.transferStore.markTransferAsFailed(
              item.transferId, 
              error.message || '上传失败'
            );
          }
          
          // 清理唯一标识
          if (item.uniqueKey && this.queueStore.uploadingUniqueKeys) {
            this.queueStore.uploadingUniqueKeys.delete(item.uniqueKey);
          }
          
          // 只有真正的错误才抛出
          throw error;
        }
      }
      
      // 如果没有找到item，且不是取消/暂停错误，抛出
      if (!isCancel && !isPauseMessage) {
        throw error;
      }
    }
  }

  /**
   * 上传文件到指定文件夹（用于文件夹上传）
   * @param {File} file - 文件对象
   * @param {number|null} targetFolderId - 目标文件夹ID
   * @param {string} folderPath - 文件夹路径
   * @param {boolean} isPublic - 是否公共空间（传入的值，不使用导航状态）
   * @param {string} existingUploadId - 【新增】已有的上传ID（文件夹上传预创建时使用）
   */
  @action
  async uploadFileToFolder(file, targetFolderId, folderPath, isPublic = null, existingUploadId = null) {
    // 【关键修复】如果已有 uploadId（文件夹上传预创建），复用它
    const uploadId = existingUploadId || generateUploadId();
    const fileName = buildFolderFileName(folderPath, file.name);
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    // 【修复】使用传入的isPublic，如果没有则回退到当前导航状态
    const targetIsPublic = isPublic !== null ? isPublic : this.rootStore.navigationStore?.isPublic;

    // 【新增】创建传输记录
    let transferId = null;
    try {
      // 【关键修复】根据文件大小计算正确的分片数
      const totalChunks = file.size > UPLOAD_CONSTANTS.NORMAL_UPLOAD_THRESHOLD
        ? Math.ceil(file.size / UPLOAD_CONSTANTS.CHUNK_SIZE)
        : 1;
      
      transferId = await this.rootStore.transferStore.createTransfer({
        transfer_type: 'upload',
        file_name: file.name,
        file_size: file.size,
        is_public: targetIsPublic,
        total_chunks: totalChunks,
        folder_id: targetFolderId,
      });
    } catch (error) {
      // 创建传输记录失败，继续上传
    }

    // 生成唯一标识
    const uniqueKey = this.queueStore.generateUniqueKey(file, targetFolderId, targetIsPublic);

    // 【关键修复】如果没有预创建的队列项，才添加新队列项
    if (!existingUploadId) {
      // 添加到队列
      this.queueStore.addToQueue({
        id: uploadId,
        file: file,
        name: fileName,
        percent: 0,
        status: 'uploading',
        error: null,
        canAbort: true,
        abortToken: null,
        abortController: null,
        uniqueKey: uniqueKey,
        tenantId: tenantId,
        isPublic: targetIsPublic,  // 【修复】保存空间类型
        isCancelledByUser: false,
        isPausedByUser: false,
        transferId: transferId,  // 【新增】关联传输记录
        totalChunks: 1,  // 【新增】普通上传只有1个分片
      }, tenantId);

      this.queueStore.addUniqueKey(file, targetFolderId, targetIsPublic);
    } else {
      // 【新增】有预创建的队列项，只更新 transferId
      this.queueStore.updateUploadItem(uploadId, {
        transferId: transferId,
      });
    }

    const updateProgress = UploadUtils.createProgressUpdater
      ? UploadUtils.createProgressUpdater()
      : (id, queue, percent) => {
          const item = queue.find(i => i.id === id);
          if (item) item.percent = percent;
        };

    // 【关键修复】大文件使用分片上传
    if (file.size > UPLOAD_CONSTANTS.NORMAL_UPLOAD_THRESHOLD) {
      try {
        // 更新队列项为分片上传状态
        this.queueStore.updateUploadItem(uploadId, {
          totalChunks: Math.ceil(file.size / UPLOAD_CONSTANTS.CHUNK_SIZE),
        });
        // 调用分片上传
        await this.rootStore.chunkUploadStore.uploadFileChunked(
          file, targetFolderId, uploadId, targetIsPublic
        );
        return { success: true };
      } catch (error) {
        // 分片上传失败处理
        const errorMsg = error?.message || String(error);
        const isPauseError = errorMsg.includes('用户暂停') || errorMsg.includes('已暂停');
        
        if (!isPauseError) {
          // 标记传输记录为失败
          if (transferId && this.rootStore.transferStore) {
            try {
              await this.rootStore.transferStore.markTransferAsFailed(
                transferId,
                error.message || '上传失败'
              );
            } catch (e) {
              // 静默处理
            }
          }
          throw error;
        }
        return;
      }
    }

    // 小文件使用普通上传（原有逻辑）
    try {
      const formData = new FormData();
      formData.append('file', file);

      if (targetFolderId !== null && targetFolderId !== undefined) {
        formData.append('folder_id', parseInt(targetFolderId));
      }

      // 【修复】使用targetIsPublic（传入的值或回退值）
      formData.append('is_public', targetIsPublic ? 'true' : 'false');

      // 【新增】传递传输记录ID
      if (transferId) {
        formData.append('transfer_id', transferId);
      }

      const tenantIdForRequest = targetIsPublic ? null : sessionStorage.getItem('tenant_id');
      if (tenantIdForRequest != null && tenantIdForRequest !== '') {
        formData.append('tenant_id', tenantIdForRequest);
      }

      const { http } = await import('libs');
      const axios = await import('axios');

      const cancelTokenSource = axios.default.CancelToken.source();
      this.queueStore.updateUploadItem(uploadId, {
        abortToken: cancelTokenSource,
      });

      await http.post(API_ENDPOINTS.FILE_UPLOAD, formData, {
        timeout: UPLOAD_CONSTANTS.UPLOAD_TIMEOUT,
        cancelToken: cancelTokenSource.token,
        onUploadProgress: (e) => {
          const percent = Math.round((e.loaded / e.total) * 100);
          const queue = this.queueStore.uploadQueue[tenantId];
          if (queue) updateProgress(uploadId, queue, percent);
        },
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });

      // 上传成功
      this.queueStore.updateUploadItem(uploadId, {
        status: 'completed',
        canAbort: false,
        abortToken: null,
        abortController: null,
        completedAt: Date.now(),
      });

      // 【新增】完成传输记录
      if (transferId && this.rootStore.transferStore) {
        try {
          await this.rootStore.transferStore.completeTransfer(transferId);
        } catch (error) {
          // 完成传输记录失败，静默处理
        }
      }

      // 【新增】清理文件引用，防止内存泄漏
      setTimeout(() => {
        const completedItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
        if (completedItem) {
          completedItem.file = null;
        }
      }, 100);
      this.queueStore.triggerRefresh();

      return { success: true };

    } catch (error) {
      const axios = await import('axios');
      const isCancel = axios.default.isCancel(error);
      const errorMsg = error?.message || String(error);
      const isPauseMessage = errorMsg.includes('用户暂停') || errorMsg.includes('User paused');

      const item = this.queueStore.findUploadItemInCurrentTenant(uploadId);
      if (item) {
        if (isCancel || isPauseMessage) {
          // 【修复】检查当前任务是否被用户暂停，而不是全局暂停状态
          const isTaskPaused = this.queueStore.isPaused(uploadId);
          this.queueStore.updateUploadItem(uploadId, {
            status: isTaskPaused ? 'paused' : 'error',
            error: isTaskPaused ? '已暂停' : '已取消',
            canAbort: false,
            abortToken: null,
          });
          
          // 【关键】暂停/取消错误不抛出
          if (isTaskPaused) {
            return;
          }
        } else {
          const httpStatus = error?.response?.status;
          const errorCode = (
            httpStatus === 401 || httpStatus === 403 ? 'PERMISSION' :
            httpStatus === 413 ? 'QUOTA' :
            httpStatus >= 400 && httpStatus < 500 ? 'CLIENT' :
            httpStatus >= 500 ? 'SERVER' :
            'UNKNOWN'
          );
          this.queueStore.updateUploadItem(uploadId, {
            status: 'error',
            error: error.message || '上传失败',
            errorCode,
            canAbort: false,
            abortToken: null,
          });
          
          // 【新增】标记传输记录为失败
          if (item.transferId && this.rootStore.transferStore) {
            try {
              await this.rootStore.transferStore.markTransferAsFailed(
                item.transferId,
                error.message || '上传失败'
              );
            } catch (e) {
              // 标记传输记录失败，静默处理
            }
          }
          
          // 只有真正的错误才抛出
          throw error;
        }
      } else if (!isCancel && !isPauseMessage) {
        // 如果没有找到item，且不是取消/暂停错误，抛出
        throw error;
      }
    }
  }
}

export default FileUploadStore;

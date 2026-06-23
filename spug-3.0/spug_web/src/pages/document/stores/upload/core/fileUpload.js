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

    // 【优化2】复用已有 transferId，避免双重创建
    // 队列项可能在入队时未创建 transfer（优化1），或已有 transferId（恢复上传）
    const existingItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    let transferId = existingItem?.transferId || null;
    const targetIsPublic = isPublic !== null ? isPublic : this.rootStore.navigationStore?.isPublic;

    if (!transferId) {
      // 没有已有 transfer，按需创建
      try {
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
        });
      } catch (error) {
        // 【P2修复】创建传输记录失败必须中止上传，
        // 否则上传成功但无 transferId，丢失暂停/取消/续传/状态持久化能力。
        // 【7.1 状态机唯一入口】不写 status:'error'，抛错让 StateChangeHandler 触发 ERROR
        throw new Error('创建上传任务失败，请稍后重试');
      }
    }

    // 【P2修复-二轮/三轮】创建后/复用前统一确保后端状态推进到 UPLOADING。
    // 必须包在 try 里：ensureTransferUploading 失败会抛错（强语义 ensure），
    // 失败时中止上传，避免后端状态与前端不一致。
    try {
      await this.rootStore.transferStore.ensureTransferUploading(transferId);
    } catch (ensureError) {
      // 【7.1 状态机唯一入口】不写 status:'error'，抛错让 StateChangeHandler 触发 ERROR
      throw new Error('上传任务状态初始化失败，请稍后重试');
    }

    // 【7.1 状态机唯一入口】不再写 status:'uploading'/canAbort，状态机 onUploadingEntry 已设置
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
      // 【7.1 状态机唯一入口】不写 status:'completed'/canAbort，状态机 onCompletedEntry 会写
      // 仅做资源清理与 completedAt 记录（展示字段）
      this.queueStore.updateUploadItem(uploadId, {
        abortToken: null,
        abortController: null,
        completedAt: Date.now(),
      });

      // 【新增】完成传输记录
      if (transferId && this.rootStore.transferStore) {
        try {
          await this.rootStore.transferStore.completeTransfer(transferId);
        } catch (error) {
          // 【M9 修复】不再完全静默，至少记录
          console.warn('[FileUpload] completeTransfer 失败:', { transferId, error });
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

      // 【关键修复】触发状态机转换：uploading → completed（小文件直通完成，无需合并）
      // 之前缺失此转换，导致状态机永远卡在 uploading，countByStates 不释放，后续任务无法启动
      const stateMachine = this.rootStore.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        const transitionResult = stateMachine.transition('UPLOAD_COMPLETE');
        console.log(`[FileUpload] ${uploadId}: 小文件上传完成，触发 UPLOAD_COMPLETE, result=${transitionResult}, newState=${stateMachine.getState()}`);
      } else {
        console.warn(`[FileUpload] ${uploadId}: 上传完成但未找到状态机!`);
      }

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
          // 已经是暂停状态，不修改生命周期状态，直接清理资源
          // 【7.1 状态机唯一入口】不写 canAbort（状态机 onPausedEntry 已写）
          this.queueStore.updateUploadItem(uploadId, {
            abortToken: null,
          });
          return;  // 【关键】暂停状态直接返回，不抛出错误
        } else if (isCancel || isPauseMessage) {
          // 【关键修复】如果是暂停导致的取消，不写生命周期状态（状态机已通过 PAUSE 进入 paused）
          // 仅清理资源
          this.queueStore.updateUploadItem(uploadId, {
            abortToken: null,
          });
          return;  // 【关键】直接返回，不抛出错误
        } else {
          // 真正的错误
          // 【7.1 状态机唯一入口】不写 status:'error'/canAbort，抛错让 StateChangeHandler 触发 ERROR
          // 仅做后端记录同步与资源清理
          this.queueStore.updateUploadItem(uploadId, {
            abortToken: null,
            abortController: null,
          });

          // 标记传输记录为失败
          if (item.transferId && this.rootStore.transferStore) {
            // 【M9 修复】加 try-catch 防止 markTransferAsFailed 抛错影响主流程
            try {
              await this.rootStore.transferStore.markTransferAsFailed(
                item.transferId,
                error.message || '上传失败'
              );
            } catch (markErr) {
              console.warn('[FileUpload] markTransferAsFailed 调用本身失败:', markErr);
            }
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
    // 【TODO 7.1 状态机唯一入口例外点】此方法是文件夹上传的旧路径，未经过 StateChangeHandler
    // 调度，直接写 status:'uploading'/'completed'/'error'/'paused' 等生命周期字段。
    // 当前经核查无外部调用方（仅本文件定义），属于遗留死代码路径。
    // 文件夹上传主路径已由 FileUploadCoordinator._processBatch → 状态机 START 事件统一调度。
    // 若未来重新启用此方法，必须改为：入队用 status:'waiting'，成功/失败/暂停通过 transition() 触发。
    // 详见《资料库并发上传与状态机修复方案.md》7.1 节。
    // 【关键修复】如果已有 uploadId（文件夹上传预创建），复用它
    const uploadId = existingUploadId || generateUploadId();
    const fileName = buildFolderFileName(folderPath, file.name);
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    // 【修复】使用传入的isPublic，如果没有则回退到当前导航状态
    const targetIsPublic = isPublic !== null ? isPublic : this.rootStore.navigationStore?.isPublic;

    // 【优化2】复用已有 transferId，避免双重创建
    const existingItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    let transferId = existingItem?.transferId || null;

    if (!transferId) {
      // 没有已有 transfer，按需创建
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
        // 【P2修复】创建传输记录失败必须中止上传，
        // 否则上传成功但无 transferId，丢失暂停/取消/续传/状态持久化能力。
        this.queueStore.updateUploadItem(uploadId, {
          status: 'error',
          error: '创建上传任务失败，请稍后重试',
          errorCode: 'CLIENT',
          canAbort: false,
        });
        throw new Error('创建上传任务失败，请稍后重试');
      }
    }

    // 【P2修复-二轮/三轮】创建后/复用前统一确保后端状态推进到 UPLOADING。
    // 必须包在 try 里：ensureTransferUploading 失败会抛错（强语义 ensure），
    // 失败时把队列项置为 error 并中止上传。
    try {
      await this.rootStore.transferStore.ensureTransferUploading(transferId);
    } catch (ensureError) {
      this.queueStore.updateUploadItem(uploadId, {
        status: 'error',
        error: '上传任务状态初始化失败，请稍后重试',
        errorCode: 'CLIENT',
        canAbort: false,
      });
      throw new Error('上传任务状态初始化失败，请稍后重试');
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
              // 【M9 修复】不再完全静默，至少记录
              console.warn('[FileUpload] markTransferAsFailed 失败:', { transferId, e });
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
          // 【M9 修复】不再完全静默，至少记录
          console.warn('[FileUpload] completeTransfer 失败:', { transferId, error });
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

      // 【关键修复】触发状态机转换：uploading → completed（小文件直通完成，无需合并）
      const stateMachine = this.rootStore.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        const transitionResult = stateMachine.transition('UPLOAD_COMPLETE');
        console.log(`[FileUpload] ${uploadId}: 文件夹小文件上传完成，触发 UPLOAD_COMPLETE, result=${transitionResult}, newState=${stateMachine.getState()}`);
      }

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
              // 【M9 修复】不再完全静默，至少记录
              console.warn('[FileUpload] markTransferAsFailed 失败:', { transferId: item.transferId, e });
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

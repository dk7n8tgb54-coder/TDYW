/**
 * FileUploadStore - 普通文件上传
 * 职责：处理单文件上传（≤32MB）
 */
import { observable, action } from 'mobx';
import { UPLOAD_CONSTANTS, API_ENDPOINTS } from './upload-core-constants';
import * as UploadUtils from '../../../utils/upload-utils';

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
   * @param {number} operationVersion - 【7.3】当前操作版本号，用于丢弃过期回调
   */
  @action
  async uploadFileNormal(file, folderId, uploadId, isPublic = null, operationVersion = 0) {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';

    // 【优化2】复用已有 transferId，避免双重创建
    // 队列项可能在入队时未创建 transfer（优化1），或已有 transferId（恢复上传）
    const existingItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    let transferId = existingItem?.transferId || null;
    // 【拖拽上传 - 5.4】优先使用队列项固化的 isPublic/systemFolderCode，避免离开党建路由后丢失
    const targetIsPublic = isPublic !== null ? isPublic : (existingItem?.isPublic ?? this.rootStore.navigationStore?.isPublic);
    const targetSystemFolderCode = existingItem?.systemFolderCode || null;

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
        }, targetSystemFolderCode);

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

      // 【拖拽上传 - 5.4】显式传 system_folder：
      //   党建任务离开党建路由后 http.js 拦截器不再注入，
      //   必须从队列项读取 systemFolderCode 显式追加，后端才能正确归属党建目录
      if (targetSystemFolderCode) {
        formData.append('system_folder', targetSystemFolderCode);
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
      
      const response = await http.post(API_ENDPOINTS.FILE_UPLOAD, formData, {
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

      // 【7.3】上传请求返回后检查版本，过期则丢弃结果，不写状态不触发转换
      if (!this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
        console.debug(`[FileUpload] ${uploadId}: 过期上传回调已丢弃 v=${operationVersion}`);
        return;
      }

      // 【根因修复】检查 FileUploadView 响应的 error 字段
      // json_response(error=...) 返回 HTTP 200，http.post 不 throw，需手动检查
      if (response && response.error) {
        throw new Error(`文件上传失败: ${response.error}`);
      }

      // 上传成功
      // 【7.1 状态机唯一入口】不写 status:'completed'/canAbort/completedAt
      // 这些核心字段由状态机 onCompletedEntry 在 transition('UPLOAD_COMPLETE') 后统一写入
      // 此处仅做资源清理（abortToken/abortController）
      this.queueStore.updateUploadItem(uploadId, {
        abortToken: null,
        abortController: null,
      });

      // 【统一入口】不再调用 completeTransfer
      // FileUploadService 已通过 TransferCompletionService 设 COMPLETED + file_path
      // StatusSynchronizer 会自动同步前端状态到后端（幂等）

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
        stateMachine.transition('UPLOAD_COMPLETE', { operationVersion });
      } else {
        console.warn(`[FileUpload] ${uploadId}: 上传完成但未找到状态机!`);
      }

      return { success: true };

    } catch (error) {
      const axios = await import('axios');
      const isCancel = axios.default.isCancel(error);
      const errorMsg = error?.message || String(error);
      const isPauseMessage = errorMsg.includes('用户暂停') || errorMsg.includes('User paused');

      // 【7.3】版本过期检查：丢弃旧回调的错误，不触发 ERROR
      if (!this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
        console.debug(`[FileUpload] ${uploadId}: 过期上传错误回调已丢弃 v=${operationVersion}`);
        return;
      }

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

  // 【方向B 2026-06-27】已删除 uploadFileToFolder 方法（遗留死代码，0 调用方）
  // 该方法是文件夹上传的旧路径，绕过状态机直接写 status:'uploading'/'completed'/'error'/'paused'
  // 文件夹上传主路径已由 FileUploadCoordinator._processBatch → 状态机 START 事件统一调度
  // 详见《资料库并发上传与状态机修复方案.md》7.1 节
}

export default FileUploadStore;

/**
 * ChunkUploadCoordinator - 分片上传协调器
 * 负责处理断点续传逻辑
 */
import { action } from 'mobx';
import { UPLOAD_CONSTANTS } from '../upload-core-constants';

export class ChunkUploadCoordinator {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 断点续传专用方法 - 支持从指定分片开始上传
   * @param {File} file - 文件对象
   * @param {number|null} folderId - 文件夹ID
   * @param {Object} item - 上传队列项
   * @param {number} chunkCount - 总分片数
   */
  @action
  async resumeChunkedUpload(file, folderId, item, chunkCount) {
    const uploadId = item.id;
    const startChunkIndex = item.currentChunk || 0;
    
    try {
      // 如果还没计算MD5，需要重新计算
      if (!item.fileHash) {
        this.core.queueStore.updateUploadItem(uploadId, {
          status: 'calculating',
        });
        
        const fileHash = await this.core.md5Store?.calculateFileMD5(file, uploadId);
        item.fileHash = fileHash;
        
        // 保存到后端
        if (item.transferId) {
          await this.core.transferStore.updateTransferHash(item.transferId, fileHash, chunkCount);
        }
      }

      const fileSize = file.size;

      this.core.queueStore.updateUploadItem(uploadId, {
        status: 'uploading',
        canAbort: true,
        chunkCount: chunkCount,
        fileSize: fileSize,
      });

      // 创建AbortController
      const taskAbortController = new AbortController();
      this.core.queueStore.updateUploadItem(uploadId, {
        abortController: taskAbortController,
        isPausedByUser: false,
        isCancelledByUser: false,
      });

      // 跟踪成功上传的分片
      const uploadedChunks = new Set();
      
      // 从断点继续上传，支持单个分片失败重试
      for (let chunkIndex = startChunkIndex; chunkIndex < chunkCount; chunkIndex++) {
        // 重新获取uploadItem
        const currentItem = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
        if (!currentItem) break;

        // 检查暂停/取消状态
        if (this.core.queueStore.isPaused(uploadId)) {
          this.core.queueStore.updateUploadItem(uploadId, {
            status: 'paused',
            error: '已暂停',
            currentChunk: chunkIndex,
            canAbort: false,
          });
          break;
        }

        if (this.core.isCancelled || currentItem.isCancelledByUser) {
          this.core.queueStore.updateUploadItem(uploadId, {
            status: 'error',
            error: '已取消',
            canAbort: false,
          });
          throw new Error('用户取消');
        }

        // 单个分片上传重试机制（最多3次）
        let chunkRetry = 0;
        let chunkError = null;
        
        while (chunkRetry < 3) {
          try {
            await this.core.chunkUploadStore.uploadSingleChunk(
              file, uploadId, chunkIndex, chunkCount, 
              item.fileHash, folderId, taskAbortController, item.isPublic
            );
            chunkError = null;
            break;
          } catch (error) {
            chunkError = error;
            chunkRetry++;
            
            const errorMsg = error?.message || String(error);
            const isAbortError = errorMsg.includes('用户暂停') || errorMsg.includes('用户取消');
            
            // 用户主动操作，不重试
            if (isAbortError) {
              throw error;
            }
            
            if (chunkRetry >= 3) {
              throw new Error(`分片${chunkIndex}上传失败，请重试`);
            }
            // 等待1秒后重试
            await new Promise(resolve => setTimeout(resolve, 1000));
          }
        }
        
        if (chunkError) {
          throw chunkError;
        }
        
        // 记录成功上传的分片
        uploadedChunks.add(chunkIndex);
        
        // 更新已上传分片计数
        item.currentChunk = chunkIndex + 1;
        
        // 每上传10个分片，让出主线程避免卡顿
        if (chunkIndex % 10 === 0) {
          await new Promise(resolve => requestAnimationFrame(resolve));
        }
      }
      
      // 检查是否所有分片都上传成功
      const totalUploaded = startChunkIndex + uploadedChunks.size;
      if (totalUploaded !== chunkCount) {
        throw new Error(`上传未完成，成功 ${totalUploaded}/${chunkCount} 个分片`);
      }

      // 检查是否暂停
      const finalItem = this.core.queueStore.findUploadItemInCurrentTenant(uploadId);
      if (finalItem && finalItem.status !== 'paused') {
        // 合并前更新状态，让用户知道正在合并
        this.core.queueStore.updateUploadItem(uploadId, {
          status: 'merging',
          error: '正在合并分片...',
          percent: 99,
        });
        
        // 合并分片
        await this.core.chunkUploadStore.mergeChunks(
          file, uploadId, chunkCount, item.fileHash, folderId, item.isPublic
        );
      }

    } catch (error) {
      const errorMsg = `（${file.name}）上传失败`;
      const errMessage = error?.message || String(error);
      const isPauseError = errMessage.includes('用户暂停') || 
                           errMessage.includes('用户取消') || 
                           errMessage.includes('上传取消') ||
                           errMessage.includes('已取消');
      
      // 如果是暂停错误，确保状态正确后直接返回
      if (isPauseError) {
        if (item.status !== 'paused') {
          this.core.queueStore.updateUploadItem(uploadId, {
            status: 'paused',
            error: '已暂停',
            canAbort: false,
            abortController: null,
          });
        }
        return;
      }
      
      // 检查是否不是暂停状态，避免竞态条件
      if (!this.core.queueStore.isPaused(uploadId)) {
        // 【修复】使用 updateUploadItem 代替直接修改，确保响应式更新
        this.core.queueStore.updateUploadItem(uploadId, {
          status: 'error',
          error: errMessage || errorMsg,
          canAbort: false,
          abortController: null,
        });

        if (item.transferId && this.core.transferStore) {
          await this.core.transferStore.markTransferAsFailed(item.transferId, errMessage || '上传失败');
        }
        
        throw error;
      }
      
      // 是暂停状态，不抛出错误
      return;
    }
  }
}

export default ChunkUploadCoordinator;

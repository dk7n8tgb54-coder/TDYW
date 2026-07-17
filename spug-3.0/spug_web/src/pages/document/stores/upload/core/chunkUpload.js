/**
 * ChunkUploadStore - 分片上传
 * 职责：处理大文件分片上传（>32MB）
 */
import { observable, action } from 'mobx';
import { message } from 'antd';
import { UPLOAD_CONSTANTS, API_ENDPOINTS } from './upload-core-constants';
import { getSystemFolder, shouldUseSystemFolder } from 'libs/systemFolderContext';

export class ChunkUploadStore {
  @observable chunkProgress = new Map();  // 分片进度

  constructor(queueStore, fileUploadStore, rootStore) {
    this.queueStore = queueStore;
    this.fileUploadStore = fileUploadStore;
    this.rootStore = rootStore;
  }

  /**
   * 分片上传（>32MB）
   * @param {File} file - 文件对象
   * @param {number|null} folderId - 文件夹ID
   * @param {string} uploadId - 上传ID
   * @param {boolean} isPublic - 是否公共空间（传入的值，不使用导航状态）
   * @param {number} operationVersion - 【7.3】当前操作版本号，用于丢弃过期回调
   */
  @action
  async uploadFileChunked(file, folderId, uploadId, isPublic = null, operationVersion = 0) {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    
    // 获取队列项
    let uploadItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (!uploadItem) {
      throw new Error('上传项不存在');
    }
    
    // 【修复】使用传入的isPublic，如果没有则回退到队列项保存的值
    const targetIsPublic = isPublic !== null ? isPublic : uploadItem.isPublic;

    // 【断点续传】检查是否已有fileHash（恢复上传时）
    let fileHash = uploadItem.fileHash;
    
    try {
      if (!fileHash) {
        // 【7.1 状态机唯一入口】不再写 status:'calculating'，状态机 onCalculatingEntry 已设置
        fileHash = await this.rootStore.md5Store?.calculateFileMD5(file, uploadId);

        // 【7.3】MD5 计算完成后检查版本，过期则丢弃结果
        if (!this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
          console.debug(`[ChunkUpload] ${uploadId}: 过期MD5回调已丢弃 v=${operationVersion}`);
          return;
        }

        // 【关键修复】MD5计算完成后检查是否已暂停
        if (this.queueStore.isPaused(uploadId)) {
          // 用户已暂停，仅保存 fileHash（进度字段，允许直接写），状态由状态机 PAUSE 事件管理
          this.queueStore.updateUploadItem(uploadId, { fileHash });
          return;  // 直接返回，不上传，不写生命周期状态
        }

        // 保存fileHash
        this.queueStore.updateUploadItem(uploadId, { fileHash });
      }
    
    const fileSize = file.size;
    const chunkCount = Math.ceil(fileSize / UPLOAD_CONSTANTS.CHUNK_SIZE);

    // 【优化1】如果没有 transferId，按需创建
    if (!uploadItem.transferId) {
      try {
        const newTransferId = await this.rootStore.transferStore.createTransfer({
          transfer_type: 'upload',
          file_name: file.name,
          file_size: file.size,
          is_public: targetIsPublic,
          total_chunks: chunkCount,
          file_hash: '',
          folder_id: folderId,
        });
        this.queueStore.updateUploadItem(uploadId, {
          transferId: newTransferId,
        });
        // 刷新 uploadItem 引用
        uploadItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
      } catch (error) {
        // 【P2修复】大文件分片上传必须 transferId（断点续传/暂停/取消都依赖它），
        // 创建失败直接中止，避免上传成功但无记录可恢复。
        // 【7.1 状态机唯一入口】不写 status:'error'，抛错让 StateChangeHandler 触发 ERROR
        throw new Error('创建上传任务失败，请稍后重试');
      }
    }

    // 【P2修复-二轮/三轮】创建后/复用前统一确保后端状态推进到 UPLOADING。
    // 必须包在 try 里：ensureTransferUploading 失败会抛错（强语义 ensure），
    // 失败时中止上传。
    try {
      await this.rootStore.transferStore.ensureTransferUploading(
        uploadItem.transferId
      );
    } catch (ensureError) {
      // 【7.1 状态机唯一入口】不写 status:'error'，抛错让 StateChangeHandler 触发 ERROR
      throw new Error('上传任务状态初始化失败，请稍后重试');
    }

    // 【修复】更新后端传输记录的 file_hash，支持断点续传
    const item = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (item?.transferId && fileHash) {
      try {
        await this.rootStore.transferStore.updateTransferFileHash(item.transferId, fileHash);
      } catch (error) {
        // 【P2-7修复】记录日志，便于排查问题
        console.warn('[ChunkUpload] 更新传输记录fileHash失败:', error);
      }
    }

    // 【断点续传】查询已上传的分片
    let uploadedChunks = new Set();
    
    if (item?.transferId && fileHash) {
      try {
        const checkResult = await this.rootStore.transferStore.checkUploadedChunks(
          fileHash, fileSize, chunkCount, targetIsPublic, item.transferId
        );
        
        if (checkResult.uploaded_chunks?.length > 0) {
          uploadedChunks = new Set(checkResult.uploaded_chunks);

          // 【优化3】不再使用 Math.max + startChunkIndex 跳过缺口
          // 改为遍历所有分片，跳过已上传分片，确保缺失分片被补齐
          const uploadedCount = checkResult.uploaded_chunks.length;
          const uploadedPercent = Math.min(Math.round((uploadedCount / chunkCount) * 100), 99);

          // 更新进度显示
          this.queueStore.updateUploadItem(uploadId, {
            percent: uploadedPercent,
          });
        }
      } catch (error) {
        // 【P2-7修复】记录日志，便于排查问题
        console.warn('[ChunkUpload] 查询已上传分片失败，降级为从头上传:', error);
      }
    }

    // 开始上传
    // 【7.1 状态机唯一入口】不再写 status:'uploading'/canAbort，状态机 onUploadingEntry 已设置
    this.queueStore.updateUploadItem(uploadId, {
      chunkCount: chunkCount,
      fileSize: fileSize,
    });

    // 创建AbortController
    const taskAbortController = new AbortController();
    this.queueStore.updateUploadItem(uploadId, {
      abortController: taskAbortController,
      // 【7.1】isPausedByUser/isCancelledByUser 由状态机 onUploadingEntry 重置，不再在此写
    });

    // 【修复】跟踪本次会话成功上传的分片
    const sessionUploadedChunks = new Set();
    
    // 【优化3】遍历所有分片，跳过已上传分片，确保缺失分片被补齐
    // 不再使用 startChunkIndex = Math.max(...uploaded_chunks) + 1
    // 因为后端可能返回不连续的分片列表（如 [0, 2, 3]），需要补齐中间缺口
    for (let chunkIndex = 0; chunkIndex < chunkCount; chunkIndex++) {
      // 重新获取uploadItem（可能被外部修改）
      const currentItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
      if (!currentItem) break;

      // 【7.3】每个分片上传前检查版本，过期则停止后续分片
      if (!this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
        console.debug(`[ChunkUpload] ${uploadId}: 过期分片上传已停止 v=${operationVersion} chunk=${chunkIndex}/${chunkCount}`);
        return;
      }

      // 检查暂停/取消状态
      if (this.queueStore.isPaused(uploadId)) {
        // 【7.1 状态机唯一入口】不写 status:'paused'，状态机已在 paused（用户暂停触发 PAUSE 事件）
        // 仅保存进度字段
        this.queueStore.updateUploadItem(uploadId, {
          currentChunk: chunkIndex,
          fileHash: fileHash,  // 【修复】确保fileHash被保存，支持断点续传
        });
        break;
      }

      if (this.rootStore.isCancelled || currentItem.isCancelledByUser) {
        // 【7.1 状态机唯一入口】不写 status:'error'，抛错让上层处理（cancelAll 已统一写状态）
        throw new Error('用户取消');
      }

      // 【断点续传】跳过已上传的分片
      if (uploadedChunks.has(chunkIndex)) {
        continue;
      }

      // 【修复】上传单个分片，失败时抛出错误
      try {
        await this.uploadSingleChunk(
          file, uploadId, chunkIndex, chunkCount, fileHash, folderId, taskAbortController, targetIsPublic, operationVersion
        );
        sessionUploadedChunks.add(chunkIndex);
      } catch (error) {
        const errorMsg = error?.message || String(error);
        
        // 用户主动暂停/取消，直接抛出
        if (errorMsg.includes('用户暂停') || errorMsg.includes('用户取消') || errorMsg.includes('已取消')) {
          throw error;
        }
        
        // 其他错误，记录并抛出，不继续上传
        // 【7.1 状态机唯一入口】不写 status:'error'，抛错让 StateChangeHandler 触发 ERROR
        throw new Error(`分片 ${chunkIndex + 1}/${chunkCount} 上传失败: ${errorMsg}`);
      }
    }
    
    // 检查是否暂停（在检查分片完成数之前）
    if (this.queueStore.isPaused(uploadId)) {
      return;  // 正常返回，不抛出错误
    }

    // 【7.3】版本过期检查：所有分片上传完成后，丢弃旧回调的最终状态迁移
    if (!this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
      console.debug(`[ChunkUpload] ${uploadId}: 过期上传完成回调已丢弃 v=${operationVersion}`);
      return;
    }
    
    // 【关键修复】检查是否所有分片都上传成功（本次上传 + 之前已上传）
    const totalUploadedCount = uploadedChunks.size + sessionUploadedChunks.size;
    if (totalUploadedCount !== chunkCount) {
      throw new Error(`上传未完成，成功 ${totalUploadedCount}/${chunkCount} 个分片`);
    }

    // 【P2修复】确保进度100%且状态正确时才合并
    const finalItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (finalItem && finalItem.status !== 'paused' && finalItem.status !== 'error') {
      // 先更新进度为100%
      this.queueStore.updateUploadItem(uploadId, {
        percent: 100,
      });
      
      // 【关键修复】触发状态转换：uploading -> merging
      // 注意：这里不直接调用mergeChunks，而是通过状态转换来触发
      // 状态转换后，StateChangeHandler会检测到merging状态并调用mergeChunks
      const stateMachine = this.rootStore.stateMachineManager?.get(uploadId);
      if (stateMachine) {
        stateMachine.transition('UPLOAD_COMPLETE', { operationVersion });
      }
    }

  } catch (error) {
      const item = this.queueStore.findUploadItemInCurrentTenant(uploadId);

      // 【关键修复】统一检查所有暂停/取消相关的错误消息
      const errorMsg = error?.message || String(error);
      const isPauseError = errorMsg.includes('用户暂停') ||
                           errorMsg.includes('用户取消') ||
                           errorMsg.includes('上传取消') ||
                           errorMsg.includes('已取消');

      // 【7.1 状态机唯一入口】暂停/取消错误：不写生命周期状态
      // 暂停时状态机已通过 PAUSE 事件进入 paused（onPausedEntry 写 status）；取消由 cancelAll 统一处理。
      // 仅保存 fileHash（进度字段，支持断点续传）后正常返回。
      if (isPauseError) {
        if (item) {
          this.queueStore.updateUploadItem(uploadId, {
            fileHash: item.fileHash || fileHash,  // 【修复】确保fileHash被保存，支持断点续传
          });
        }
        return;  // 【关键】正常返回，不再抛出错误，不写生命周期状态
      }

      // 非暂停错误，且不是暂停状态，才标记后端失败并抛出（由 StateChangeHandler 触发 ERROR）
      if (item && !this.queueStore.isPaused(uploadId)) {
        // 清理唯一标识
        if (item.uniqueKey && !this.rootStore.isCancelled) {
          this.queueStore.removeUniqueKey(file, folderId, this.rootStore.navigationStore?.isPublic);
        }

        // 【7.1 状态机唯一入口】不写 status:'error'/canAbort，抛错让 StateChangeHandler.startUpload catch 触发 ERROR
        // 仅做后端记录同步与资源清理
        const detailedError = error.message || '上传失败';
        this.queueStore.updateUploadItem(uploadId, {
          abortToken: null,
          abortController: null,
        });

        // 标记传输记录为失败
        if (item.transferId && this.rootStore.transferStore) {
          // 【M9 修复】markTransferAsFailed 自身已有 console.error，这里加 try-catch
          // 是为了防止 markTransferAsFailed 内部抛错影响主流程（虽然现在不会了）
          try {
            await this.rootStore.transferStore.markTransferAsFailed(item.transferId, detailedError);
          } catch (e) {
            console.warn('[ChunkUpload] markTransferAsFailed 调用本身失败:', e);
          }
        }

        // 只有非暂停错误才抛出
        throw error;
      }

      // 如果是暂停状态，不抛出错误
      if (this.queueStore.isPaused(uploadId)) {
        return;
      }

      // 其他未知错误抛出
      throw error;
    }
  }

  /**
   * 上传单个分片
   * @param {boolean} targetIsPublic - 是否公共空间（由 uploadFileChunked 传入）
   * @param {number} operationVersion - 【7.3】当前操作版本号，用于进度回调检查
   */
  async uploadSingleChunk(file, uploadId, chunkIndex, chunkCount, fileHash, folderId, abortController, targetIsPublic, operationVersion = 0) {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    const start = chunkIndex * UPLOAD_CONSTANTS.CHUNK_SIZE;
    const end = Math.min(start + UPLOAD_CONSTANTS.CHUNK_SIZE, file.size);
    const chunkBlob = file.slice(start, end);

    const formData = new FormData();
    formData.append('file', chunkBlob);
    formData.append('file_name', file.name);
    formData.append('file_size', file.size);
    formData.append('chunk_index', chunkIndex);
    formData.append('total_chunks', chunkCount);
    formData.append('file_hash', fileHash);

    // 【优化7】携带分片大小，后端可校验分片完整性
    const chunkSize = end - start;
    formData.append('chunk_size', chunkSize);

    if (folderId !== null) {
      formData.append('folder_id', parseInt(folderId));
    }

    // 【修复】使用targetIsPublic（传入的值或队列项保存的值），而不是当前导航状态
    formData.append('is_public', targetIsPublic ? 'true' : 'false');
    
    const tenantIdForRequest = targetIsPublic ? null : sessionStorage.getItem('tenant_id');
    if (tenantIdForRequest !== null) {
      formData.append('tenant_id', tenantIdForRequest);
    }

    // 【路径隔离】传递 transfer_id，使分片写入隔离目录
    const uploadItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    if (uploadItem?.transferId) {
      formData.append('transfer_id', uploadItem.transferId);
    }

    // 【党建文档】注入 system_folder 上下文（XHR 不走 axios 拦截器，需手动注入）
    const activeSystemFolder = getSystemFolder();
    if (activeSystemFolder && shouldUseSystemFolder()) {
      formData.append('system_folder', activeSystemFolder);
    }

    // 再次检查暂停状态
    if (this.queueStore.isPaused(uploadId)) {
      return;
    }

    // 获取Token，添加调试信息
    // 【修复】使用正确的 key 'token'（登录时存储的key）
    const xToken = sessionStorage.getItem('token');
    if (!xToken) {
      throw new Error('登录已过期，请重新登录');
    }

    try {
      const xhr = new XMLHttpRequest();
      let lastUpdateTime = 0;

      await new Promise((resolve, reject) => {
        // 【关键修复】如果signal已被abort，立即拒绝，不上传
        if (abortController.signal.aborted) {
          reject(new Error('用户暂停'));
          return;
        }

        const abortHandler = () => {
          xhr.abort();
          reject(new Error('用户暂停'));
        };

        abortController.signal.addEventListener('abort', abortHandler);

        // 【速度计算】用于计算上传速度
        let lastProgressTime = Date.now();
        let lastProgressLoaded = 0;
        
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            // 【7.3】进度回调检查版本，避免旧进度回退新进度
            if (operationVersion && !this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
              return;
            }
            const now = Date.now();
            const uploadedBytesInChunk = e.loaded;
            const bytesFromPrevChunks = chunkIndex * UPLOAD_CONSTANTS.CHUNK_SIZE;
            const currentChunkSize = end - start;
            const chunkProgress = uploadedBytesInChunk / currentChunkSize;
            const totalUploadedBytes = bytesFromPrevChunks + (chunkProgress * currentChunkSize);
            const newPercent = Math.min(Math.round((totalUploadedBytes / file.size) * 100), 99);

            // 【速度计算】计算上传速度
            const timeDiff = now - lastProgressTime;
            if (timeDiff >= 1000) {  // 每秒计算一次速度
              const bytesDiff = totalUploadedBytes - lastProgressLoaded;
              const speed = Math.round(bytesDiff / (timeDiff / 1000));  // 字节/秒
              this.fileUploadStore.uploadSpeed.set(uploadId, speed);
              lastProgressTime = now;
              lastProgressLoaded = totalUploadedBytes;
            }

            const shouldUpdate =
              now - lastUpdateTime >= UPLOAD_CONSTANTS.PROGRESS_THROTTLE_DELAY ||
              newPercent === 100;

            if (shouldUpdate) {
              lastUpdateTime = now;
              const item = this.queueStore.findUploadItemInCurrentTenant(uploadId);
              if (item) {
                item.percent = newPercent;
              }
              this.queueStore.uploadRefreshTrigger += 1;
            }
          }
        });

        xhr.addEventListener('load', () => {
          abortController.signal.removeEventListener('abort', abortHandler);
          if (xhr.status === 200) {
            resolve();
          } else if (xhr.status === 401) {
            reject(new Error('登录已过期，请重新登录'));
          } else {
            reject(new Error(`HTTP ${xhr.status}: ${xhr.statusText}, 响应: ${xhr.responseText?.substring(0, 100)}`));
          }
        });

        xhr.addEventListener('error', () => {
          abortController.signal.removeEventListener('abort', abortHandler);
          reject(new Error(`网络错误(分片${chunkIndex})`));
        });

        xhr.addEventListener('abort', () => {
          abortController.signal.removeEventListener('abort', abortHandler);
          reject(new Error('上传取消'));
        });

        xhr.addEventListener('timeout', () => {
          abortController.signal.removeEventListener('abort', abortHandler);
          reject(new Error(`上传超时(分片${chunkIndex})`));
        });

        xhr.open('POST', API_ENDPOINTS.CHUNK_UPLOAD);
        xhr.setRequestHeader('X-Token', xToken);
        xhr.withCredentials = true;
        xhr.timeout = UPLOAD_CONSTANTS.UPLOAD_TIMEOUT; // 添加超时设置
        xhr.send(formData);
      });

    } catch (chunkError) {
      const errorMsg = chunkError?.message || String(chunkError);
      const isAbortError = errorMsg.includes('用户暂停') || errorMsg.includes('用户取消');

      if (isAbortError) {
        // 【7.1 状态机唯一入口】不写 status:'paused'，状态机已通过 PAUSE 事件进入 paused
        // 仅保存 fileHash（进度字段，支持断点续传），抛错让上层 catch 统一处理暂停
        const item = this.queueStore.findUploadItemInCurrentTenant(uploadId);
        this.queueStore.updateUploadItem(uploadId, {
          fileHash: item?.fileHash || fileHash,  // 【修复】确保fileHash被保存，支持断点续传
        });
        throw chunkError;
      } else {
        throw chunkError;
      }
    }
  }

  /**
   * 合并分片
   * @param {File} file - 文件对象
   * @param {string} uploadId - 上传ID
   * @param {number} chunkCount - 分片总数
   * @param {string} fileHash - 文件哈希
   * @param {number|null} folderId - 文件夹ID
   * @param {boolean} isPublic - 是否公共空间
   * @param {number} operationVersion - 【7.3】当前操作版本号
   */
  async mergeChunks(file, uploadId, chunkCount, fileHash, folderId, isPublic = null, operationVersion = 0) {
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    
    // 【修复】使用传入的isPublic，如果没有则回退到队列项保存的值
    const uploadItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
    const targetIsPublic = isPublic !== null ? isPublic : uploadItem?.isPublic;

    const { http } = await import('libs');
    
    // 【关键修复】添加try-catch处理"文件正在合并中"错误
    let mergeResult;
    try {
      mergeResult = await http.post(API_ENDPOINTS.MERGE_CHUNKS, {
        file_name: file.name,
        file_size: file.size,
        total_chunks: chunkCount,
        file_hash: fileHash,
        folder_id: folderId !== null ? parseInt(folderId) : null,
        is_public: targetIsPublic,
        tenant_id: targetIsPublic ? null : sessionStorage.getItem('tenant_id'),
        transfer_id: uploadItem?.transferId,
      });
    } catch (error) {
      // 如果后端返回"文件正在合并中"，说明合并已在进行，直接进入轮询
      const errorMessage = error.message || error.response?.data?.error || '';
      if (errorMessage.includes('正在合并')) {
        console.log(`[ChunkUploadStore] ${uploadId}: 文件正在合并中(错误)，开始轮询状态`);
        // 从错误响应或之前的状态中获取task_id
        const existingTaskId = uploadItem?.celeryTaskId || error.response?.data?.task_id;
        if (existingTaskId) {
          await this.pollMergeStatus(null, existingTaskId, uploadId, operationVersion);
          return { success: true, celeryTaskId: existingTaskId };
        }
        // 如果没有task_id，等待一段时间后重试
        console.warn(`[ChunkUploadStore] ${uploadId}: 无法获取合并任务ID，等待后重试`);
        await new Promise(resolve => setTimeout(resolve, 2000));
        // 递归重试
        return this.mergeChunks(file, uploadId, chunkCount, fileHash, folderId, isPublic, operationVersion);
      }
      throw error;
    }

    // 【修复】检查后端返回的状态，如果是merging，直接轮询
    if (mergeResult.status === 'merging') {
      console.log(`[ChunkUploadStore] ${uploadId}: 文件正在合并中(响应)，开始轮询状态`);
      const existingTaskId = mergeResult.task_id || uploadItem?.celeryTaskId;
      if (existingTaskId) {
        await this.pollMergeStatus(null, existingTaskId, uploadId, operationVersion);
        return { success: true, celeryTaskId: existingTaskId };
      }
      // 如果没有task_id，等待后重试
      console.warn(`[ChunkUploadStore] ${uploadId}: 无法获取合并任务ID，等待后重试`);
      await new Promise(resolve => setTimeout(resolve, 2000));
      return this.mergeChunks(file, uploadId, chunkCount, fileHash, folderId, isPublic, operationVersion);
    }

    // 轮询合并状态
    const mergeTaskId = mergeResult.merge_task_id;
    const celeryTaskId = mergeResult.task_id;

    // 【7.1 状态机唯一入口】不写 status:'merging'，状态机 onMergingEntry 已设置
    // 仅保存 celeryTaskId（进度字段，用于轮询）
    this.queueStore.updateUploadItem(uploadId, {
      celeryTaskId: celeryTaskId,
    });

    await this.pollMergeStatus(mergeTaskId, celeryTaskId, uploadId, operationVersion);

    // 【修复】合并成功，由调用方（StateChangeHandler）触发 MERGE_SUCCESS 事件
    // 这里只返回成功，不直接更新生命周期状态
    return {
      success: true,
      mergeTaskId,
      celeryTaskId,
    };
  }

  /**
   * 轮询合并状态
   * 【优化6】渐进式轮询：
   *   0-30秒：每2秒
   *   30秒-5分钟：每5秒
   *   超过5分钟：每15秒（降低服务器压力）
   * 【7.3 异步操作加版本号】
   *   - 每次 await 返回后检查 operationVersion，版本过期则停止轮询
   *   - 检查 celeryTaskId 与当前 item.celeryTaskId 是否一致，不一致则停止
   *
   * @param {string} mergeTaskId - 合并任务ID
   * @param {string} celeryTaskId - Celery任务ID
   * @param {string} uploadId - 【7.3】上传ID，用于版本检查
   * @param {number} operationVersion - 【7.3】当前操作版本号
   */
  async pollMergeStatus(mergeTaskId, celeryTaskId = null, uploadId = null, operationVersion = 0) {
    const { http } = await import('libs');
    let startTime = Date.now();
    let consecutiveErrors = 0;
    const MAX_CONSECUTIVE_ERRORS = 5;

    while (true) {
      // 【7.3】每次轮询前检查版本，过期则停止
      if (uploadId && operationVersion && !this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
        console.debug(`[ChunkUpload] ${uploadId}: 过期轮询已停止 v=${operationVersion}`);
        return;
      }

      // 【7.3】检查 celeryTaskId 是否仍匹配当前 item，不匹配则停止（新轮询已由新 task 启动）
      if (uploadId && celeryTaskId) {
        const currentItem = this.queueStore.findUploadItemInCurrentTenant(uploadId);
        if (currentItem && currentItem.celeryTaskId && currentItem.celeryTaskId !== celeryTaskId) {
          console.debug(`[ChunkUpload] ${uploadId}: task_id 不匹配，停止旧轮询 old=${celeryTaskId} current=${currentItem.celeryTaskId}`);
          return;
        }
      }

      const elapsed = (Date.now() - startTime) / 1000;
      if (elapsed > UPLOAD_CONSTANTS.MERGE_MAX_POLLING_TIME) {
        throw new Error('合并超时');
      }

      try {
        const params = celeryTaskId
          ? { task_id: celeryTaskId }
          : { merge_task_id: mergeTaskId };

        const status = await http.get(API_ENDPOINTS.MERGE_STATUS, { params });

        // 【7.3】请求返回后再次检查版本
        if (uploadId && operationVersion && !this.queueStore.isCurrentOperation(uploadId, operationVersion)) {
          console.debug(`[ChunkUpload] ${uploadId}: 过期轮询响应已丢弃 v=${operationVersion}`);
          return;
        }

        consecutiveErrors = 0;

        if (status.status === 'completed' || status.status === 'success') {
          return;
        } else if (status.status === 'failed') {
          throw new Error(status.error || '合并失败');
        } else if (status.status === 'timeout') {
          throw new Error('合并超时');
        } else if (status.status === 'not_found') {
          throw new Error('合并任务不存在');
        } else if (status.status === 'error') {
          throw new Error(status.error || '合并任务错误');
        } else if (status.status === 'progress' || status.status === 'pending' || status.status === 'merging') {
          // 合并进行中，继续轮询
        } else {
          // 【P1-12修复】处理未知状态，避免无限循环
        }

        // 【优化6】渐进式轮询间隔
        let interval;
        if (elapsed <= 30) {
          interval = 2000;  // 0-30秒：每2秒
        } else if (elapsed <= 300) {
          interval = 5000;  // 30秒-5分钟：每5秒
        } else {
          interval = 15000;  // 超过5分钟：每15秒
        }

        await new Promise(resolve => setTimeout(resolve, interval));
      } catch (error) {
        consecutiveErrors++;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          throw new Error(`合并状态查询连续失败${MAX_CONSECUTIVE_ERRORS}次，请检查网络`);
        }
        
        const backoffTime = Math.min(1000 * Math.pow(2, consecutiveErrors - 1), 16000);
        await new Promise(resolve => setTimeout(resolve, backoffTime));
      }
    }
  }
}

export default ChunkUploadStore;

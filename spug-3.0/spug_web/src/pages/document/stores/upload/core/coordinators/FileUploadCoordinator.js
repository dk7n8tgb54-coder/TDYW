/**
 * FileUploadCoordinator - 文件上传协调器
 * 负责处理文件选择、上传队列处理、文件校验等
 */
import { action } from 'mobx';
import { message } from 'antd';
import { UPLOAD_CONSTANTS, generateUploadId } from '../upload-core-constants';
import { validateFileName } from '../../../../utils/upload-utils';

export class FileUploadCoordinator {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 处理文件选择
   * @param {FileList} files - 选择的文件列表
   */
  @action
  async handleFileSelect(files) {
    const targetFolderId = this.core.getUploadTargetFolderId();

    // 批量提示
    if (files.length > UPLOAD_CONSTANTS.BATCH_WARNING_THRESHOLD) {
      message.info(`正在批量上传 ${files.length} 个文件，请稍候...`);
    }

    // 防重复提交
    const duplicateFiles = [];
    const uniqueFiles = [];
    const isPublic = this.core.rootStore.navigationStore?.isPublic;

    for (const file of files) {
      const uniqueKey = this.core.queueStore.generateUniqueKey(file, targetFolderId, isPublic);
      
      if (this.core.queueStore.uploadingUniqueKeys.has(uniqueKey)) {
        duplicateFiles.push(file.name);
      } else {
        uniqueFiles.push(file);
      }
    }

    if (duplicateFiles.length > 0) {
      const tip = duplicateFiles.length <= 3
        ? duplicateFiles.map(name => `"${name}"`).join('、')
        : `${duplicateFiles.slice(0, 3).map(name => `"${name}"`).join('、')} 等 ${duplicateFiles.length} 个文件`;
      message.warning(`以下文件已在上传队列中，跳过重复提交：${tip}`);
    }

    if (uniqueFiles.length === 0) {
      return;
    }

    if (this.core.rootStore.uploadUIStore && this.core.rootStore.uploadUIStore.showUploadPanel) {
      this.core.rootStore.uploadUIStore.showUploadPanel();
    }
    this.core.isPaused = false;
    this.core.isCancelled = false;
    this.core.pendingFiles = [...uniqueFiles];
    
    await this.processUploadQueue(uniqueFiles, targetFolderId);
    
    this.core.queueStore.triggerRefresh();
  }

  /**
   * 处理上传队列
   * @param {Array} files - 文件列表
   * @param {number} folderId - 目标文件夹ID
   */
  @action
  async processUploadQueue(files, folderId) {
    const tenantId = this.core.getCurrentTenantId();
    const isPublic = this.core.rootStore.navigationStore?.isPublic;

    if (!this.core.uploadQueue[tenantId]) {
      this.core.uploadQueue[tenantId] = [];
    }

    // 文件名校验
    const validFiles = [];
    const invalidFiles = [];
    for (const file of files) {
      const validation = validateFileName(file.name);
      if (validation.valid) {
        validFiles.push(file);
      } else {
        invalidFiles.push({ name: file.name, reason: validation.message });
      }
    }

    if (invalidFiles.length > 0) {
      if (invalidFiles.length === 1) {
        message.error(`文件 "${invalidFiles[0].name}" 无法上传: ${invalidFiles[0].reason}`);
      } else {
        message.error(`${invalidFiles.length} 个文件无法上传，请检查文件名长度和非法字符`);
      }
    }

    if (validFiles.length === 0) {
      return;
    }

    // 【移除】不再分批加载，所有任务直接加入主队列
    // 虚拟列表支持1000+流畅渲染，不再需要显示队列限制
    const allUploadItems = [];

    for (let index = 0; index < validFiles.length; index++) {
      const file = validFiles[index];
      const uniqueKey = this.core.queueStore.generateUniqueKey(file, folderId, isPublic);
      this.core.queueStore.uploadingUniqueKeys.add(uniqueKey);

      const uploadId = generateUploadId();
      const estimatedChunks = Math.ceil(file.size / UPLOAD_CONSTANTS.CHUNK_SIZE) || 1;
      
      const transferId = await this.core.transferStore.createTransfer({
        transfer_type: 'upload',
        file_name: file.name,
        file_size: file.size,
        is_public: isPublic,
        total_chunks: estimatedChunks,
        file_hash: '',
        ...(folderId !== null && { folder_id: folderId })
      });

      const item = {
        id: uploadId,
        name: file.name,
        percent: 0,
        status: 'waiting',
        error: null,
        canAbort: false,
        fileSize: file.size,
        chunks: [],
        currentChunk: 0,
        uniqueKey: uniqueKey,
        tenantId: tenantId,
        transferId: transferId,
        folderId: folderId,
        fileHash: null,
        isPublic: isPublic,
        totalChunks: estimatedChunks,
      };
      Object.defineProperty(item, 'file', {
        value: file,
        writable: true,
        enumerable: false,
        configurable: true
      });

      // 【修改】所有任务直接加入主队列
      this.core.queueStore.addToQueue(item, tenantId);
      allUploadItems.push(item);
      
      if (this.core.stateMachineManager) {
        // 【P0修复】创建状态机时传入item，确保canStart守卫可以正确判断
        this.core.stateMachineManager.create(uploadId, {
          queueStore: this.core.queueStore,
          transferStore: this.core.transferStore,
          md5Store: this.core.md5Store,
          file: file,
          folderId: folderId,
          item: item  // 【新增】传入item确保canStart守卫正常工作
        });
      }
    }

    console.log('[processUploadQueue] 开始启动任务, 总任务数:', allUploadItems.length);
    if (this.core.uploadCoordinator) {
      // 【P0修复】新添加文件时强制重置暂停状态，确保自动开始
      if (this.core.isPaused && allUploadItems.length > 0) {
        console.log('[processUploadQueue] 新添加文件，重置暂停状态');
        this.core.isPaused = false;
      }
      this.core.uploadCoordinator.startWaiting();
    }
  }

  /**
   * 上传单个文件
   * @param {File} file - 文件对象
   * @param {number} folderId - 文件夹ID
   * @param {string} existingUploadId - 已有的上传ID（可选）
   * @param {boolean} isPublic - 是否公共空间
   */
  @action
  async uploadSingleFile(file, folderId = null, existingUploadId = null, isPublic = null) {
    const uploadId = existingUploadId || generateUploadId();
    const targetFolderId = folderId !== null ? folderId : this.core.rootStore.navigationStore?.currentFolderId;
    const targetIsPublic = isPublic !== null ? isPublic : this.core.rootStore.navigationStore?.isPublic;

    if (this.core.isCancelled) {
      return;
    }

    try {
      if (file.size > UPLOAD_CONSTANTS.NORMAL_UPLOAD_THRESHOLD) {
        return await this.core.chunkUploadStore.uploadFileChunked(file, targetFolderId, uploadId, targetIsPublic);
      } else {
        return await this.core.fileUploadStore.uploadFileNormal(file, targetFolderId, uploadId, targetIsPublic);
      }
    } catch (error) {
      if (this.core.isCancelled || error.message?.includes('已取消')) {
        throw error;
      }
      throw error;
    }
  }

  /**
   * 重新选择文件并恢复上传
   * @param {string} itemId - 上传项ID
   * @param {File} newFile - 新选择的文件
   */
  @action
  async replaceFileAndResume(itemId, newFile) {
    const item = this.core.queueStore.findUploadItemInCurrentTenant(itemId);
    if (!item) {
      message.error('上传项不存在');
      return;
    }
    
    // 【修复】使用 updateUploadItem 代替直接修改
    this.core.queueStore.updateUploadItem(itemId, {
      file: newFile,
      status: 'waiting',
      error: null,
    });
    
    message.success('文件已选择，准备继续上传');
    
    setTimeout(async () => {
      if (this.core.itemOperationController) {
        await this.core.itemOperationController.resumeItem(itemId);
      }
    }, 500);
  }
}

export default FileUploadCoordinator;

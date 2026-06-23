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

    // 【2026-06-06】不自动展开传输列表抽屉，与文件夹上传保持一致
    // 新任务进队列时只显示底部小条，用户主动点击/快捷键 (Ctrl+Shift+U) 才展开
    this.core.isPaused = false;
    this.core.isCancelled = false;
    this.core.pendingFiles = [...uniqueFiles];

    await this.processUploadQueue(uniqueFiles, targetFolderId);

    this.core.queueStore.triggerRefresh();
  }

  /**
   * 处理上传队列
   *
   * 【重构 2026-06-06】支持两种调用方式（向后兼容）：
   *   1. 老格式：processUploadQueue(files: File[], folderId: number | null)
   *      - 普通上传：所有文件共享同一个目标文件夹
   *   2. 新格式：processUploadQueue(items: Array<{file, folderId, folderPath?}>, null)
   *      - 文件夹上传：每个文件有自己的目标文件夹
   *
   * @param {Array} filesOrItems - 文件列表 或 items 数组
   * @param {number|null} folderId - 目标文件夹ID（老格式必填，新格式传 null）
   */
  @action
  async processUploadQueue(filesOrItems, folderId) {
    // 【重构】检测输入格式：items 数组 vs 纯文件数组
    const isBatchFormat = Array.isArray(filesOrItems) && filesOrItems.length > 0 && filesOrItems[0] && filesOrItems[0].file;

    if (isBatchFormat) {
      return this._processBatch(filesOrItems);
    }
    return this._processUniform(filesOrItems, folderId);
  }

  /**
   * 【新格式】处理 items 批次（每个文件有自己的 folderId）
   * 用于文件夹上传：每个文件的目标文件夹不同
   * @private
   */
  @action
  async _processBatch(items) {
    const tenantId = this.core.getCurrentTenantId();
    const isPublic = this.core.rootStore.navigationStore?.isPublic;

    if (!this.core.uploadQueue[tenantId]) {
      this.core.uploadQueue[tenantId] = [];
    }

    // 文件名校验
    const validItems = [];
    const invalidItems = [];
    for (const item of items) {
      const validation = validateFileName(item.file.name);
      if (validation.valid) {
        validItems.push(item);
      } else {
        invalidItems.push({ name: item.file.name, reason: validation.message });
      }
    }

    if (invalidItems.length > 0) {
      if (invalidItems.length === 1) {
        message.error(`文件 "${invalidItems[0].name}" 无法上传: ${invalidItems[0].reason}`);
      } else {
        message.error(`${invalidItems.length} 个文件无法上传，请检查文件名长度和非法字符`);
      }
    }

    if (validItems.length === 0) {
      return [];
    }

    const allUploadItems = [];

    for (let index = 0; index < validItems.length; index++) {
      const { file, folderId, folderPath } = validItems[index];
      const uniqueKey = this.core.queueStore.generateUniqueKey(file, folderId, isPublic);
      this.core.queueStore.uploadingUniqueKeys.add(uniqueKey);

      const uploadId = generateUploadId();
      const estimatedChunks = Math.ceil(file.size / UPLOAD_CONSTANTS.CHUNK_SIZE) || 1;

      // 【优化1】入队时不再创建 transfer，延迟到真正获得并发槽上传时再创建
      // 避免批量选择1000个文件时立即产生1000条PENDING记录
      // transferId 将在 uploadFileNormal / uploadFileChunked 中按需创建

      // 【重构】显示名称优先使用 folderPath（文件夹上传场景）
      const displayName = folderPath ? `${folderPath}/${file.name}` : file.name;

      const queueItem = {
        id: uploadId,
        name: displayName,
        percent: 0,
        status: 'waiting',
        error: null,
        canAbort: false,
        fileSize: file.size,
        chunks: [],
        currentChunk: 0,
        uniqueKey: uniqueKey,
        tenantId: tenantId,
        transferId: null,  // 【优化1】延迟创建，初始为null
        folderId: folderId,
        fileHash: null,
        isPublic: isPublic,
        totalChunks: estimatedChunks,
      };
      Object.defineProperty(queueItem, 'file', {
        value: file,
        writable: true,
        enumerable: false,
        configurable: true
      });

      this.core.queueStore.addToQueue(queueItem, tenantId);
      allUploadItems.push(queueItem);

      // 【Loop-200修复】入队阶段不再创建状态机，改由 startWaiting 调度时懒创建
      // 避免一次上传 870 个文件时瞬间创建 870 个状态机占满 MAX_ACTIVE_MACHINES 保护阈值
    }

    if (this.core.uploadCoordinator) {
      if (this.core.isPaused && allUploadItems.length > 0) {
        this.core.isPaused = false;
      }
      this.core.uploadCoordinator.startWaiting();
    }
    return allUploadItems;
  }

  /**
   * 【老格式】处理统一 folderId 的文件列表（普通上传）
   * @private
   */
  @action
  async _processUniform(files, folderId) {
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

      // 【优化1】入队时不再创建 transfer，延迟到真正获得并发槽上传时再创建

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
        transferId: null,  // 【优化1】延迟创建，初始为null
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

      // 【Loop-200修复】入队阶段不再创建状态机，改由 startWaiting 调度时懒创建
      // 避免一次上传 870 个文件时瞬间创建 870 个状态机占满 MAX_ACTIVE_MACHINES 保护阈值
    }

    if (this.core.uploadCoordinator) {
      // 【P0修复】新添加文件时强制重置暂停状态，确保自动开始
      if (this.core.isPaused && allUploadItems.length > 0) {
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
    // 【TODO 7.1 状态机唯一入口例外点】replaceFileAndResume 直接写 status:'waiting' 绕过状态机。
    // 原因：用户重新选择文件后恢复上传，此时任务处于 paused/error 等状态，状态机需根据历史与 fileHash
    // 判断恢复目标（waiting/calculating/uploading）。直接写 'waiting' 是为了强制从头调度，简化逻辑。
    // 风险：与状态机 currentState 不一致，但下方 resumeItem 会触发 transition('RESUME'/'START')，
    // 状态机守卫会校正目标状态，onWaitingEntry 会重新写 status:'waiting'，最终一致。
    // 后续优化：应封装为 replaceFileAndResume 专用事件，由状态机统一处理文件替换 + 状态迁移。
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

/**
 * FileUploadCoordinator - 文件上传协调器
 * 负责处理文件选择、上传队列处理、文件校验等
 */
import { action } from 'mobx';
import { message } from 'antd';
import http from 'libs/http';
import { UPLOAD_CONSTANTS, generateUploadId } from '../upload-core-constants';
import { validateFileName } from '../../../../utils/upload-utils';

function formatFileNames(names) {
  return names.length <= 3
    ? names.map(n => `"${n}"`).join('、')
    : `${names.slice(0, 3).map(n => `"${n}"`).join('、')} 等 ${names.length} 个文件`;
}

export class FileUploadCoordinator {
  constructor(coreStore) {
    this.core = coreStore;
  }

  /**
   * 处理文件选择
   * @param {FileList} files - 选择的文件列表
   * @param {Object|null} [targetContext=null] - 由 uploadCoreStore.captureUploadTargetContext 生成的不可变上下文快照
   *   包含 {folderId, isPublic, tenantId, systemFolderCode}。null 时由调用方负责捕获。
   */
  @action
  async handleFileSelect(files, targetContext = null) {
    const ctx = targetContext || this.core.captureUploadTargetContext();
    const targetFolderId = ctx.folderId;
    const targetIsPublic = ctx.isPublic;

    if (files.length > UPLOAD_CONSTANTS.BATCH_WARNING_THRESHOLD) {
      message.info(`正在批量上传 ${files.length} 个文件，请稍候...`);
    }

    const existingItems = this.core.queueStore?.existingFileItems || [];

    const duplicateFiles = [];     // 已在上传队列中
    const conflictFiles = [];      // 同名 -> 弹窗让用户选（无论大小是否相同）
    const conflictMeta = [];       // 冲突元数据（与 conflictFiles 一一对应）
    const normalFiles = [];        // 无冲突

    for (const file of files) {
      const uniqueKey = this.core.queueStore.generateUniqueKey(file, targetFolderId, targetIsPublic);

      if (this.core.queueStore.uploadingUniqueKeys.has(uniqueKey)) {
        duplicateFiles.push(file.name);
      } else {
        const existingItem = existingItems.find(
          item => item.name === file.name && !item.isFolder
        );
        if (existingItem) {
          // 同名即冲突，无论大小是否相同
          const existingSize = Number(existingItem.file_size || existingItem.size || 0);
          conflictFiles.push(file);
          conflictMeta.push({
            fileName: file.name,
            fileSize: file.size,
            existingId: existingItem.id,
            existingSize: existingSize,
            sameSize: existingSize === file.size,
            action: 'replace',
          });
        } else {
          normalFiles.push(file);
        }
      }
    }

    if (duplicateFiles.length > 0) {
      message.warning(`以下文件已在上传队列中，跳过重复提交：${formatFileNames(duplicateFiles)}`);
    }

    // 正常文件立即上传
    if (normalFiles.length > 0) {
      this.core.isPaused = false;
      this.core.isCancelled = false;
      this.core.pendingFiles = [...normalFiles];
      await this.processUploadQueue(normalFiles, targetFolderId, ctx);
      this.core.queueStore.triggerRefresh();
    }

    // 冲突文件弹窗
    if (conflictFiles.length > 0) {
      this.core.showConflictDialog(conflictMeta, conflictFiles, ctx);
    }
  }

  /**
   * 执行冲突处理结果（由 UploadConflictModal "确定"按钮 -> uploadCoreStore.resolveConflicts 调用）
   * @param {Array} conflicts - 冲突元数据数组 [{fileName, fileSize, existingId, existingSize, action, folderId?, folderPath?}]
   * @param {File[]} files - 与 conflicts 一一对应的 File 对象
   * @param {Object} ctx - 上传上下文
   */
  async executeConflictResolution(conflicts, files, ctx) {
    const targetFolderId = ctx.folderId;
    const targetIsPublic = ctx.isPublic;

    const replaceIndices = [];
    const keepItems = [];   // {file, folderId, folderPath}
    const skipNames = [];

    conflicts.forEach((c, i) => {
      if (c.action === 'replace') {
        replaceIndices.push(i);
      } else if (c.action === 'keep') {
        const folderId = c.folderId !== undefined ? c.folderId : targetFolderId;
        const folderPath = c.folderPath || '';
        // 标记 conflict_action 供上传代码传给后端
        files[i]._conflictAction = 'keep';
        keepItems.push({ file: files[i], folderId, folderPath });
      } else {
        skipNames.push(files[i].name);
      }
    });

    if (skipNames.length > 0) {
      message.info(`已跳过：${formatFileNames(skipNames)}`);
    }

    // 替换：先删除旧文件，再上传新文件
    let replaceItems = [];
    if (replaceIndices.length > 0) {
      const deleteParams = replaceIndices.map(i => ({
        id: conflicts[i].existingId,
        is_public: targetIsPublic,
      }));
      // 逐个删除并收集结果，避免 Promise.all 快速失败导致无法判断哪些成功
      const deleteResults = await Promise.all(deleteParams.map(async p => {
        try {
          const result = await http.delete('/api/document/file/', { params: p, timeout: 30000 });
          return { ok: true, result };
        } catch (error) {
          // HTTP 拦截器已经调用了 message.error，这里不再重复弹窗
          return { ok: false, error };
        }
      }));

      // 检查是否有失败的删除（包括 reject 和 resolve 但含 error 字段）
      const failedDeletes = deleteResults.filter(r => !r.ok || (r.result && r.result.error));
      if (failedDeletes.length > 0) {
        // 仅对 resolve 但含 error 的情况补充提示（拦截器未处理的边缘情况）
        const resolvedWithError = failedDeletes.find(r => r.ok && r.result && r.result.error);
        if (resolvedWithError) {
          message.error(typeof resolvedWithError.result.error === 'string'
            ? resolvedWithError.result.error
            : '删除旧文件失败，替换操作未完成');
        }
        // reject 的情况已由 HTTP 拦截器提示，不再重复
        return;
      }

      replaceItems = replaceIndices.map(i => ({
        file: files[i],
        folderId: conflicts[i].folderId !== undefined ? conflicts[i].folderId : targetFolderId,
        folderPath: conflicts[i].folderPath || '',
      }));
    }

    // 上传替换 + 保留两者的文件
    const itemsToUpload = [...replaceItems, ...keepItems];
    if (itemsToUpload.length > 0) {
      this.core.isPaused = false;
      this.core.isCancelled = false;
      this.core.pendingFiles = itemsToUpload.map(item => item.file);

      // 文件夹上传模式（conflict 含 folderId）用 batch 格式，单文件上传用 uniform 格式
      const hasPerFileFolderId = conflicts.some(c => c.folderId !== undefined);
      if (hasPerFileFolderId) {
        await this.processUploadQueue(itemsToUpload, null, ctx);
      } else {
        await this.processUploadQueue(itemsToUpload.map(item => item.file), targetFolderId, ctx);
      }
      this.core.queueStore.triggerRefresh();
    }
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
   * 【拖拽上传扩展】第三参数 targetContext（可选）：
   *   - 拖拽 drop 时由 captureUploadTargetContext 捕获的不可变快照
   *   - null 时由调用方负责捕获（按钮上传已在 handleFileSelect 捕获）
   *   - 包含 systemFolderCode/tenantId/isPublic，写入每个队列项，
   *     使后续 transfer/chunk/merge 请求不依赖当前路由的全局 system_folder 上下文
   *
   * @param {Array} filesOrItems - 文件列表 或 items 数组
   * @param {number|null} folderId - 目标文件夹ID（老格式必填，新格式传 null）
   * @param {Object|null} [targetContext=null] - 不可变上传目标上下文
   */
  @action
  async processUploadQueue(filesOrItems, folderId, targetContext = null) {
    // 【重构】检测输入格式：items 数组 vs 纯文件数组
    const isBatchFormat = Array.isArray(filesOrItems) && filesOrItems.length > 0 && filesOrItems[0] && filesOrItems[0].file;

    if (isBatchFormat) {
      return this._processBatch(filesOrItems, targetContext);
    }
    return this._processUniform(filesOrItems, folderId, targetContext);
  }

  /**
   * 【新格式】处理 items 批次（每个文件有自己的 folderId）
   * 用于文件夹上传：每个文件的目标文件夹不同
   * @private
   * @param {Array} items - [{file, folderId, folderPath}]
   * @param {Object|null} [targetContext=null] - 不可变上传目标上下文（systemFolderCode/tenantId/isPublic）
   */
  @action
  async _processBatch(items, targetContext = null) {
    // 文件夹上传时 isPublic/tenantId/systemFolderCode 来自 targetContext；
    // 兼容老调用方（未传 ctx）时回退到 navigationStore
    const ctx = targetContext || this.core.captureUploadTargetContext();
    const tenantId = ctx.tenantId;
    const isPublic = ctx.isPublic;
    const systemFolderCode = ctx.systemFolderCode;

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
        // 【拖拽上传】固化系统目录上下文，后续 transfer/chunk/merge 请求从此读取，
        // 不依赖 systemFolderContext 全局变量（党建任务离开页面后仍携带正确上下文）
        systemFolderCode: systemFolderCode,
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
   * @param {File[]} files - 文件数组
   * @param {number|null} folderId - 目标文件夹ID
   * @param {Object|null} [targetContext=null] - 不可变上传目标上下文
   */
  @action
  async _processUniform(files, folderId, targetContext = null) {
    // 普通上传时 isPublic/tenantId/systemFolderCode 来自 targetContext；
    // 兼容老调用方（未传 ctx）时回退到 navigationStore
    const ctx = targetContext || this.core.captureUploadTargetContext();
    const tenantId = ctx.tenantId;
    const isPublic = ctx.isPublic;
    const systemFolderCode = ctx.systemFolderCode;

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
        // 【拖拽上传】固化系统目录上下文，后续 transfer/chunk/merge 请求从此读取，
        // 不依赖 systemFolderContext 全局变量（党建任务离开页面后仍携带正确上下文）
        systemFolderCode: systemFolderCode,
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

/**
 * FolderUploadStore - 文件夹上传协调器
 *
 * 【重构 2026-06-06】从 567 行精简为协调器
 * 职责（单一）：
 *   1. 接收用户选择的文件夹
 *   2. 委托 FolderStructureBuilder 创建文件夹结构
 *   3. 委托 FileUploadCoordinator 处理实际的上传
 *   4. 失败时回滚已创建的文件夹
 *
 * 不再自己实现：
 *   - 文件夹创建/查询/回滚（已抽到 FolderStructureBuilder）
 *   - 上传并发控制、状态机、进度更新（已由 FileUploadCoordinator 接管）
 */
import { action } from 'mobx';
import { message } from 'antd';
import { FolderStructureBuilder } from './folder/FolderStructureBuilder';

const FOLDER_UPLOAD_BATCH_SIZE = 20;

/**
 * 兜底文件名校验函数
 */
const defaultValidateFileName = (name) => {
  if (!name || name.length === 0) return { valid: false, message: '文件名不能为空' };
  if (name.length > 255) return { valid: false, message: '文件名超过255字符' };
  if (/[<>:"|?*\\/]/.test(name)) return { valid: false, message: '文件名包含非法字符' };
  return { valid: true };
};

/**
 * 路径安全校验（防路径遍历）
 */
const validatePathSecurity = (path) => {
  if (!path) return { valid: true };
  if (/\.\./.test(path) || path.startsWith('/') || path.startsWith('\\')) {
    return { valid: false, message: '路径包含非法字符' };
  }
  return { valid: true };
};

export class FolderUploadStore {
  constructor(queueStore, fileUploadStore, rootStore) {
    this.queueStore = queueStore;
    this.fileUploadStore = fileUploadStore;
    this.rootStore = rootStore;

    // 【重构】文件夹结构构建器（独立职责）
    this.structureBuilder = new FolderStructureBuilder();

    // 【Bug #4 修复】记录当前实例添加的 uniqueKey
    this._myUniqueKeys = new Set();

    // 页面卸载时清理唯一键
    this._cleanupOnUnload = () => this._clearUniqueKeys();
    if (typeof window !== 'undefined') {
      window.addEventListener('beforeunload', this._cleanupOnUnload);
    }
  }

  /**
   * 销毁时清理资源
   */
  destroy() {
    if (typeof window !== 'undefined') {
      window.removeEventListener('beforeunload', this._cleanupOnUnload);
    }
  }

  // ============================================================
  // 主入口
  // ============================================================

  /**
   * 处理文件夹选择（按钮上传入口）
   * @param {FileList} files - 带 webkitRelativePath 的文件列表
   * @param {Object|null} [targetContext=null] - 拖拽上传时由 captureUploadTargetContext 生成的不可变快照；
   *   按钮上传不传时由 uploadCoreStore.handleFolderSelect 已捕获
   */
  @action
  async handleFolderSelect(files, targetContext = null) {
    return this._processFolderUpload(files, targetContext, false);
  }

  /**
   * 【拖拽上传专用】处理规范化后的文件夹条目
   *
   * 与 handleFolderSelect 的区别：
   *   - handleFolderSelect 接收带 webkitRelativePath 的 File[]（按钮 webkitdirectory 路径）
   *   - handleFolderEntries 接收 {file, relativePath, rootName}[]（拖拽 webkitGetAsEntry 路径）
   *
   * 两条路径最终都走 FolderStructureBuilder + FileUploadCoordinator._processBatch，
   * 不创建第二套队列或协调器。
   *
   * @param {Array<{file: File, relativePath: string, rootName: string}>} entries
   * @param {Object|null} [targetContext=null] - drop 时捕获的不可变上下文快照
   */
  @action
  async handleFolderEntries(entries, targetContext = null) {
    return this._processFolderUpload(entries, targetContext, true);
  }

  /**
   * 文件夹上传统一处理逻辑（按钮 / 拖拽 共用）
   * @param {File[]|Array<{file, relativePath}>} filesOrEntries - 文件列表或规范化条目
   * @param {Object|null} targetContext - 不可变上传目标上下文
   * @param {boolean} isEntriesFormat - true=entries 格式，false=File[] 格式
   * @private
   */
  @action
  async _processFolderUpload(filesOrEntries, targetContext, isEntriesFormat) {
    // 党建文档系统目录上下文优先从 targetContext 读取
    const ctx = targetContext || this.rootStore.captureUploadTargetContext();
    const targetFolderId = ctx.folderId;
    const isPublic = ctx.isPublic;
    const systemFolderCode = ctx.systemFolderCode;

    // 1. 校验文件
    const { validFiles, invalidFiles } = this._validateFiles(filesOrEntries, isEntriesFormat);
    this._showInvalidFilesMessage(invalidFiles);

    if (validFiles.length === 0) return;

    // 2. 计算去重 key（顶层目录名 + 文件数 + 总大小 + 目标 + 空间 + 系统目录）
    const folderUniqueKey = this._generateFolderKey(validFiles, targetFolderId, isPublic, isEntriesFormat, systemFolderCode);
    const topFolderName = this._getTopFolderName(validFiles, isEntriesFormat);

    // 3. 检查重复
    if (this._checkDuplicateSubmission(folderUniqueKey, topFolderName)) return;

    // 4. 【2026-06-06】不自动展开传输列表抽屉，与单文件上传保持一致
    // 新任务进队列时只显示底部小条，用户主动点击/快捷键 (Ctrl+Shift+U) 才展开

    // 5. 初始化 pendingFolderFiles 状态
    this._initPendingState(validFiles, targetFolderId, isPublic, folderUniqueKey);

    // 6. 委托 FolderStructureBuilder 创建文件夹结构（显式传 systemFolderCode，
    //    党建任务离开党建路由后仍能把子目录创建到党建根下）
    let folderMap;
    try {
      folderMap = await this.structureBuilder.build(validFiles, targetFolderId, isPublic, systemFolderCode);
    } catch (error) {
      message.error(`文件夹创建失败: ${error.message || '未知错误'}`);
      await this.structureBuilder.rollback();
      this._clearFolderKey(folderUniqueKey);
      return;
    }

    // 7. 分批构造上传项并入队，第一批准备好后队列即可开始消费
    let enqueuedCount = 0;
    try {
      const coordinator = this.rootStore.fileUploadCoordinator;
      if (!coordinator) {
        throw new Error('上传协调器未初始化');
      }

      for (let i = 0; i < validFiles.length; i += FOLDER_UPLOAD_BATCH_SIZE) {
        if (this.rootStore.isCancelled) break;

        const batchSlice = validFiles.slice(i, i + FOLDER_UPLOAD_BATCH_SIZE);
        const batchItems = batchSlice.map(item => (
          this._buildUploadItem(item, folderMap, targetFolderId, isPublic, isEntriesFormat)
        ));

        // 透传 targetContext，让 _processBatch 把 systemFolderCode 写入每个队列项
        const uploadItems = await coordinator.processUploadQueue(batchItems, null, ctx);
        enqueuedCount += Array.isArray(uploadItems) ? uploadItems.length : batchItems.length;
        this.queueStore.setFolderUploadProgress(enqueuedCount, validFiles.length);

        await this._yieldToBrowser();
      }
    } catch (error) {
      console.error('[FolderUpload] 上传任务入队失败:', error);
      message.error(`上传任务入队失败: ${this._getErrorMessage(error)}`);
    } finally {
      this._clearFolderKey(folderUniqueKey);
    }
  }

  // ============================================================
  // 校验和辅助方法
  // ============================================================

  _buildUploadItem(item, folderMap, targetFolderId, isPublic, isEntriesFormat = false) {
    // 兼容两种格式：
    //   - File（按钮上传）：relativePath = file.webkitRelativePath
    //   - {file, relativePath, rootName}（拖拽上传）：relativePath = entry.relativePath
    const file = isEntriesFormat ? item.file : item;
    const relativePath = isEntriesFormat
      ? (item.relativePath || file.name)
      : (file.webkitRelativePath || file.name);
    const folderPath = relativePath.split('/').slice(0, -1).join('/');
    const itemFolderId = folderPath ? folderMap.get(folderPath) : targetFolderId;

    if (folderPath && (itemFolderId === null || itemFolderId === undefined)) {
      throw new Error(`文件夹路径创建失败: ${folderPath}`);
    }

    const uniqueKey = this.queueStore.generateUniqueKey(file, itemFolderId, isPublic);
    this._myUniqueKeys.add(uniqueKey);
    return { file, folderId: itemFolderId, folderPath };
  }

  _yieldToBrowser() {
    return new Promise(resolve => setTimeout(resolve, 0));
  }

  _getErrorMessage(error) {
    if (!error) return '未知错误';
    if (typeof error === 'string') return error;
    return error.message || '未知错误';
  }

  /**
   * 校验文件列表（支持 File[] 和 entries[] 两种格式）
   * @param {File[]|Array<{file, relativePath}>} filesOrEntries
   * @param {boolean} isEntriesFormat - true=entries 格式，false=File[] 格式
   */
  _validateFiles(filesOrEntries, isEntriesFormat = false) {
    const validFiles = [];
    const invalidFiles = [];

    for (const item of filesOrEntries) {
      const file = isEntriesFormat ? item.file : item;
      const relativePath = isEntriesFormat
        ? (item.relativePath || file.name)
        : (file.webkitRelativePath || file.name);

      const pathCheck = validatePathSecurity(relativePath);
      if (!pathCheck.valid) {
        invalidFiles.push({ name: file.name, reason: pathCheck.message });
        continue;
      }

      const nameCheck = defaultValidateFileName(file.name);
      if (nameCheck.valid) {
        // 保留原 item（entries 格式需要 relativePath；File 格式直接用 file.webkitRelativePath）
        validFiles.push(item);
      } else {
        invalidFiles.push({ name: file.name, reason: nameCheck.message });
      }
    }

    return { validFiles, invalidFiles };
  }

  _showInvalidFilesMessage(invalidFiles) {
    if (invalidFiles.length === 0) return;
    if (invalidFiles.length === 1) {
      message.error(`文件 "${invalidFiles[0].name}" 无法上传: ${invalidFiles[0].reason}`);
    } else {
      message.error(`${invalidFiles.length} 个文件无法上传，请检查文件名和路径`);
    }
  }

  /**
   * 生成文件夹去重 key（支持两种格式 + 系统目录隔离）
   */
  _generateFolderKey(filesOrEntries, targetFolderId, isPublic, isEntriesFormat = false, systemFolderCode = null) {
    const topFolderName = this._getTopFolderName(filesOrEntries, isEntriesFormat);
    const totalSize = filesOrEntries.reduce((sum, item) => {
      const f = isEntriesFormat ? item.file : item;
      return sum + f.size;
    }, 0);
    const scope = isPublic ? 'public' : 'private';
    const sys = systemFolderCode ? `-${systemFolderCode}` : '';
    return `folder-${topFolderName}-${filesOrEntries.length}-${totalSize}-${targetFolderId}-${scope}${sys}`;
  }

  /**
   * 获取顶层目录名（支持两种格式）
   */
  _getTopFolderName(filesOrEntries, isEntriesFormat = false) {
    if (filesOrEntries.length === 0) return 'unknown';
    const first = filesOrEntries[0];
    if (isEntriesFormat) {
      // entries 格式优先用 rootName（拖拽层提供），其次从 relativePath 切
      return first.rootName || (first.relativePath || first.file.name).split('/')[0] || 'unknown';
    }
    return first.webkitRelativePath?.split('/')[0] || first.name || 'unknown';
  }

  _checkDuplicateSubmission(folderUniqueKey, folderName) {
    if (this.queueStore?.uploadingUniqueKeys?.has(folderUniqueKey)) {
      message.warning(`文件夹 "${folderName}" 已在上传队列中，跳过重复提交`);
      return true;
    }
    return false;
  }

  _initPendingState(files, targetFolderId, isPublic, folderUniqueKey) {
    this.rootStore.pendingFiles = [...files];
    this.rootStore.pendingFolderFiles = {
      files,
      folderMap: new Map(),
      currentFolderId: targetFolderId,
      isPublic,
      folderUniqueKey
    };

    if (this.queueStore?.uploadingUniqueKeys) {
      this.queueStore.uploadingUniqueKeys.add(folderUniqueKey);
      this._myUniqueKeys.add(folderUniqueKey);
    }

    this.queueStore.setFolderUploadProgress(0, files.length);
  }

  // ============================================================
  // 清理
  // ============================================================

  /**
   * 清理唯一键（仅清理当前实例添加的）
   */
  _clearUniqueKeys() {
    if (this.queueStore?.uploadingUniqueKeys) {
      for (const key of this._myUniqueKeys) {
        this.queueStore.uploadingUniqueKeys.delete(key);
      }
      this._myUniqueKeys.clear();
    }
  }

  _clearFolderKey(folderUniqueKey) {
    if (this.queueStore?.uploadingUniqueKeys) {
      this.queueStore.uploadingUniqueKeys.delete(folderUniqueKey);
      this._myUniqueKeys.delete(folderUniqueKey);
    }
  }
}

export default FolderUploadStore;

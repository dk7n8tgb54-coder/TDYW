/**
 * FolderUploadStore - 文件夹上传
 * 职责：处理文件夹上传、递归创建文件夹结构
 * 
 * 优化内容：
 * 1. 区分本次创建和历史复用的文件夹，避免回滚误删用户数据
 * 2. 按深度分组，同深度并发创建，提升性能
 * 3. 增加失败回滚机制，清理半成品
 * 4. 页面卸载时清理唯一键，避免刷新后无法重传
 * 5. 外部依赖兜底，增强健壮性
 * 6. 路径安全校验，防止路径遍历
 */
import { action } from 'mobx';
import { message } from 'antd';
import { UPLOAD_CONSTANTS } from './upload-core-constants';

/**
 * 兜底文件名校验函数
 * 当外部依赖不可用时使用
 */
const defaultValidateFileName = (name) => {
  if (!name || name.length === 0) return { valid: false, message: '文件名不能为空' };
  if (name.length > 255) return { valid: false, message: '文件名超过255字符' };
  if (/[<>:"|?*\\/]/.test(name)) return { valid: false, message: '文件名包含非法字符' };
  return { valid: true };
};

/**
 * 路径安全校验
 * @param {string} path - 文件路径
 * @returns {{valid: boolean, message?: string}}
 */
const validatePathSecurity = (path) => {
  if (!path) return { valid: true };
  // 检查路径遍历攻击特征
  if (/\.\./.test(path) || path.startsWith('/') || path.startsWith('\\')) {
    return { valid: false, message: '路径包含非法字符' };
  }
  return { valid: true };
};

/**
 * 分批并发执行
 * @param {Array} items - 待处理项
 * @param {Function} processor - 处理函数
 * @param {number} concurrency - 并发数
 */
const runInBatches = async (items, processor, concurrency) => {
  const results = [];
  for (let i = 0; i < items.length; i += concurrency) {
    const batch = items.slice(i, i + concurrency);
    const batchResults = await Promise.all(batch.map(processor));
    results.push(...batchResults);
  }
  return results;
};

export class FolderUploadStore {
  constructor(queueStore, fileUploadStore, rootStore) {
    this.queueStore = queueStore;
    this.fileUploadStore = fileUploadStore;
    this.rootStore = rootStore;
    
    // 区分本次创建和历史复用的文件夹ID
    this.createdByThisInstance = new Set();
    this.reusedFolderIds = new Set();
    
    // 页面卸载时清理唯一键
    this._cleanupOnUnload = () => this._clearUniqueKeys();
    if (typeof window !== 'undefined') {
      window.addEventListener('beforeunload', this._cleanupOnUnload);
    }
  }

  /**
   * 清理唯一键
   */
  _clearUniqueKeys() {
    if (this.queueStore?.uploadingUniqueKeys) {
      this.queueStore.uploadingUniqueKeys.clear();
    }
  }

  /**
   * 销毁时清理
   */
  destroy() {
    if (typeof window !== 'undefined') {
      window.removeEventListener('beforeunload', this._cleanupOnUnload);
    }
  }

  /**
   * 获取文件名校验函数（优先外部，兜底默认）
   */
  _getValidateFileName() {
    try {
      const external = require('../../../utils/upload-utils');
      if (external?.validateFileName) return external.validateFileName;
    } catch (e) {
      console.warn('[FolderUpload] 外部校验函数不可用，使用默认实现');
    }
    return defaultValidateFileName;
  }

  /**
   * 校验文件
   */
  _validateFiles(files) {
    const validateFileName = this._getValidateFileName();
    const validFiles = [];
    const invalidFiles = [];

    for (const file of files) {
      const relativePath = file.webkitRelativePath || file.name;
      
      // 路径安全校验
      const pathCheck = validatePathSecurity(relativePath);
      if (!pathCheck.valid) {
        invalidFiles.push({ name: file.name, reason: pathCheck.message });
        continue;
      }
      
      // 文件名校验
      const nameCheck = validateFileName(file.name);
      if (nameCheck.valid) {
        validFiles.push(file);
      } else {
        invalidFiles.push({ name: file.name, reason: nameCheck.message });
      }
    }

    return { validFiles, invalidFiles };
  }

  /**
   * 显示无效文件提示
   */
  _showInvalidFilesMessage(invalidFiles) {
    if (invalidFiles.length === 0) return;
    
    if (invalidFiles.length === 1) {
      message.error(`文件 "${invalidFiles[0].name}" 无法上传: ${invalidFiles[0].reason}`);
    } else {
      message.error(`${invalidFiles.length} 个文件无法上传，请检查文件名和路径`);
    }
  }

  /**
   * 生成文件夹唯一键
   */
  _generateFolderKey(files, targetFolderId, isPublic) {
    const topFolderName = files[0]?.webkitRelativePath?.split('/')[0] || 'unknown';
    const totalSize = files.reduce((sum, f) => sum + f.size, 0);
    return `folder-${topFolderName}-${files.length}-${totalSize}-${targetFolderId}-${isPublic ? 'public' : 'private'}`;
  }

  /**
   * 检查是否重复提交
   */
  _checkDuplicateSubmission(folderUniqueKey, folderName) {
    if (this.queueStore?.uploadingUniqueKeys?.has(folderUniqueKey)) {
      message.warning(`文件夹 "${folderName}" 已在上传队列中，跳过重复提交`);
      return true;
    }
    return false;
  }

  /**
   * 初始化上传状态
   */
  _initUploadState(files, targetFolderId, isPublic, folderUniqueKey) {
    this.rootStore.isPaused = false;
    this.rootStore.isCancelled = false;
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
    }
    
    this.queueStore.setFolderUploadProgress(0, files.length);
  }

  /**
   * 提取文件夹路径并按深度分组
   */
  _extractAndGroupPaths(files) {
    const paths = [...new Set(
      files
        .map(f => (f.webkitRelativePath || f.name).split('/').slice(0, -1).join('/'))
        .filter(p => p)
    )];

    const depthGroups = new Map();
    paths.forEach(path => {
      const depth = path.split('/').length;
      if (!depthGroups.has(depth)) depthGroups.set(depth, []);
      depthGroups.get(depth).push(path);
    });

    return { paths, depthGroups };
  }

  /**
   * 处理文件夹选择（主入口）
   */
  @action
  async handleFolderSelect(files) {
    // 1. 校验文件
    const { validFiles, invalidFiles } = this._validateFiles(files);
    this._showInvalidFilesMessage(invalidFiles);
    
    if (validFiles.length === 0) return;

    // 2. 获取目标信息
    const targetFolderId = this.rootStore.rootStore?.navigationStore?.getUploadTargetFolderId?.() || null;
    const isPublic = this.rootStore.rootStore?.navigationStore?.isPublic;
    const folderUniqueKey = this._generateFolderKey(validFiles, targetFolderId, isPublic);
    const topFolderName = validFiles[0]?.webkitRelativePath?.split('/')[0] || 'unknown';

    // 3. 检查重复
    if (this._checkDuplicateSubmission(folderUniqueKey, topFolderName)) return;

    // 4. 显示上传面板
    if (this.rootStore.uploadUIStore?.showUploadPanel) {
      this.rootStore.uploadUIStore.showUploadPanel();
    }

    // 5. 初始化状态
    this._initUploadState(validFiles, targetFolderId, isPublic, folderUniqueKey);

    // 6. 提取并分组路径
    const { paths, depthGroups } = this._extractAndGroupPaths(validFiles);
    
    // 7. 并发创建文件夹结构
    const folderMap = new Map();
    try {
      await this._createFoldersConcurrently(depthGroups, targetFolderId, folderMap);
    } catch (error) {
      await this._rollbackCreatedFolders();
      message.error(`文件夹创建失败: ${error.message || '未知错误'}`);
      return;
    }

    // 8. 上传文件
    await this._uploadFiles(validFiles, folderMap, targetFolderId, folderUniqueKey);
  }

  /**
   * 并发创建文件夹（按深度分组，同深度并发）
   */
  async _createFoldersConcurrently(depthGroups, targetFolderId, folderMap) {
    const sortedDepths = Array.from(depthGroups.keys()).sort((a, b) => a - b);
    const CONCURRENCY = 3;

    for (const depth of sortedDepths) {
      const paths = depthGroups.get(depth);
      
      await runInBatches(
        paths,
        async (path) => {
          const folderId = await this._createFolderStructure(path, targetFolderId);
          folderMap.set(path, folderId);
        },
        CONCURRENCY
      );
    }
  }

  /**
   * 创建单个文件夹结构（支持幂等检查）
   */
  async _createFolderStructure(folderPath, parentFolderId) {
    const { http } = await import('libs');
    const isPublic = this.rootStore.pendingFolderFiles?.isPublic ?? 
                     this.rootStore.rootStore?.navigationStore?.isPublic;
    const paths = folderPath.split('/');
    let currentParentId = parentFolderId;
    let currentPath = '';

    for (const folderName of paths) {
      currentPath = currentPath ? `${currentPath}/${folderName}` : folderName;
      
      // 检查本地缓存
      const cachedId = this._getCachedFolderId(currentPath);
      if (cachedId) {
        currentParentId = cachedId;
        this.reusedFolderIds.add(currentParentId);
        continue;
      }

      // 服务端幂等检查
      const existingId = await this._checkExistingFolder(folderName, currentParentId, isPublic);
      if (existingId) {
        currentParentId = existingId;
        this.reusedFolderIds.add(currentParentId);
        this._cacheFolderId(currentPath, currentParentId);
        continue;
      }

      // 创建新文件夹
      const folderId = await this._createFolder(folderName, currentParentId, isPublic);
      currentParentId = folderId;
      this.createdByThisInstance.add(currentParentId);
      this._cacheFolderId(currentPath, currentParentId);
    }

    return currentParentId;
  }

  /**
   * 获取缓存的文件夹ID
   */
  _getCachedFolderId(path) {
    const folderMap = this.rootStore.pendingFolderFiles?.folderMap;
    if (!folderMap) return null;
    
    for (const [cachedPath, id] of folderMap) {
      if (cachedPath === path) return id;
    }
    return null;
  }

  /**
   * 缓存文件夹ID
   */
  _cacheFolderId(path, id) {
    if (this.rootStore.pendingFolderFiles?.folderMap) {
      this.rootStore.pendingFolderFiles.folderMap.set(path, id);
    }
  }

  /**
   * 检查服务端是否已存在文件夹
   */
  async _checkExistingFolder(name, parentId, isPublic) {
    try {
      const { http } = await import('libs');
      const result = await http.get('/api/document/folder/', {
        params: { parent_id: parentId, name, is_public: isPublic }
      });
      return result.results?.[0]?.id || null;
    } catch (e) {
      return null;
    }
  }

  /**
   * 创建单个文件夹
   */
  async _createFolder(name, parentId, isPublic) {
    const { http } = await import('libs');
    const params = {
      name,
      parent_id: parentId,
      is_public: isPublic,
    };
    
    const tenantId = isPublic ? null : sessionStorage.getItem('tenant_id');
    if (tenantId) {
      params.tenant_id = tenantId;
    }

    const result = await http.post('/api/document/folder/', params);
    return result.id;
  }

  /**
   * 回滚本次创建的文件夹
   */
  async _rollbackCreatedFolders() {
    if (this.createdByThisInstance.size === 0) return;
    
    console.warn('[FolderUpload] 回滚本次创建的文件夹:', this.createdByThisInstance.size);
    const { http } = await import('libs');
    
    for (const folderId of [...this.createdByThisInstance].reverse()) {
      try {
        await http.delete(`/api/document/folder/${folderId}/`);
      } catch (e) {
        console.error(`回滚文件夹 ${folderId} 失败:`, e);
      }
    }
    
    this.createdByThisInstance.clear();
    this.reusedFolderIds.clear();
  }

  /**
   * 上传文件 - 先全部加入队列显示，再并发上传
   */
  async _uploadFiles(files, folderMap, targetFolderId, folderUniqueKey) {
    const isPublic = this.rootStore.pendingFolderFiles?.isPublic;
    const CONCURRENCY = 3; // 同时上传3个文件
    
    // ========== 第一步：先把所有文件加入队列显示 ==========
    const uploadItems = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const targetId = this._getTargetFolderId(file, folderMap, targetFolderId);
      const folderPath = file.webkitRelativePath || '';
      
      // 预创建上传项（waiting状态），让用户先看到全部文件
      const uploadId = await this._prepareUploadItem(file, targetId, folderPath, isPublic, i);
      uploadItems.push({
        id: uploadId,
        file,
        targetId,
        index: i,
        status: 'waiting'
      });
    }
    
    // ========== 第二步：并发上传 ==========
    const status = {
      completed: 0,
      success: 0,
      failed: 0,
      paused: false,
      cancelled: false,
      failedFiles: []
    };

    // 包装单个文件上传
    const uploadSingleFile = async (item) => {
      // 检查暂停/取消状态
      if (status.cancelled) return { status: 'cancelled', item };
      if (status.paused) return { status: 'paused', item };

      // 更新状态为上传中
      this.queueStore.updateUploadItem(item.id, { status: 'uploading' });

      try {
        // 【关键修复】传入已有的 uploadId，避免重复创建队列项
        await this.fileUploadStore.uploadFileToFolder(
          item.file, item.targetId, null, isPublic, item.file._folderUploadId
        );
        status.success++;
        return { status: 'success', item };
      } catch (error) {
        status.failed++;
        status.failedFiles.push({ file: item.file, error, index: item.index });
        console.error(`文件上传失败: ${item.file.name}`, error);
        return { status: 'failed', item, error };
      } finally {
        status.completed++;
        this.queueStore.setFolderUploadProgress(status.completed, files.length);
      }
    };

    // 分批并发上传
    for (let i = 0; i < uploadItems.length; i += CONCURRENCY) {
      // 检查暂停/取消
      if (this.rootStore.isCancelled) {
        status.cancelled = true;
        this.rootStore.pendingFiles = files.slice(i);
        // 标记剩余未上传的为取消
        uploadItems.slice(i).forEach(item => {
          this.queueStore.updateUploadItem(item.id, { status: 'cancelled', error: '已取消' });
        });
        break;
      }

      if (this.rootStore.isPaused) {
        status.paused = true;
        this.rootStore.pendingFiles = files.slice(i);
        // 标记剩余未上传的为暂停
        uploadItems.slice(i).forEach(item => {
          this.queueStore.updateUploadItem(item.id, { status: 'paused', error: '已暂停' });
        });
        break;
      }

      // 当前批次并发上传
      const batch = uploadItems.slice(i, i + CONCURRENCY);
      await Promise.all(batch.map(item => uploadSingleFile(item)));
    }

    this._clearFolderKey(folderUniqueKey);
    
    // 如果有失败的文件，保存到状态供重试
    if (status.failedFiles.length > 0) {
      this.rootStore.failedFolderFiles = status.failedFiles;
    }
    
    this._showUploadResult(status.success, status.failed);
  }

  /**
   * 预创建上传项（先加入队列显示）
   */
  async _prepareUploadItem(file, targetFolderId, folderPath, isPublic, index) {
    const { generateUploadId } = await import('./upload-core-constants');
    const uploadId = generateUploadId();
    const tenantId = this.rootStore.getCurrentTenantId?.() || 'default';
    
    // 构建显示名称（包含文件夹路径）
    const displayName = folderPath ? `${folderPath}/${file.name}` : file.name;
    
    // 添加到队列（waiting状态）
    this.queueStore.addToQueue({
      id: uploadId,
      file: file,
      name: displayName,
      percent: 0,
      status: 'waiting', // 先显示为等待中
      error: null,
      canAbort: true,
      abortToken: null,
      abortController: null,
      uniqueKey: this.queueStore.generateUniqueKey(file, targetFolderId, isPublic),
      tenantId: tenantId,
      isPublic: isPublic,
      isCancelledByUser: false,
      isPausedByUser: false,
      transferId: null,
      totalChunks: file.size > 32 * 1024 * 1024 ? Math.ceil(file.size / (8 * 1024 * 1024)) : 1,
      fileSize: file.size,
      folderIndex: index, // 用于排序显示
    }, tenantId);
    
    this.queueStore.addUniqueKey(file, targetFolderId, isPublic);
    
    // 【关键】把 uploadId 存到文件对象上，供后续上传使用
    file._folderUploadId = uploadId;
    
    return uploadId;
  }

  /**
   * 获取目标文件夹ID
   */
  _getTargetFolderId(file, folderMap, targetFolderId) {
    const relativePath = file.webkitRelativePath || file.name;
    const folderPath = relativePath.split('/').slice(0, -1).join('/');
    return folderPath ? folderMap.get(folderPath) : targetFolderId;
  }

  /**
   * 清理文件夹唯一键
   */
  _clearFolderKey(folderUniqueKey) {
    if (this.queueStore?.uploadingUniqueKeys) {
      this.queueStore.uploadingUniqueKeys.delete(folderUniqueKey);
    }
  }

  /**
   * 显示上传结果
   */
  _showUploadResult(successCount, failCount) {
    if (successCount === 0) return;
    
    const msg = failCount > 0 
      ? `文件夹上传完成: ${successCount}个成功, ${failCount}个失败`
      : `文件夹上传完成: ${successCount}个文件`;
    message.success(msg);
  }
}

export default FolderUploadStore;

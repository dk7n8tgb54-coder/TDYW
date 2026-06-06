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
   * 处理文件夹选择（主入口）
   * @param {FileList} files - 带 webkitRelativePath 的文件列表
   */
  @action
  async handleFolderSelect(files) {
    // 1. 校验文件
    const { validFiles, invalidFiles } = this._validateFiles(files);
    this._showInvalidFilesMessage(invalidFiles);

    if (validFiles.length === 0) return;

    // 2. 获取目标信息
    const targetFolderId = this.rootStore.getUploadTargetFolderId?.() || null;
    const isPublic = this.rootStore.getIsPublic?.() ?? false;
    const folderUniqueKey = this._generateFolderKey(validFiles, targetFolderId, isPublic);
    const topFolderName = validFiles[0]?.webkitRelativePath?.split('/')[0] || 'unknown';

    // 3. 检查重复
    if (this._checkDuplicateSubmission(folderUniqueKey, topFolderName)) return;

    // 4. 【2026-06-06】不自动展开传输列表抽屉，与单文件上传保持一致
    // 新任务进队列时只显示底部小条，用户主动点击/快捷键 (Ctrl+Shift+U) 才展开

    // 5. 初始化 pendingFolderFiles 状态
    this._initPendingState(validFiles, targetFolderId, isPublic, folderUniqueKey);

    // 6. 委托 FolderStructureBuilder 创建文件夹结构
    let folderMap;
    try {
      folderMap = await this.structureBuilder.build(validFiles, targetFolderId, isPublic);
    } catch (error) {
      message.error(`文件夹创建失败: ${error.message || '未知错误'}`);
      await this.structureBuilder.rollback();
      this._clearFolderKey(folderUniqueKey);
      return;
    }

    // 7. 构造 items 数组，委托 FileUploadCoordinator 处理
    const items = validFiles.map(file => {
      const relativePath = file.webkitRelativePath || file.name;
      const folderPath = relativePath.split('/').slice(0, -1).join('/');
      const itemFolderId = folderPath ? folderMap.get(folderPath) : targetFolderId;
      const uniqueKey = this.queueStore.generateUniqueKey(file, itemFolderId, isPublic);
      this._myUniqueKeys.add(uniqueKey);
      return { file, folderId: itemFolderId, folderPath };
    });

    try {
      await this.rootStore.fileUploadCoordinator?.processUploadQueue(items);
    } catch (error) {
      console.error('[FolderUpload] 上传失败:', error);
      await this.structureBuilder.rollback();
    } finally {
      this._clearFolderKey(folderUniqueKey);
    }
  }

  // ============================================================
  // 校验和辅助方法
  // ============================================================

  _validateFiles(files) {
    const validFiles = [];
    const invalidFiles = [];

    for (const file of files) {
      const relativePath = file.webkitRelativePath || file.name;

      const pathCheck = validatePathSecurity(relativePath);
      if (!pathCheck.valid) {
        invalidFiles.push({ name: file.name, reason: pathCheck.message });
        continue;
      }

      const nameCheck = defaultValidateFileName(file.name);
      if (nameCheck.valid) {
        validFiles.push(file);
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

  _generateFolderKey(files, targetFolderId, isPublic) {
    const topFolderName = files[0]?.webkitRelativePath?.split('/')[0] || 'unknown';
    const totalSize = files.reduce((sum, f) => sum + f.size, 0);
    return `folder-${topFolderName}-${files.length}-${totalSize}-${targetFolderId}-${isPublic ? 'public' : 'private'}`;
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

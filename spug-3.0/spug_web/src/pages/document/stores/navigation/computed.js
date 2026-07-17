/**
 * NavigationComputed - 导航计算属性
 * 
 * 职责：提供基于导航状态的派生数据
 */
import { computed } from 'mobx';

class NavigationComputed {
  constructor(navigationStore) {
    this.store = navigationStore;
  }

  // ============================================================
  // 路径相关计算
  // ============================================================

  /**
   * 获取路径深度（层级数）
   * @returns {number} 路径深度，根目录为0
   */
  @computed
  get pathDepth() {
    return this.store.path?.length || 0;
  }

  /**
   * 获取当前路径名称字符串
   * @returns {string} 格式：文件夹1/文件夹2/...
   */
  @computed
  get pathString() {
    if (!this.store.path?.length) return '根目录';
    return this.store.path.map(p => p.name).join('/');
  }

  /**
   * 获取当前文件夹名称
   * @returns {string} 当前文件夹名，根目录返回'我的文件'或'公共共享库'
   */
  @computed
  get currentFolderName() {
    if (!this.store.currentFolderId) {
      return this.store.isPublic ? '公共共享库' : '我的文件';
    }
    const current = this.store.path[this.store.path.length - 1];
    return current?.name || '未知文件夹';
  }

  /**
   * 获取父文件夹ID
   * @returns {number|null} 父文件夹ID，根目录返回null
   */
  @computed
  get parentFolderId() {
    if (this.store.path.length <= 1) return null;
    return this.store.path[this.store.path.length - 2]?.id || null;
  }

  // ============================================================
  // 状态判断
  // ============================================================

  /**
   * 是否在根目录
   * @returns {boolean}
   */
  @computed
  get isRoot() {
    // 党建文档锁定模式：currentFolderId 即锁定根目录时视为"根"
    if (this.store.lockedRootFolderId) {
      return this.store.currentFolderId === this.store.lockedRootFolderId;
    }
    return !this.store.currentFolderId;
  }

  /**
   * 是否可以返回上一级
   * @returns {boolean}
   */
  @computed
  get canGoUp() {
    // 党建文档锁定模式：在锁定根目录时不能向上
    if (this.store.lockedRootFolderId) {
      return this.store.currentFolderId !== this.store.lockedRootFolderId
        && this.store.path.length > 0;
    }
    return this.store.path.length > 0;
  }

  /**
   * 当前空间名称
   * @returns {string}
   */
  @computed
  get spaceName() {
    if (this.store.lockedRootFolderName) {
      return this.store.lockedRootFolderName;
    }
    return this.store.isPublic ? '公共共享库' : '我的文件';
  }

  /**
   * 是否处于党建文档锁定根目录（用于 UI 隐藏重命名/移动/删除等操作）
   * @returns {boolean}
   */
  @computed
  get isLockedRoot() {
    if (!this.store.lockedRootFolderId) return false;
    return this.store.currentFolderId === this.store.lockedRootFolderId;
  }

  // ============================================================
  // 上传目标相关
  // ============================================================

  /**
   * 获取上传目标文件夹ID
   * 优先使用左侧树选中的文件夹，如果未选中则使用当前打开的文件夹
   * @returns {number|null} 目标文件夹ID
   */
  @computed
  get uploadTargetId() {
    return this.store.selectedFolderId !== null 
      ? this.store.selectedFolderId 
      : this.store.currentFolderId;
  }

  /**
   * 是否有明确的上传目标
   * @returns {boolean} 是否有选中的目标文件夹
   */
  @computed
  get hasUploadTarget() {
    return this.uploadTargetId !== null;
  }
}

export default NavigationComputed;

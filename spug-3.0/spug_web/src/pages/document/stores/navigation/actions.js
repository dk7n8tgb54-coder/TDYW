/**
 * NavigationActions - 导航动作集合
 * 
 * 职责：封装所有导航相关的状态变更操作
 * 将原 NavigationStore 中的 action 方法抽取到这里
 */
class NavigationActions {
  constructor(navigationStore) {
    this.store = navigationStore;
  }

  // ============================================================
  // 基础导航
  // ============================================================

  /**
   * 进入文件夹
   * @param {number} folderId - 文件夹ID
   * @param {string} folderName - 文件夹名称
   */
  enterFolder(folderId, folderName) {
    this.store.path.push({ id: folderId, name: folderName });
    this.store.currentFolderId = folderId;
    this.store.selectedFolderId = folderId; // 同步选中状态
    
    // 同步到URL
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 导航到指定路径层级
   * @param {number} index - 路径索引，-1表示返回根目录
   */
  navigateTo(index) {
    if (index < 0) {
      this.goToRoot();
    } else {
      this.store.path = this.store.path.slice(0, index + 1);
      this.store.currentFolderId = this.store.path[this.store.path.length - 1]?.id || null;
      this.store.selectedFolderId = this.store.currentFolderId;
    }
    
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 返回上一级目录
   */
  goUp() {
    if (this.store.path.length > 0) {
      this.store.path.pop();
      this.store.currentFolderId = this.store.path.length > 0 
        ? this.store.path[this.store.path.length - 1].id 
        : null;
      this.store.selectedFolderId = this.store.currentFolderId;
    }
    
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 跳转到根目录
   */
  goToRoot() {
    this.store.path = [];
    this.store.currentFolderId = null;
    this.store.selectedFolderId = null;
    
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  // ============================================================
  // 文件夹选择
  // ============================================================

  /**
   * 从左侧树选择文件夹
   * @param {number|null} folderId - 文件夹ID，null表示根目录
   * @param {string} folderName - 文件夹名称
   */
  selectFolder(folderId, folderName) {
    this.store.selectedFolderId = folderId;
    this.store.path = folderId ? [{ id: folderId, name: folderName }] : [];
    this.store.currentFolderId = folderId;
    
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 选择根节点（我的文件/公共共享库）
   * @param {boolean} isPublicRoot - 是否为公共根节点
   */
  selectRootFolder(isPublicRoot) {
    this.store.selectedFolderId = null;
    this.store.isPublic = isPublicRoot;
    this.store.path = [];
    this.store.currentFolderId = null;
    
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  // ============================================================
  // 空间切换
  // ============================================================

  /**
   * 切换到公共空间
   */
  switchToPublic() {
    this.selectRootFolder(true);
  }

  /**
   * 切换到私有空间
   */
  switchToPrivate() {
    this.selectRootFolder(false);
  }

  /**
   * 切换空间（自动取反）
   */
  toggleSpace() {
    this.selectRootFolder(!this.store.isPublic);
  }

  // ============================================================
  // 路径管理
  // ============================================================

  /**
   * 设置完整路径
   * @param {Array} path - 路径数组 [{id, name}, ...]
   * @param {number|null} currentId - 当前文件夹ID
   */
  setPath(path, currentId = null) {
    this.store.path = path || [];
    this.store.currentFolderId = currentId || (path?.[path.length - 1]?.id) || null;
    this.store.selectedFolderId = this.store.currentFolderId;
    
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 重置所有导航状态
   */
  reset() {
    this.store.path = [];
    this.store.currentFolderId = null;
    this.store.selectedFolderId = null;
    this.store.isPublic = false;
    
    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  // ============================================================
  // 状态恢复
  // ============================================================

  /**
   * 从URL恢复导航状态
   * @returns {boolean} 是否成功恢复
   */
  restoreFromUrl() {
    if (!this.store.sync) return false;
    
    const state = this.store.sync.parseFromUrl();
    if (!state) return false;

    this.store.isPublic = state.isPublic;
    if (state.path?.length) {
      this.setPath(state.path, state.folderId);
    } else {
      this.store.currentFolderId = state.folderId;
      this.store.selectedFolderId = state.folderId;
    }
    
    return true;
  }
}

export default NavigationActions;

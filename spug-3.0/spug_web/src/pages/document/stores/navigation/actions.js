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
    // 党建工作锁定模式：index < 0（返回根）定位到锁定根目录，不能回到公共库根目录
    if (index < 0) {
      if (this.store.lockedRootFolderId) {
        this.goToLockedRoot();
      } else {
        this.goToRoot();
      }
      return;
    }
    this.store.path = this.store.path.slice(0, index + 1);
    this.store.currentFolderId = this.store.path[this.store.path.length - 1]?.id || null;
    this.store.selectedFolderId = this.store.currentFolderId;

    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 返回上一级目录
   */
  goUp() {
    // 党建工作锁定模式：已在锁定根目录时不再向上
    if (this.store.lockedRootFolderId && this.store.currentFolderId === this.store.lockedRootFolderId) {
      return;
    }
    if (this.store.path.length > 0) {
      this.store.path.pop();
      // 防止回到锁定根目录之上（公共库根目录）
      if (this.store.lockedRootFolderId && this.store.path.length === 0) {
        this.goToLockedRoot();
        return;
      }
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
    // 党建工作锁定模式：根目录即锁定根目录
    if (this.store.lockedRootFolderId) {
      this.goToLockedRoot();
      return;
    }
    this.store.path = [];
    this.store.currentFolderId = null;
    this.store.selectedFolderId = null;

    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 跳转到党建工作锁定根目录
   */
  goToLockedRoot() {
    const rootId = this.store.lockedRootFolderId;
    const rootName = this.store.lockedRootFolderName || '党建工作';
    this.store.path = [{ id: rootId, name: rootName }];
    this.store.currentFolderId = rootId;
    this.store.selectedFolderId = rootId;

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
   * 选择根节点（公共共享库）
   */
  selectRootFolder() {
    // 党建工作锁定模式：固定为公共且定位到锁定根目录
    if (this.store.lockedRootFolderId) {
      this.goToLockedRoot();
      return;
    }
    this.store.selectedFolderId = null;
    this.store.isPublic = true;
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
    this.selectRootFolder();
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
    // 党建工作锁定模式：重置到锁定根目录，保持公共空间
    if (this.store.lockedRootFolderId) {
      this.goToLockedRoot();
      return;
    }
    this.store.path = [];
    this.store.currentFolderId = null;
    this.store.selectedFolderId = null;
    this.store.isPublic = true;

    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  // ============================================================
  // 系统目录（党建工作）
  // ============================================================

  /**
   * 初始化系统目录锁定模式（党建工作）
   * @param {Object} param
   * @param {string} param.code - 系统目录编码
   * @param {number} param.folderId - 根目录 ID
   * @param {string} param.name - 根目录显示名
   */
  initSystemFolder({ code, folderId, name }) {
    this.store.isPublic = true;
    this.store.mode = 'partyBuildingDocuments';
    this.store.systemFolderCode = code;
    this.store.lockedRootFolderId = folderId;
    this.store.lockedRootFolderName = name;
    this.store.path = [{ id: folderId, name }];
    this.store.currentFolderId = folderId;
    this.store.selectedFolderId = folderId;
    this.store.systemFolderReady = true;

    if (this.store.sync) {
      this.store.sync.syncToUrl();
    }
  }

  /**
   * 清除系统目录锁定模式（离开党建工作页面时调用）
   */
  clearSystemFolder() {
    this.store.mode = 'normal';
    this.store.systemFolderCode = null;
    this.store.lockedRootFolderId = null;
    this.store.lockedRootFolderName = null;
    this.store.systemFolderReady = false;
    this.store.path = [];
    this.store.currentFolderId = null;
    this.store.selectedFolderId = null;
    this.store.isPublic = true;

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

    this.store.isPublic = true;
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

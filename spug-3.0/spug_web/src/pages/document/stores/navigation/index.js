/**
 * NavigationStore - 文件夹导航管理（重构版）
 * 
 * 【重构说明】采用组合模式，将原有功能拆分为：
 * - Actions: 导航动作（enterFolder, navigateTo, etc.）
 * - Computed: 计算属性（pathDepth, isRoot, etc.）
 * - Sync: URL同步管理
 * 
 * 主类仅保留原始状态定义，所有操作委托给子模块
 */
import { observable, action } from 'mobx';
import NavigationActions from './actions';
import NavigationComputed from './computed';
import NavigationSync from './sync';

class NavigationStore {
  constructor(rootStore = null) {
    this.rootStore = rootStore;
    
    // 初始化子模块（注意顺序：先 sync -> actions/computed）
    this.sync = new NavigationSync(this);
    this.actions = new NavigationActions(this);
    this.computed = new NavigationComputed(this);
    
    // 如果没有传入 rootStore，尝试从 window 获取（开发调试用）
    if (!this.rootStore && typeof window !== 'undefined' && window.__ROOT_STORE__) {
      this.rootStore = window.__ROOT_STORE__;
    }
  }

  // ============================================================
  // 核心状态（保持与原API兼容）
  // ============================================================
  
  /**
   * 当前文件夹ID（右侧文件列表打开的文件夹）
   * @type {number|null}
   */
  @observable currentFolderId = null;

  /**
   * 左侧树选中的文件夹ID（用于上传目标）
   * @type {number|null}
   */
  @observable selectedFolderId = null;

  /**
   * 导航路径 [{id, name}, ...]
   * @type {Array}
   */
  @observable path = [];

  /**
   * 当前是否公共空间 false=我的文件, true=公共共享库
   * @type {boolean}
   */
  @observable isPublic = false;

  // ============================================================
  // 代理属性（兼容原API）
  // ============================================================

  // ----- 计算属性代理 -----
  get pathDepth() { return this.computed.pathDepth; }
  get pathString() { return this.computed.pathString; }
  get currentFolderName() { return this.computed.currentFolderName; }
  get parentFolderId() { return this.computed.parentFolderId; }
  get isRoot() { return this.computed.isRoot; }
  get canGoUp() { return this.computed.canGoUp; }
  get spaceName() { return this.computed.spaceName; }
  get uploadTargetId() { return this.computed.uploadTargetId; }
  get hasUploadTarget() { return this.computed.hasUploadTarget; }

  // ============================================================
  // 代理方法（兼容原API）
  // ============================================================

  // ----- 基础导航 -----
  @action.bound enterFolder(folderId, folderName) {
    return this.actions.enterFolder(folderId, folderName);
  }

  @action.bound navigateTo(index) {
    return this.actions.navigateTo(index);
  }

  @action.bound goUp() {
    return this.actions.goUp();
  }

  // ----- 文件夹选择 -----
  @action.bound selectFolder(folderId, folderName) {
    return this.actions.selectFolder(folderId, folderName);
  }

  @action.bound selectRootFolder(isPublicRoot) {
    return this.actions.selectRootFolder(isPublicRoot);
  }

  // ----- 路径管理 -----
  @action.bound setPath(path, currentId) {
    return this.actions.setPath(path, currentId);
  }

  @action.bound reset() {
    return this.actions.reset();
  }

  // ----- 获取当前路径（保持兼容） -----
  @action.bound getCurrentPath() {
    return this.path;
  }

  @action.bound getUploadTargetFolderId() {
    return this.computed.uploadTargetId;
  }
}

// 创建单例实例（保持向后兼容）
const navigationStore = new NavigationStore();
export default navigationStore;

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
  @observable isPublic = true;

  /**
   * 【党建文档】模式相关状态
   * - mode: 'normal' | 'partyBuildingDocuments'
   * - systemFolderCode: 系统目录编码（如 'party_building_documents'），为 null 表示普通模式
   * - lockedRootFolderId: 锁定的系统根目录 ID（党建文档根目录），导航不能超出此根
   * - lockedRootFolderName: 锁定根目录的显示名（如 '党建文档'）
   */
  @observable mode = 'normal';
  @observable systemFolderCode = null;
  @observable lockedRootFolderId = null;
  @observable lockedRootFolderName = null;

  /**
   * 是否已初始化系统目录（用于页面挂载时判断是否完成定位）
   */
  @observable systemFolderReady = false;

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
  get isLockedRoot() { return this.computed.isLockedRoot; }

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

  // ----- 系统目录（党建文档） -----
  @action.bound initSystemFolder({ code, folderId, name }) {
    return this.actions.initSystemFolder({ code, folderId, name });
  }

  @action.bound clearSystemFolder() {
    return this.actions.clearSystemFolder();
  }

  // ----- 获取当前路径（保持兼容） -----
  @action.bound getCurrentPath() {
    return this.path;
  }

  @action.bound getUploadTargetFolderId() {
    return this.computed.uploadTargetId;
  }
}

// 导出类（供 RootStore 创建实例和单元测试使用）
export { NavigationStore };

// ========== 向后兼容 ==========
// 旧组件使用: import navigationStore from './stores/navigation'
// 新组件应使用: import rootStore from './stores'; rootStore.navigationStore
// 
// 使用 Proxy 实现延迟绑定：default export 指向 RootStore 中的实例，
// 避免循环依赖，同时保证旧代码拿到的是 RootStore 管理的同一实例。
let _rootStoreNavigationStore = null;

export function _bindNavigationStore(instance) {
  _rootStoreNavigationStore = instance;
}

// default export 是一个 Proxy，所有属性访问委托给 RootStore 中的实例
const navigationStoreProxy = typeof Proxy !== 'undefined' 
  ? new Proxy({}, {
      get(_target, prop) {
        const store = _rootStoreNavigationStore;
        if (!store) {
          // RootStore 尚未初始化，返回 undefined（不应在正常流程中发生）
          return undefined;
        }
        const value = store[prop];
        // 绑定方法到正确的 this
        if (typeof value === 'function') {
          return value.bind(store);
        }
        return value;
      }
    })
  : new NavigationStore(); // 不支持 Proxy 的环境降级为独立实例

export default navigationStoreProxy;

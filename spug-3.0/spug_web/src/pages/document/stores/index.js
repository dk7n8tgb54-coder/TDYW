/**
 * Stores 统一导出
 * 职责：组合所有Store，提供统一的根Store
 * 
 * 【依赖注入重构】所有子 Store 由 RootStore 统一创建并注入依赖，
 * 移除模块级单例和 window.__ROOT_STORE__ fallback。
 */
import { NavigationStore, _bindNavigationStore } from './navigation';
import { UploadUIStore, _bindUploadUIStore } from './upload/ui';
import UploadCoreStore from './upload/core';
import { setRootStore } from './upload';

/**
 * RootStore - 根状态管理
 * 
 * 所有子 Store 由 RootStore 构造函数创建，rootStore 引用通过构造函数注入。
 * 这样做的好处：
 * 1. 单元测试可以创建独立 RootStore，无需清理全局状态
 * 2. 热更新不会因为模块级单例导致状态残留
 * 3. 不依赖 window 全局变量，SSR/Jest 环境安全
 */
class RootStore {
  constructor() {
    // 初始化导航Store（注入 rootStore）
    this.navigationStore = new NavigationStore(this);
    _bindNavigationStore(this.navigationStore);
    
    // 初始化UI Store（注入 rootStore）
    this.uploadUIStore = new UploadUIStore(this);
    _bindUploadUIStore(this.uploadUIStore);
    
    // 初始化上传核心Store（注入 rootStore）
    this.uploadCoreStore = new UploadCoreStore(this);
    
    // 设置rootStore引用（供upload模块内部使用）
    setRootStore(this);
  }
}

// 创建单例
const rootStore = new RootStore();

// 导出单例
export default rootStore;

// 导出Store类（便于单独使用和测试）
export { 
  NavigationStore,
  UploadUIStore,
  UploadCoreStore 
};

// 从upload模块导出子Store
export {
  UploadQueueStore,
  FileUploadStore,
  ChunkUploadStore,
  FolderUploadStore,
  MD5Store,
  TransferStore,
} from './upload';

// ========== 向后兼容：保持原有的导入方式 ==========

const uploadCoreStore = rootStore.uploadCoreStore;
const navigationStore = rootStore.navigationStore;
const uploadUIStore = rootStore.uploadUIStore;

export { 
  uploadCoreStore, 
  navigationStore, 
  uploadUIStore 
};

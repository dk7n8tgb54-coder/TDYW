/**
 * Stores 统一导出
 * 职责：组合所有Store，提供统一的根Store
 */
import navigationStore from './navigation';
import uploadUIStore from './upload/ui';
import UploadCoreStore from './upload/core';
import { setRootStore } from './upload';

/**
 * RootStore - 根状态管理
 */
class RootStore {
  constructor() {
    // 初始化UI Store（使用单例）
    this.uploadUIStore = uploadUIStore;
    
    // 初始化导航Store（使用单例）
    this.navigationStore = navigationStore;
    
    // 初始化上传核心Store（传入rootStore作为依赖）
    this.uploadCoreStore = new UploadCoreStore(this);
    
    // 设置rootStore引用（供upload模块使用）
    setRootStore(this);
  }
}

// 创建单例
const rootStore = new RootStore();

// 导出单例
export default rootStore;

// 导出Store类（便于单独使用）
export { 
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

export { 
  uploadCoreStore, 
  navigationStore, 
  uploadUIStore 
};

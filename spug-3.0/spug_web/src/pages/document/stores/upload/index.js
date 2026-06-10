/**
 * Upload 模块统一导出
 * 
 * 使用示例：
 *   import { UploadCoreStore, UploadQueueStore } from './upload';
 *   或
 *   import { uploadCoreStore } from './upload';  // 直接获取单例
 */

// 核心Store
export { default as UploadCoreStore, getUploadCoreStore } from './core';

// 子Store
export { UploadQueueStore } from './core/queue';
export { FileUploadStore } from './core/fileUpload';
export { ChunkUploadStore } from './core/chunkUpload';
export { FolderUploadStore } from './core/folderUpload';
export { MD5Store } from './core/md5';
export { TransferStore } from './core/transfer';

// 状态机
export { UploadStateMachine } from './core/UploadStateMachine';
export { StateMachineManager } from './core/StateMachineManager';

// 便捷导出：从根Store获取单例
// 注意：需要在RootStore初始化后才能使用
let _rootStore = null;

export function setRootStore(rootStore) {
  _rootStore = rootStore;
}

export function getUploadStore() {
  if (!_rootStore) {
    console.warn('RootStore未初始化，请先调用setRootStore()');
    return null;
  }
  return _rootStore.uploadCoreStore;
}

// UI Store（注意：从 named export 导出类，而非 default export 的 Proxy 实例）
export { UploadUIStore } from './ui';

/**
 * 7.1 状态机测试 - 共享环境构造（非测试文件）
 * 提供给 stateMachineGateway.*.test.js 三个测试文件复用的 mock 环境。
 * jest 不会运行此文件（无 .test.js 后缀）。
 *
 * 【方向B 2026-06-27】移除 StoreEventAdapter/EventBus 依赖
 * 状态机 entry/exit 直接通过 context.queueStore.updateUploadItem 更新 item
 * 测试环境只需 mock queueStore，不再需要 adapter 桥接
 */
import { StateMachineManager } from '../StateMachineManager';

// 刷新微任务队列（用于 onRetryAction 等异步 scheduleStart）
export const flushMicrotasks = () => new Promise(resolve => setTimeout(resolve, 0));

/**
 * 构造测试环境：manager + mock stores + 稳定 itemRef
 * @param {object} overrides - 覆盖 itemRef 默认字段
 */
export function setupGatewayEnv(overrides = {}) {
  const capturedUpdates = [];
  const itemRef = {
    id: 'test-id',
    file: { name: 'test.txt', size: 1024 },
    fileHash: 'abc123',
    totalChunks: 1,       // 默认普通上传
    fileSize: 1024,
    status: 'waiting',
    isCancelledByUser: false,
    isPausedByUser: false,
    ...overrides,
  };

  const mockQueueStore = {
    findUploadItemInCurrentTenant: jest.fn(() => itemRef),
    updateUploadItem: jest.fn((id, updates) => {
      Object.assign(itemRef, updates);
      capturedUpdates.push({ id, ...updates });
    }),
    // 【7.3】操作版本号方法
    bumpOperationVersion: jest.fn((id) => {
      const next = (itemRef.operationVersion || 0) + 1;
      itemRef.operationVersion = next;
      return next;
    }),
    getOperationVersion: jest.fn(() => itemRef.operationVersion || 0),
    isCurrentOperation: jest.fn((id, version) => {
      if (!version) return true;
      return (itemRef.operationVersion || 0) === version;
    }),
  };
  const mockTransferStore = { updateTransferStatus: jest.fn() };

  const manager = new StateMachineManager();

  return { manager, mockQueueStore, mockTransferStore, capturedUpdates, itemRef };
}

/** 销毁测试环境，避免状态机残留 */
export function teardownGatewayEnv(adapter, manager) {
  // 【方向B】adapter 参数保留仅为向后兼容，实际已无 adapter
  if (manager) {
    manager.clear();
  }
}

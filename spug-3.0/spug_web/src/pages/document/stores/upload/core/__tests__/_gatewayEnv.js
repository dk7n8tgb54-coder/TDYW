/**
 * 7.1 状态机测试 - 共享环境构造（非测试文件）
 * 提供给 stateMachineGateway.*.test.js 三个测试文件复用的 mock 环境。
 * jest 不会运行此文件（无 .test.js 后缀）。
 */
import { StateMachineManager } from '../StateMachineManager';
import { StoreEventAdapter } from '../StoreEventAdapter';
import { globalEventBus } from '../EventBus';

// 刷新微任务队列（用于 onRetryAction 等异步 scheduleStart）
export const flushMicrotasks = () => new Promise(resolve => setTimeout(resolve, 0));

/**
 * 构造测试环境：manager + adapter + mock stores + 稳定 itemRef
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
  };
  const mockTransferStore = { updateTransferStatus: jest.fn() };

  const manager = new StateMachineManager();
  const adapter = new StoreEventAdapter({
    queueStore: mockQueueStore,
    transferStore: mockTransferStore,
  });
  adapter.init();

  return { manager, adapter, mockQueueStore, mockTransferStore, capturedUpdates, itemRef };
}

/** 销毁测试环境，避免 EventBus 残留监听器 */
export function teardownGatewayEnv(adapter, manager) {
  adapter.destroy();
  manager.clear();
  globalEventBus.clear();
}

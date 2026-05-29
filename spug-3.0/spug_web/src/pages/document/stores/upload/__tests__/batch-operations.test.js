/**
 * 批量操作功能测试
 * 测试内容：
 * 1. TransferStore 批量暂停/恢复/取消方法
 * 2. 异常处理和loading状态
 * 3. 批量API调用替代循环调用
 *
 * @jest-environment jsdom
 */

import { TransferStore } from '../core/transfer';
import { API_ENDPOINTS } from '../../constants';

// Mock libs/http
jest.mock('libs', () => ({
  http: {
    post: jest.fn(),
    get: jest.fn(),
    delete: jest.fn(),
  },
}));

// Mock message
jest.mock('antd', () => ({
  message: {
    loading: jest.fn(() => jest.fn()),
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
    destroy: jest.fn(),
  },
}));

import { http } from 'libs';
import { message } from 'antd';

describe('TransferStore 批量操作测试', () => {
  let store;
  let rootStore;

  beforeEach(() => {
    jest.clearAllMocks();
    rootStore = {
      navigationStore: {
        isPublic: false,
        currentFolderId: 1,
      },
    };
    store = new TransferStore(rootStore);
  });

  describe('batchPauseTransfers', () => {
    it('应该成功批量暂停传输记录', async () => {
      const ids = [1, 2, 3];
      const mockResponse = { updated: 3, success_ids: [1, 2, 3] };
      http.post.mockResolvedValueOnce(mockResponse);

      const result = await store.batchPauseTransfers(ids);

      expect(http.post).toHaveBeenCalledWith(
        API_ENDPOINTS.TRANSFERS_BATCH_PAUSE,
        { transfer_ids: ids }
      );
      expect(result.success).toBe(true);
      expect(result.updated).toBe(3);
      expect(message.loading).toHaveBeenCalledWith('正在暂停 3 个传输任务...', 0);
      expect(message.success).toHaveBeenCalledWith('已暂停 3 个传输任务');
    });

    it('空ID列表应该直接返回成功', async () => {
      const result = await store.batchPauseTransfers([]);

      expect(http.post).not.toHaveBeenCalled();
      expect(result.success).toBe(true);
      expect(result.updated).toBe(0);
    });

    it('应该处理403无权限错误', async () => {
      const ids = [1, 2];
      const error = { status: 403, message: 'Forbidden' };
      http.post.mockRejectedValueOnce(error);

      const result = await store.batchPauseTransfers(ids);

      expect(result.success).toBe(false);
      expect(message.error).toHaveBeenCalledWith('批量暂停失败: 无权限操作');
    });

    it('应该处理500服务器错误', async () => {
      const ids = [1, 2];
      const error = { status: 500, message: 'Internal Server Error' };
      http.post.mockRejectedValueOnce(error);

      const result = await store.batchPauseTransfers(ids);

      expect(result.success).toBe(false);
      expect(message.error).toHaveBeenCalledWith('批量暂停失败: 服务器错误，请稍后重试');
    });

    it('应该处理网络错误', async () => {
      const ids = [1];
      const error = { message: 'Network Error' };
      http.post.mockRejectedValueOnce(error);

      const result = await store.batchPauseTransfers(ids);

      expect(result.success).toBe(false);
      expect(message.error).toHaveBeenCalledWith('批量暂停失败: Network Error');
    });
  });

  describe('batchResumeTransfers', () => {
    it('应该成功批量恢复传输记录', async () => {
      const ids = [1, 2, 3];
      const mockResponse = { updated: 3, success_ids: [1, 2, 3] };
      http.post.mockResolvedValueOnce(mockResponse);

      const result = await store.batchResumeTransfers(ids);

      expect(http.post).toHaveBeenCalledWith(
        API_ENDPOINTS.TRANSFERS_BATCH_RESUME,
        { transfer_ids: ids }
      );
      expect(result.success).toBe(true);
      expect(result.updated).toBe(3);
      expect(message.loading).toHaveBeenCalledWith('正在恢复 3 个传输任务...', 0);
      expect(message.success).toHaveBeenCalledWith('已恢复 3 个传输任务');
    });

    it('空ID列表应该直接返回成功', async () => {
      const result = await store.batchResumeTransfers([]);

      expect(http.post).not.toHaveBeenCalled();
      expect(result.success).toBe(true);
      expect(result.updated).toBe(0);
    });

    it('应该正确处理部分成功的情况', async () => {
      const ids = [1, 2, 3];
      const mockResponse = { updated: 1, success_ids: [1] };
      http.post.mockResolvedValueOnce(mockResponse);

      const result = await store.batchResumeTransfers(ids);

      expect(result.success).toBe(true);
      expect(result.updated).toBe(1);
      expect(message.success).toHaveBeenCalledWith('已恢复 1 个传输任务');
    });
  });

  describe('batchCancelTransfers', () => {
    it('应该成功批量取消传输记录', async () => {
      const ids = [1, 2, 3];
      const mockResponse = { task_id: 'celery-task-123', status: 'pending' };
      http.post.mockResolvedValueOnce(mockResponse);

      const result = await store.batchCancelTransfers(ids);

      expect(http.post).toHaveBeenCalledWith(
        API_ENDPOINTS.TRANSFERS_BATCH_CANCEL,
        { transfer_ids: ids }
      );
      expect(result.success).toBe(true);
      expect(result.task_id).toBe('celery-task-123');
      expect(message.loading).toHaveBeenCalledWith('正在取消 3 个传输任务...', 0);
      expect(message.success).toHaveBeenCalledWith('已提交批量取消任务 (任务ID: celery-task-123)');
    });

    it('空ID列表应该直接返回成功', async () => {
      const result = await store.batchCancelTransfers([]);

      expect(http.post).not.toHaveBeenCalled();
      expect(result.success).toBe(true);
    });

    it('应该处理服务器错误', async () => {
      const ids = [1, 2];
      const error = { status: 500 };
      http.post.mockRejectedValueOnce(error);

      const result = await store.batchCancelTransfers(ids);

      expect(result.success).toBe(false);
      expect(message.error).toHaveBeenCalledWith('批量取消失败: 服务器错误，请稍后重试');
    });
  });

  describe('批量操作性能测试', () => {
    it('批量暂停应该只调用一次API', async () => {
      const ids = Array.from({ length: 100 }, (_, i) => i + 1);
      http.post.mockResolvedValueOnce({ updated: 100 });

      await store.batchPauseTransfers(ids);

      expect(http.post).toHaveBeenCalledTimes(1);
      expect(http.post).toHaveBeenCalledWith(
        API_ENDPOINTS.TRANSFERS_BATCH_PAUSE,
        { transfer_ids: ids }
      );
    });

    it('批量恢复应该只调用一次API', async () => {
      const ids = Array.from({ length: 50 }, (_, i) => i + 1);
      http.post.mockResolvedValueOnce({ updated: 50 });

      await store.batchResumeTransfers(ids);

      expect(http.post).toHaveBeenCalledTimes(1);
    });

    it('批量取消应该只调用一次API', async () => {
      const ids = Array.from({ length: 30 }, (_, i) => i + 1);
      http.post.mockResolvedValueOnce({ task_id: 'task-123' });

      await store.batchCancelTransfers(ids);

      expect(http.post).toHaveBeenCalledTimes(1);
    });
  });

  describe('loading状态管理', () => {
    it('应该显示并隐藏loading', async () => {
      const hideLoading = jest.fn();
      message.loading.mockReturnValueOnce(hideLoading);
      http.post.mockResolvedValueOnce({ updated: 3 });

      await store.batchPauseTransfers([1, 2, 3]);

      expect(message.loading).toHaveBeenCalledWith('正在暂停 3 个传输任务...', 0);
      expect(hideLoading).toHaveBeenCalled();
    });

    it('错误时也应该隐藏loading', async () => {
      const hideLoading = jest.fn();
      message.loading.mockReturnValueOnce(hideLoading);
      http.post.mockRejectedValueOnce(new Error('Network Error'));

      await store.batchPauseTransfers([1, 2]);

      expect(hideLoading).toHaveBeenCalled();
    });
  });
});

// 模拟运行测试
console.log('\n============================================');
console.log('  TransferStore 批量操作单元测试');
console.log('============================================\n');

console.log('测试场景:');
console.log('1. ✓ 批量暂停/恢复/取消功能');
console.log('2. ✓ 异常处理（403/500/网络错误）');
console.log('3. ✓ Loading状态管理');
console.log('4. ✓ 性能测试（单次API调用替代循环）');
console.log('\n运行方式: npm test -- batch-operations.test.js\n');

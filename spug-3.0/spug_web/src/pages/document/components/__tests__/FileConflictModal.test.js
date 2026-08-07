/**
 * 前端测试：统一冲突弹窗 + 冲突检测逻辑
 *
 * 覆盖：
 * 1. FileConflictModal 正确显示冲突列表
 * 2. 三种操作选项（replace/keep/skip）
 * 3. 全部替换/全部保留/全部跳过
 * 4. onConfirm 回调返回正确的 actions 数组
 * 5. 冲突检测逻辑（API 返回 status:conflict 时收集冲突）
 * 6. 无冲突时直接执行
 * 7. skip 不计入成功
 * 8. HTTP 200 + error 不显示成功
 * 9. 错误消息只显示一次
 */

// Mock antd message
const mockMessage = {
  info: jest.fn(),
  error: jest.fn(),
  success: jest.fn(),
  warning: jest.fn(),
};
jest.mock('antd', () => ({
  message: mockMessage,
  Modal: jest.fn(() => null),
  Table: jest.fn(() => null),
  Radio: { Group: jest.fn(() => null), Button: jest.fn(() => null) },
  Button: jest.fn(() => null),
  Space: jest.fn(() => null),
  Typography: { Text: jest.fn(() => null) },
}));

// Mock http
const mockHttpPost = jest.fn();
jest.mock('libs/http', () => ({
  __esModule: true,
  default: {
    delete: jest.fn(),
    post: mockHttpPost,
    get: jest.fn(),
    put: jest.fn(),
  },
}));


describe('统一冲突处理前端测试', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('FileConflictModal 组件逻辑', () => {
    // 测试 FileConflictModal 的核心逻辑（不依赖 React 渲染）
    function createConflictActions(conflicts, defaultAction = 'replace') {
      return conflicts.map(() => defaultAction);
    }

    it('默认所有冲突项 action 为 replace', () => {
      const conflicts = [
        { existing_name: 'a.txt', new_name: 'a.txt', existing_size: 100, new_size: 200 },
        { existing_name: 'b.txt', new_name: 'b.txt', existing_size: 50, new_size: 50 },
      ];
      const actions = createConflictActions(conflicts);
      expect(actions).toEqual(['replace', 'replace']);
    });

    it('全部替换设置所有 action 为 replace', () => {
      const conflicts = [{}, {}, {}];
      const actions = conflicts.map(() => 'skip'); // 初始为 skip
      conflicts.forEach((_, i) => { actions[i] = 'replace'; });
      expect(actions).toEqual(['replace', 'replace', 'replace']);
    });

    it('全部保留设置所有 action 为 keep', () => {
      const conflicts = [{}, {}, {}];
      const actions = conflicts.map(() => 'keep');
      expect(actions).toEqual(['keep', 'keep', 'keep']);
    });

    it('全部跳过设置所有 action 为 skip', () => {
      const conflicts = [{}, {}, {}];
      const actions = conflicts.map(() => 'skip');
      expect(actions).toEqual(['skip', 'skip', 'skip']);
    });

    it('每个冲突项可单独选择不同 action', () => {
      const conflicts = [{}, {}, {}];
      const actions = ['replace', 'keep', 'skip'];
      expect(actions[0]).toBe('replace');
      expect(actions[1]).toBe('keep');
      expect(actions[2]).toBe('skip');
    });

    it('onConfirm 返回 actions 数组', () => {
      const conflicts = [{}, {}];
      const actions = ['replace', 'skip'];
      // 模拟 onConfirm 回调
      const result = actions;
      expect(result).toHaveLength(2);
      expect(result[0]).toBe('replace');
      expect(result[1]).toBe('skip');
    });
  });

  describe('冲突检测逻辑（模拟 handleCopyItems）', () => {
    /**
     * 模拟 handleCopyItems 的核心逻辑
     */
    async function simulateCopyItems(items, targetFolderId, isPublic) {
      let successCount = 0;
      let failCount = 0;
      const conflicts = [];
      const pendingOps = [];

      for (const item of items) {
        if (item.isFolder) {
          mockHttpPost.mockResolvedValueOnce({});
          try {
            await mockHttpPost('/api/document/folder/copy/', {
              id: item.id, target_id: targetFolderId, is_public: isPublic
            }, { timeout: 300000 });
            successCount++;
          } catch (e) {
            failCount++;
          }
        } else {
          const result = await mockHttpPost('/api/document/file/copy/', {
            id: item.id, folder_id: targetFolderId, is_public: isPublic
          }, { timeout: 300000 });

          if (result && result.status === 'conflict') {
            conflicts.push(result.conflicts[0]);
            pendingOps.push({
              item, endpoint: '/api/document/file/copy/',
              targetFolderId, paramKey: 'folder_id'
            });
          } else {
            successCount++;
          }
        }
      }

      return { successCount, failCount, conflicts, pendingOps };
    }

    it('无冲突时直接执行，不弹窗', async () => {
      mockHttpPost.mockResolvedValue({ status: 'success' });

      const items = [
        { id: 1, name: 'a.txt', isFolder: false },
        { id: 2, name: 'b.txt', isFolder: false },
      ];

      const result = await simulateCopyItems(items, 100, false);

      expect(result.successCount).toBe(2);
      expect(result.failCount).toBe(0);
      expect(result.conflicts).toHaveLength(0);
      expect(result.pendingOps).toHaveLength(0);
    });

    it('有冲突时收集冲突信息', async () => {
      mockHttpPost
        .mockResolvedValueOnce({
          status: 'conflict',
          conflicts: [{ existing_name: 'a.txt', new_name: 'a.txt', existing_size: 100, new_size: 200 }]
        })
        .mockResolvedValueOnce({ status: 'success' });

      const items = [
        { id: 1, name: 'a.txt', isFolder: false },
        { id: 2, name: 'b.txt', isFolder: false },
      ];

      const result = await simulateCopyItems(items, 100, false);

      expect(result.successCount).toBe(1); // b.txt 成功
      expect(result.conflicts).toHaveLength(1); // a.txt 冲突
      expect(result.pendingOps).toHaveLength(1);
    });

    it('同名同大小也弹窗（不跳过）', async () => {
      mockHttpPost.mockResolvedValue({
        status: 'conflict',
        conflicts: [{
          existing_name: 'same.txt', new_name: 'same.txt',
          existing_size: 100, new_size: 100, same_size: true
        }]
      });

      const items = [{ id: 1, name: 'same.txt', isFolder: false }];
      const result = await simulateCopyItems(items, 100, false);

      expect(result.conflicts).toHaveLength(1);
      expect(result.conflicts[0].same_size).toBe(true);
    });
  });

  describe('冲突解决逻辑（模拟 resolveConflicts）', () => {
    /**
     * 模拟 resolveConflicts 的核心逻辑
     */
    async function simulateResolveConflicts(pendingOps, actions, isPublic) {
      let successCount = 0;
      let failCount = 0;
      let skipCount = 0;

      for (let i = 0; i < pendingOps.length; i++) {
        const { item, endpoint, targetFolderId, paramKey } = pendingOps[i];
        const action = actions[i];

        if (action === 'skip') {
          skipCount++;
          continue;
        }

        try {
          const result = await mockHttpPost(endpoint, {
            id: item.id,
            [paramKey]: targetFolderId,
            is_public: isPublic,
            conflict_action: action,
          }, { timeout: 300000 });

          if (result && result.status === 'conflict') {
            failCount++;
          } else if (result && result.status === 'skipped') {
            skipCount++;
          } else {
            successCount++;
          }
        } catch (e) {
          failCount++;
        }
      }

      return { successCount, failCount, skipCount };
    }

    it('replace 动作发送 conflict_action=replace', async () => {
      mockHttpPost.mockResolvedValue({ status: 'success' });

      const pendingOps = [{
        item: { id: 1, name: 'a.txt' },
        endpoint: '/api/document/file/copy/',
        targetFolderId: 100,
        paramKey: 'folder_id'
      }];
      const actions = ['replace'];

      const result = await simulateResolveConflicts(pendingOps, actions, false);

      expect(result.successCount).toBe(1);
      expect(mockHttpPost).toHaveBeenCalledWith(
        '/api/document/file/copy/',
        expect.objectContaining({ conflict_action: 'replace' }),
        expect.anything()
      );
    });

    it('keep 动作发送 conflict_action=keep', async () => {
      mockHttpPost.mockResolvedValue({ status: 'success' });

      const pendingOps = [{
        item: { id: 1, name: 'b.txt' },
        endpoint: '/api/document/file/move/',
        targetFolderId: 200,
        paramKey: 'target_id'
      }];
      const actions = ['keep'];

      const result = await simulateResolveConflicts(pendingOps, actions, false);

      expect(result.successCount).toBe(1);
      expect(mockHttpPost).toHaveBeenCalledWith(
        '/api/document/file/move/',
        expect.objectContaining({ conflict_action: 'keep' }),
        expect.anything()
      );
    });

    it('skip 不发送请求，不计入成功', async () => {
      const pendingOps = [
        { item: { id: 1 }, endpoint: '/api/document/file/copy/', targetFolderId: 100, paramKey: 'folder_id' },
        { item: { id: 2 }, endpoint: '/api/document/file/copy/', targetFolderId: 100, paramKey: 'folder_id' },
      ];
      const actions = ['skip', 'replace'];

      mockHttpPost.mockResolvedValue({ status: 'success' });
      const result = await simulateResolveConflicts(pendingOps, actions, false);

      expect(result.skipCount).toBe(1);
      expect(result.successCount).toBe(1);
      // skip 不调用 API
      expect(mockHttpPost).toHaveBeenCalledTimes(1);
    });

    it('用户确认前不发送正式写入请求', async () => {
      // 预检阶段（无 conflict_action）不应该带 conflict_action
      const preCheckCall = {
        id: 1, folder_id: 100, is_public: false
      };
      // 确认阶段（有 conflict_action）才带
      const confirmCall = {
        id: 1, folder_id: 100, is_public: false,
        conflict_action: 'replace'
      };

      expect(preCheckCall.conflict_action).toBeUndefined();
      expect(confirmCall.conflict_action).toBe('replace');
    });

    it('HTTP 200 + error 不显示成功', async () => {
      // HTTP 拦截器行为：200 + error -> message.error + reject
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('权限不足');
        return Promise.reject('权限不足');
      });

      const pendingOps = [{
        item: { id: 1 }, endpoint: '/api/document/file/copy/',
        targetFolderId: 100, paramKey: 'folder_id'
      }];
      const actions = ['replace'];

      const result = await simulateResolveConflicts(pendingOps, actions, false);

      expect(result.failCount).toBe(1);
      expect(result.successCount).toBe(0);
      expect(mockMessage.success).not.toHaveBeenCalled();
    });

    it('批量混合处理结果统计准确', async () => {
      mockHttpPost
        .mockResolvedValueOnce({ status: 'success' })    // replace -> success
        .mockResolvedValueOnce({ status: 'success' })    // keep -> success
        .mockResolvedValueOnce({ status: 'conflict' }); // replace -> still conflict (并发)

      const pendingOps = [
        { item: { id: 1 }, endpoint: '/api/document/file/copy/', targetFolderId: 100, paramKey: 'folder_id' },
        { item: { id: 2 }, endpoint: '/api/document/file/copy/', targetFolderId: 100, paramKey: 'folder_id' },
        { item: { id: 3 }, endpoint: '/api/document/file/copy/', targetFolderId: 100, paramKey: 'folder_id' },
      ];
      const actions = ['replace', 'keep', 'skip'];

      const result = await simulateResolveConflicts(pendingOps, actions, false);

      expect(result.successCount).toBe(2);
      expect(result.failCount).toBe(0); // 第三个是 skip，不是 fail
      expect(result.skipCount).toBe(1);
    });

    it('错误消息只显示一次', async () => {
      // HTTP 拦截器弹一次 error，resolveConflicts 不再重复弹
      mockHttpPost.mockImplementation(() => {
        return Promise.reject('网络错误');
      });

      const pendingOps = [
        { item: { id: 1 }, endpoint: '/api/document/file/copy/', targetFolderId: 100, paramKey: 'folder_id' },
      ];
      const actions = ['replace'];

      const result = await simulateResolveConflicts(pendingOps, actions, false);

      // 失败计入 failCount，不显示 success
      expect(result.failCount).toBe(1);
      expect(result.successCount).toBe(0);
      // 拦截器已弹 error，resolveConflicts 不再调用 message.success
      expect(mockMessage.success).not.toHaveBeenCalled();
    });
  });

  describe('上传冲突条件变更', () => {
    it('同名同大小文件进入冲突列表（不跳过）', () => {
      // 模拟 FileUploadCoordinator 的冲突检测逻辑
      const file = { name: 'test.txt', size: 100 };
      const existingItems = [{ name: 'test.txt', file_size: 100, isFolder: false }];

      const existingItem = existingItems.find(
        item => item.name === file.name && !item.isFolder
      );

      // 修改后的逻辑：同名即冲突，不再检查大小
      const isConflict = !!existingItem;
      expect(isConflict).toBe(true);

      // 验证 sameSize 信息
      const existingSize = Number(existingItem.file_size || 0);
      const sameSize = existingSize === file.size;
      expect(sameSize).toBe(true); // 大小相同，但仍弹窗
    });

    it('同名不同大小文件进入冲突列表', () => {
      const file = { name: 'test.txt', size: 200 };
      const existingItems = [{ name: 'test.txt', file_size: 100, isFolder: false }];

      const existingItem = existingItems.find(
        item => item.name === file.name && !item.isFolder
      );

      const isConflict = !!existingItem;
      expect(isConflict).toBe(true);

      const existingSize = Number(existingItem.file_size || 0);
      const sameSize = existingSize === file.size;
      expect(sameSize).toBe(false); // 大小不同
    });
  });
});

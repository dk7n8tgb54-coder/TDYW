/**
 * Bug 1 测试：替换失败后不应继续上传新文件
 *
 * 由于 FileUploadCoordinator 使用 mobx @action 装饰器，
 * Jest 环境下无法直接导入，因此提取 executeConflictResolution
 * 的核心逻辑进行独立测试。
 *
 * 验证：
 * 1. DELETE resolve 成功 -> 调用上传队列
 * 2. DELETE resolve {error: '...'} -> 绝不调用上传队列
 * 3. DELETE reject -> 绝不调用上传队列
 * 4. 混合"替换、保留两者、跳过"时不破坏分类行为
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
}));

// Mock http
const mockHttpDelete = jest.fn();

/**
 * 提取 executeConflictResolution 中"替换"部分的核心逻辑
 * 与 FileUploadCoordinator.js 中修改后的代码保持一致
 */
async function executeReplaceLogic(conflicts, files, ctx) {
  const targetFolderId = ctx.folderId;
  const targetIsPublic = ctx.isPublic || false;

  // 分类
  const replaceIndices = [];
  const keepIndices = [];
  const skipIndices = [];
  conflicts.forEach((c, i) => {
    if (c.action === 'replace') replaceIndices.push(i);
    else if (c.action === 'keep') keepIndices.push(i);
    else if (c.action === 'skip') skipIndices.push(i);
  });

  // 跳过提示
  for (const i of skipIndices) {
    mockMessage.info(`已跳过：${conflicts[i].fileName}`);
  }

  // 替换：先删除旧文件，再上传新文件
  let replaceItems = [];
  if (replaceIndices.length > 0) {
    const deleteParams = replaceIndices.map(i => ({
      id: conflicts[i].existingId,
      is_public: targetIsPublic,
    }));
    // 逐个删除并收集结果，避免 Promise.all 快速失败导致无法判断哪些成功
    const deleteResults = await Promise.all(deleteParams.map(async p => {
      try {
        const result = await mockHttpDelete('/api/document/file/', { params: p, timeout: 30000 });
        return { ok: true, result };
      } catch (error) {
        // HTTP 拦截器已经调用了 message.error，这里不再重复弹窗
        return { ok: false, error };
      }
    }));

    // 检查是否有失败的删除（包括 reject 和 resolve 但含 error 字段）
    const failedDeletes = deleteResults.filter(r => !r.ok || (r.result && r.result.error));
    if (failedDeletes.length > 0) {
      // 仅对 resolve 但含 error 的情况补充提示（拦截器未处理的边缘情况）
      const resolvedWithError = failedDeletes.find(r => r.ok && r.result && r.result.error);
      if (resolvedWithError) {
        mockMessage.error(typeof resolvedWithError.result.error === 'string'
          ? resolvedWithError.result.error
          : '删除旧文件失败，替换操作未完成');
      }
      // reject 的情况已由 HTTP 拦截器提示，不再重复
      return { uploaded: false, items: [] };
    }

    replaceItems = replaceIndices.map(i => ({
      file: files[i],
      folderId: conflicts[i].folderId !== undefined ? conflicts[i].folderId : targetFolderId,
      folderPath: conflicts[i].folderPath || '',
    }));
  }

  // 保留两者
  const keepItems = keepIndices.map(i => ({
    file: files[i],
    folderId: conflicts[i].folderId !== undefined ? conflicts[i].folderId : targetFolderId,
    folderPath: conflicts[i].folderPath || '',
  }));

  // 合并上传队列
  const allItems = [...replaceItems, ...keepItems];

  // 模拟 processUploadQueue 调用
  mockProcessUploadQueue(allItems);

  return { uploaded: true, items: allItems };
}

const mockProcessUploadQueue = jest.fn();

describe('Bug1: executeConflictResolution 替换逻辑', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('场景1: DELETE 全部成功 -> 应调用上传队列', () => {
    it('单个替换文件，DELETE 成功后应调用上传队列', async () => {
      mockHttpDelete.mockResolvedValue({ success: true });

      const conflicts = [
        { fileName: 'foo.txt', existingId: 101, action: 'replace' },
      ];
      const files = [new File(['content'], 'foo.txt')];
      const ctx = { folderId: 1, isPublic: false };

      const result = await executeReplaceLogic(conflicts, files, ctx);

      expect(mockHttpDelete).toHaveBeenCalledTimes(1);
      expect(mockHttpDelete).toHaveBeenCalledWith(
        '/api/document/file/',
        { params: { id: 101, is_public: false }, timeout: 30000 }
      );
      expect(mockProcessUploadQueue).toHaveBeenCalledTimes(1);
      expect(result.uploaded).toBe(true);
      expect(result.items).toHaveLength(1);
    });

    it('多个替换文件，全部 DELETE 成功后应调用上传队列', async () => {
      mockHttpDelete.mockResolvedValue({ success: true });

      const conflicts = [
        { fileName: 'a.txt', existingId: 1, action: 'replace' },
        { fileName: 'b.txt', existingId: 2, action: 'replace' },
      ];
      const files = [
        new File(['a'], 'a.txt'),
        new File(['b'], 'b.txt'),
      ];
      const ctx = { folderId: 1, isPublic: false };

      const result = await executeReplaceLogic(conflicts, files, ctx);

      expect(mockHttpDelete).toHaveBeenCalledTimes(2);
      expect(mockProcessUploadQueue).toHaveBeenCalledTimes(1);
      expect(result.uploaded).toBe(true);
      expect(result.items).toHaveLength(2);
    });
  });

  describe('场景2: DELETE resolve {error: "..."} -> 绝不上传', () => {
    it('DELETE resolve 含 error 字段时不应调用上传队列', async () => {
      mockHttpDelete.mockResolvedValue({ error: '文件删除失败：权限不足' });

      const conflicts = [
        { fileName: 'foo.txt', existingId: 101, action: 'replace' },
      ];
      const files = [new File(['content'], 'foo.txt')];
      const ctx = { folderId: 1, isPublic: false };

      const result = await executeReplaceLogic(conflicts, files, ctx);

      expect(mockHttpDelete).toHaveBeenCalledTimes(1);
      expect(mockProcessUploadQueue).not.toHaveBeenCalled();
      expect(result.uploaded).toBe(false);
      // resolve 但含 error 时应补充提示
      expect(mockMessage.error).toHaveBeenCalledWith('文件删除失败：权限不足');
    });
  });

  describe('场景3: DELETE reject -> 绝不上传', () => {
    it('DELETE reject 时不应调用上传队列', async () => {
      // HTTP 拦截器已经调用了 message.error，reject 值为 string
      mockHttpDelete.mockRejectedValue('文件删除失败：网络错误');

      const conflicts = [
        { fileName: 'foo.txt', existingId: 101, action: 'replace' },
      ];
      const files = [new File(['content'], 'foo.txt')];
      const ctx = { folderId: 1, isPublic: false };

      const result = await executeReplaceLogic(conflicts, files, ctx);

      expect(mockHttpDelete).toHaveBeenCalledTimes(1);
      expect(mockProcessUploadQueue).not.toHaveBeenCalled();
      expect(result.uploaded).toBe(false);
      // reject 的情况已由 HTTP 拦截器提示，不重复弹窗
      expect(mockMessage.error).not.toHaveBeenCalled();
    });

    it('多个替换中任一 DELETE reject 时不应调用上传队列', async () => {
      mockHttpDelete
        .mockResolvedValueOnce({ success: true })
        .mockRejectedValueOnce('文件删除失败：服务器错误');

      const conflicts = [
        { fileName: 'a.txt', existingId: 1, action: 'replace' },
        { fileName: 'b.txt', existingId: 2, action: 'replace' },
      ];
      const files = [
        new File(['a'], 'a.txt'),
        new File(['b'], 'b.txt'),
      ];
      const ctx = { folderId: 1, isPublic: false };

      const result = await executeReplaceLogic(conflicts, files, ctx);

      expect(mockHttpDelete).toHaveBeenCalledTimes(2);
      expect(mockProcessUploadQueue).not.toHaveBeenCalled();
      expect(result.uploaded).toBe(false);
    });
  });

  describe('场景4: 混合"替换、保留两者、跳过"分类行为', () => {
    it('替换成功 + 保留两者 + 跳过 -> 三类各自正确处理', async () => {
      mockHttpDelete.mockResolvedValue({ success: true });

      const conflicts = [
        { fileName: 'replace.txt', existingId: 10, action: 'replace' },
        { fileName: 'keep.txt', existingId: 11, action: 'keep' },
        { fileName: 'skip.txt', existingId: 12, action: 'skip' },
      ];
      const files = [
        new File(['r'], 'replace.txt'),
        new File(['k'], 'keep.txt'),
        new File(['s'], 'skip.txt'),
      ];
      const ctx = { folderId: 5, isPublic: false };

      const result = await executeReplaceLogic(conflicts, files, ctx);

      // 替换：只删除了 1 个旧文件
      expect(mockHttpDelete).toHaveBeenCalledTimes(1);
      expect(mockHttpDelete).toHaveBeenCalledWith(
        '/api/document/file/',
        { params: { id: 10, is_public: false }, timeout: 30000 }
      );

      // 跳过：显示跳过提示
      expect(mockMessage.info).toHaveBeenCalledWith('已跳过：skip.txt');

      // 上传队列应被调用（替换 + 保留两者 = 2 个文件）
      expect(mockProcessUploadQueue).toHaveBeenCalledTimes(1);
      expect(result.uploaded).toBe(true);
      expect(result.items).toHaveLength(2);
    });

    it('替换失败 + 保留两者 -> 不上传替换文件，整体返回失败', async () => {
      mockHttpDelete.mockRejectedValue('删除失败');

      const conflicts = [
        { fileName: 'replace.txt', existingId: 10, action: 'replace' },
        { fileName: 'keep.txt', existingId: 11, action: 'keep' },
      ];
      const files = [
        new File(['r'], 'replace.txt'),
        new File(['k'], 'keep.txt'),
      ];
      const ctx = { folderId: 5, isPublic: false };

      const result = await executeReplaceLogic(conflicts, files, ctx);

      // 替换失败 -> 整体 return，不上传任何文件
      expect(mockHttpDelete).toHaveBeenCalledTimes(1);
      expect(mockProcessUploadQueue).not.toHaveBeenCalled();
      expect(result.uploaded).toBe(false);
      expect(result.items).toHaveLength(0);
    });
  });
});

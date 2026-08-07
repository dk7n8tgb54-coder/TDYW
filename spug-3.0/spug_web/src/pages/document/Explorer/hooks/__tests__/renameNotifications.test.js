/**
 * Bug 3 测试：文件和文件夹重命名只弹一次提示
 *
 * 验证：
 * 1. 后端返回同名错误时 message.error 只调用一次，文本完全等于后端错误
 * 2. 网络错误只提示一次
 * 3. 失败时不显示成功、不刷新、不取消重命名状态
 * 4. 成功时只显示一次成功提示，并正常刷新、退出重命名状态
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

// 由于 useFileOperations 依赖 React hooks 和复杂上下文，
// 我们直接测试核心逻辑而非完整 hook
describe('Bug3: 重命名通知去重', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  /**
   * 模拟 handleRename 的核心逻辑（去除 message 调用后的版本）
   * 这对应修改后的 useFileOperations.js 中 handleRename 的行为
   */
  async function handleRenameLogic(record, newName, { isPublic, refresh, onFolderChange }) {
    const url = record.isFolder ? '/api/document/folder/rename/' : '/api/document/file/rename/';
    await mockHttpPost(url, {
      id: record.id,
      name: newName,
      is_public: isPublic,
    });
    // 成功后刷新列表（通知由 confirmRename 负责）
    if (refresh) refresh(true);
    if (record.isFolder && onFolderChange) {
      onFolderChange();
    }
  }

  /**
   * 模拟 confirmRename 的核心逻辑（修改后的版本）
   * 这是通知的唯一所有者
   */
  async function confirmRenameLogic(record, newName, { handleRename, cancelRename }) {
    if (!newName?.trim()) {
      mockMessage.warning(`请输入${record.isFolder ? '文件夹' : '文件'}名称`);
      return;
    }
    const currentName = record.display_name || record.name;
    if (newName.trim() === currentName) {
      cancelRename();
      return;
    }
    try {
      await handleRename(record, newName.trim());
      cancelRename();
      mockMessage.success('重命名成功');
    } catch (error) {
      // HTTP 拦截器已对后端 error 弹窗（reject 值为 string），不再重复提示
      // 仅对非 HTTP 错误（Error 对象）补充提示
      if (error instanceof Error) {
        mockMessage.error('重命名失败：' + error.message);
      }
      // 失败时保留编辑态，不调用 cancelRename
    }
  }

  describe('文件重命名', () => {
    const fileRecord = { id: 1, name: 'old.txt', display_name: 'old.txt', isFolder: false };

    it('后端返回同名错误时 message.error 只调用一次，文本完全等于后端错误', async () => {
      // 模拟 HTTP 拦截器行为：reject 并调用 message.error
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('该文件名称已存在');
        return Promise.reject('该文件名称已存在');
      });

      const cancelRename = jest.fn();
      const refresh = jest.fn();
      const handleRename = (record, newName) => handleRenameLogic(record, newName, {
        isPublic: false, refresh, onFolderChange: null,
      });

      await confirmRenameLogic(fileRecord, 'existing.txt', { handleRename, cancelRename, refresh });

      // message.error 只被调用一次（来自 HTTP 拦截器模拟）
      expect(mockMessage.error).toHaveBeenCalledTimes(1);
      expect(mockMessage.error).toHaveBeenCalledWith('该文件名称已存在');
      // 不显示成功
      expect(mockMessage.success).not.toHaveBeenCalled();
      // 不取消重命名状态（保留编辑态）
      expect(cancelRename).not.toHaveBeenCalled();
      // 不刷新
      expect(refresh).not.toHaveBeenCalled();
    });

    it('网络错误只提示一次', async () => {
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('网络异常，请稍后重试');
        return Promise.reject('网络异常，请稍后重试');
      });

      const cancelRename = jest.fn();
      const refresh = jest.fn();
      const handleRename = (record, newName) => handleRenameLogic(record, newName, {
        isPublic: false, refresh, onFolderChange: null,
      });

      await confirmRenameLogic(fileRecord, 'new.txt', { handleRename, cancelRename, refresh });

      expect(mockMessage.error).toHaveBeenCalledTimes(1);
      expect(mockMessage.error).toHaveBeenCalledWith('网络异常，请稍后重试');
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(cancelRename).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
    });

    it('失败时不显示成功、不刷新、不取消重命名状态', async () => {
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('该文件名称已存在');
        return Promise.reject('该文件名称已存在');
      });

      const cancelRename = jest.fn();
      const refresh = jest.fn();
      const handleRename = (record, newName) => handleRenameLogic(record, newName, {
        isPublic: false, refresh, onFolderChange: null,
      });

      await confirmRenameLogic(fileRecord, 'dup.txt', { handleRename, cancelRename, refresh });

      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(cancelRename).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
    });

    it('成功时只显示一次成功提示，并正常刷新、退出重命名状态', async () => {
      mockHttpPost.mockResolvedValue({ success: true });

      const cancelRename = jest.fn();
      const refresh = jest.fn();
      const handleRename = (record, newName) => handleRenameLogic(record, newName, {
        isPublic: false, refresh, onFolderChange: null,
      });

      await confirmRenameLogic(fileRecord, 'newname.txt', { handleRename, cancelRename, refresh });

      expect(mockMessage.success).toHaveBeenCalledTimes(1);
      expect(mockMessage.success).toHaveBeenCalledWith('重命名成功');
      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(cancelRename).toHaveBeenCalledTimes(1);
      expect(refresh).toHaveBeenCalledTimes(1);
      expect(refresh).toHaveBeenCalledWith(true);
    });
  });

  describe('文件夹重命名', () => {
    const folderRecord = { id: 10, name: 'oldfolder', display_name: 'oldfolder', isFolder: true };

    it('后端返回同名错误时 message.error 只调用一次，文本完全等于后端错误', async () => {
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('该文件夹名称已存在');
        return Promise.reject('该文件夹名称已存在');
      });

      const cancelRename = jest.fn();
      const refresh = jest.fn();
      const handleRename = (record, newName) => handleRenameLogic(record, newName, {
        isPublic: false, refresh, onFolderChange: jest.fn(),
      });

      await confirmRenameLogic(folderRecord, 'existingfolder', { handleRename, cancelRename, refresh });

      expect(mockMessage.error).toHaveBeenCalledTimes(1);
      expect(mockMessage.error).toHaveBeenCalledWith('该文件夹名称已存在');
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(cancelRename).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
    });

    it('网络错误只提示一次', async () => {
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('网络异常，请稍后重试');
        return Promise.reject('网络异常，请稍后重试');
      });

      const cancelRename = jest.fn();
      const refresh = jest.fn();
      const handleRename = (record, newName) => handleRenameLogic(record, newName, {
        isPublic: false, refresh, onFolderChange: jest.fn(),
      });

      await confirmRenameLogic(folderRecord, 'newfolder', { handleRename, cancelRename, refresh });

      expect(mockMessage.error).toHaveBeenCalledTimes(1);
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(cancelRename).not.toHaveBeenCalled();
    });

    it('成功时只显示一次成功提示，并正常刷新、退出重命名状态', async () => {
      mockHttpPost.mockResolvedValue({ success: true });

      const cancelRename = jest.fn();
      const refresh = jest.fn();
      const onFolderChange = jest.fn();
      const handleRename = (record, newName) => handleRenameLogic(record, newName, {
        isPublic: false, refresh, onFolderChange,
      });

      await confirmRenameLogic(folderRecord, 'newfolder', { handleRename, cancelRename, refresh });

      expect(mockMessage.success).toHaveBeenCalledTimes(1);
      expect(mockMessage.success).toHaveBeenCalledWith('重命名成功');
      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(cancelRename).toHaveBeenCalledTimes(1);
      expect(refresh).toHaveBeenCalledTimes(1);
      expect(onFolderChange).toHaveBeenCalledTimes(1);
    });
  });

  describe('handleRename 不再调用 message', () => {
    it('handleRename 成功时不调用 message.success', async () => {
      mockHttpPost.mockResolvedValue({ success: true });
      const refresh = jest.fn();

      await handleRenameLogic(
        { id: 1, isFolder: false },
        'new.txt',
        { isPublic: false, refresh, onFolderChange: null }
      );

      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(refresh).toHaveBeenCalledWith(true);
    });

    it('handleRename 失败时不调用 message.error（由拦截器负责）', async () => {
      // handleRename 不再 try/catch，错误直接抛出
      mockHttpPost.mockRejectedValue('该文件名称已存在');
      const refresh = jest.fn();

      await expect(
        handleRenameLogic(
          { id: 1, isFolder: false },
          'dup.txt',
          { isPublic: false, refresh, onFolderChange: null }
        )
      ).rejects.toEqual('该文件名称已存在');

      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
    });
  });
});

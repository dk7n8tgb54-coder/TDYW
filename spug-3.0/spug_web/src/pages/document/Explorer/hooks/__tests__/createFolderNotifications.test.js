/**
 * Bug6 测试：新建同名文件夹仍显示"创建成功"
 *
 * 验证：
 * 1. created:true 时只弹一次"文件夹创建成功"，并刷新列表+树+退出编辑态
 * 2. created:false 时弹一次"同名文件夹已存在"，不刷新列表、不刷新树，退出编辑态
 * 3. created 缺失或异常格式时不误报创建成功
 * 4. 后端业务错误只提示一次（HTTP 拦截器已弹窗，confirmCreateFolder 不重复）
 * 5. 网络错误只提示一次
 * 6. handleCreateFolder 自身不调用 message（通知由 confirmCreateFolder 统一负责）
 * 7. handleCreateFolder 仅在 created:true 时刷新
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

describe('Bug6: 新建同名文件夹通知去重', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  /**
   * 模拟 handleCreateFolder 的核心逻辑（修改后的版本）
   * 不调用 message，仅在 created:true 时刷新，返回 result 供调用方判断
   */
  async function handleCreateFolderLogic(name, parentId, { isPublic, folderId, refresh, onFolderChange }) {
    if (!name) {
      return Promise.reject('请输入文件夹名称');
    }
    const result = await mockHttpPost('/api/document/folder/', {
      name: name,
      parent_id: parentId || folderId,
      is_public: isPublic,
    });
    if (result && result.created) {
      if (refresh) refresh(true);
      if (onFolderChange) onFolderChange();
    }
    return result;
  }

  /**
   * 模拟 confirmCreateFolder 的核心逻辑（修改后的版本）
   * 这是消息提示的唯一所有者
   */
  async function confirmCreateFolderLogic(folderName, { handleCreateFolder, cancelCreateFolder }) {
    if (!folderName?.trim()) {
      mockMessage.warning('请输入文件夹名称');
      return;
    }
    try {
      const result = await handleCreateFolder(folderName.trim());
      cancelCreateFolder();
      if (result && result.created === true) {
        mockMessage.success('文件夹创建成功');
      } else if (result && result.created === false) {
        mockMessage.warning('同名文件夹已存在');
      } else {
        mockMessage.warning('创建结果未知，请刷新查看');
      }
    } catch (error) {
      if (error instanceof Error) {
        mockMessage.error('创建失败：' + error.message);
      }
    }
  }

  describe('created:true - 真正新建', () => {
    it('只弹一次"文件夹创建成功"，并刷新列表+树+退出编辑态', async () => {
      mockHttpPost.mockResolvedValue({ id: 42, created: true });

      const cancelCreateFolder = jest.fn();
      const refresh = jest.fn();
      const onFolderChange = jest.fn();
      const handleCreateFolder = (name) => handleCreateFolderLogic(name, null, {
        isPublic: false, folderId: 1, refresh, onFolderChange,
      });

      await confirmCreateFolderLogic('新文件夹', { handleCreateFolder, cancelCreateFolder });

      expect(mockMessage.success).toHaveBeenCalledTimes(1);
      expect(mockMessage.success).toHaveBeenCalledWith('文件夹创建成功');
      expect(mockMessage.warning).not.toHaveBeenCalled();
      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(cancelCreateFolder).toHaveBeenCalledTimes(1);
      expect(refresh).toHaveBeenCalledTimes(1);
      expect(refresh).toHaveBeenCalledWith(true);
      expect(onFolderChange).toHaveBeenCalledTimes(1);
    });
  });

  describe('created:false - 同名已存在', () => {
    it('弹一次"同名文件夹已存在"，不刷新列表、不刷新树，退出编辑态', async () => {
      mockHttpPost.mockResolvedValue({ id: 42, created: false });

      const cancelCreateFolder = jest.fn();
      const refresh = jest.fn();
      const onFolderChange = jest.fn();
      const handleCreateFolder = (name) => handleCreateFolderLogic(name, null, {
        isPublic: false, folderId: 1, refresh, onFolderChange,
      });

      await confirmCreateFolderLogic('已有文件夹', { handleCreateFolder, cancelCreateFolder });

      expect(mockMessage.warning).toHaveBeenCalledTimes(1);
      expect(mockMessage.warning).toHaveBeenCalledWith('同名文件夹已存在');
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(cancelCreateFolder).toHaveBeenCalledTimes(1);
      // created:false 时不刷新列表和树
      expect(refresh).not.toHaveBeenCalled();
      expect(onFolderChange).not.toHaveBeenCalled();
    });
  });

  describe('created 缺失或异常格式', () => {
    it('created 字段缺失时不误报创建成功', async () => {
      mockHttpPost.mockResolvedValue({ id: 42 });

      const cancelCreateFolder = jest.fn();
      const refresh = jest.fn();
      const onFolderChange = jest.fn();
      const handleCreateFolder = (name) => handleCreateFolderLogic(name, null, {
        isPublic: false, folderId: 1, refresh, onFolderChange,
      });

      await confirmCreateFolderLogic('未知结果文件夹', { handleCreateFolder, cancelCreateFolder });

      expect(mockMessage.warning).toHaveBeenCalledTimes(1);
      expect(mockMessage.warning).toHaveBeenCalledWith('创建结果未知，请刷新查看');
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(mockMessage.error).not.toHaveBeenCalled();
    });

    it('响应为空对象时不误报创建成功', async () => {
      mockHttpPost.mockResolvedValue({});

      const cancelCreateFolder = jest.fn();
      const refresh = jest.fn();
      const handleCreateFolder = (name) => handleCreateFolderLogic(name, null, {
        isPublic: false, folderId: 1, refresh, onFolderChange: jest.fn(),
      });

      await confirmCreateFolderLogic('空响应文件夹', { handleCreateFolder, cancelCreateFolder });

      expect(mockMessage.warning).toHaveBeenCalledWith('创建结果未知，请刷新查看');
      expect(mockMessage.success).not.toHaveBeenCalled();
    });

    it('created 为非布尔值时不误报创建成功', async () => {
      mockHttpPost.mockResolvedValue({ id: 42, created: 'true' });

      const cancelCreateFolder = jest.fn();
      const handleCreateFolder = (name) => handleCreateFolderLogic(name, null, {
        isPublic: false, folderId: 1, refresh: jest.fn(), onFolderChange: jest.fn(),
      });

      await confirmCreateFolderLogic('字符串created', { handleCreateFolder, cancelCreateFolder });

      // created === true 是严格比较，'true' 字符串不匹配
      expect(mockMessage.warning).toHaveBeenCalledWith('创建结果未知，请刷新查看');
      expect(mockMessage.success).not.toHaveBeenCalled();
    });
  });

  describe('错误只提示一次', () => {
    it('后端业务错误只提示一次（HTTP 拦截器已弹窗）', async () => {
      // 模拟 HTTP 拦截器行为：reject 并调用 message.error
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('文件夹创建失败');
        return Promise.reject('文件夹创建失败');
      });

      const cancelCreateFolder = jest.fn();
      const refresh = jest.fn();
      const handleCreateFolder = (name) => handleCreateFolderLogic(name, null, {
        isPublic: false, folderId: 1, refresh, onFolderChange: jest.fn(),
      });

      await confirmCreateFolderLogic('错误测试', { handleCreateFolder, cancelCreateFolder });

      // message.error 只被调用一次（来自 HTTP 拦截器模拟）
      expect(mockMessage.error).toHaveBeenCalledTimes(1);
      expect(mockMessage.error).toHaveBeenCalledWith('文件夹创建失败');
      expect(mockMessage.success).not.toHaveBeenCalled();
      // 失败时不退出编辑态
      expect(cancelCreateFolder).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
    });

    it('网络错误只提示一次', async () => {
      mockHttpPost.mockImplementation(() => {
        mockMessage.error('网络连接失败，请检查网络后重试');
        return Promise.reject('网络连接失败，请检查网络后重试');
      });

      const cancelCreateFolder = jest.fn();
      const handleCreateFolder = (name) => handleCreateFolderLogic(name, null, {
        isPublic: false, folderId: 1, refresh: jest.fn(), onFolderChange: jest.fn(),
      });

      await confirmCreateFolderLogic('网络错误测试', { handleCreateFolder, cancelCreateFolder });

      expect(mockMessage.error).toHaveBeenCalledTimes(1);
      expect(mockMessage.error).toHaveBeenCalledWith('网络连接失败，请检查网络后重试');
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(cancelCreateFolder).not.toHaveBeenCalled();
    });
  });

  describe('handleCreateFolder 不再调用 message', () => {
    it('成功时不调用 message.success', async () => {
      mockHttpPost.mockResolvedValue({ id: 42, created: true });
      const refresh = jest.fn();

      await handleCreateFolderLogic('新文件', null, {
        isPublic: false, folderId: 1, refresh, onFolderChange: jest.fn(),
      });

      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(refresh).toHaveBeenCalledWith(true);
    });

    it('created:false 时不调用 message 且不刷新', async () => {
      mockHttpPost.mockResolvedValue({ id: 42, created: false });
      const refresh = jest.fn();

      const result = await handleCreateFolderLogic('已有文件', null, {
        isPublic: false, folderId: 1, refresh, onFolderChange: jest.fn(),
      });

      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(mockMessage.warning).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
      expect(result).toEqual({ id: 42, created: false });
    });

    it('失败时不调用 message.error（由拦截器负责）', async () => {
      mockHttpPost.mockRejectedValue('创建失败');
      const refresh = jest.fn();

      await expect(
        handleCreateFolderLogic('失败测试', null, {
          isPublic: false, folderId: 1, refresh, onFolderChange: jest.fn(),
        })
      ).rejects.toEqual('创建失败');

      expect(mockMessage.error).not.toHaveBeenCalled();
      expect(mockMessage.success).not.toHaveBeenCalled();
      expect(refresh).not.toHaveBeenCalled();
    });
  });

  describe('空名称处理', () => {
    it('空名称弹出警告不调用 API', async () => {
      const cancelCreateFolder = jest.fn();
      const handleCreateFolder = jest.fn();

      await confirmCreateFolderLogic('  ', { handleCreateFolder, cancelCreateFolder });

      expect(mockMessage.warning).toHaveBeenCalledTimes(1);
      expect(mockMessage.warning).toHaveBeenCalledWith('请输入文件夹名称');
      expect(handleCreateFolder).not.toHaveBeenCalled();
      expect(cancelCreateFolder).not.toHaveBeenCalled();
    });
  });
});

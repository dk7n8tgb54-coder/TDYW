/**
 * 大文件夹下载（异步打包轮询）测试
 *
 * 覆盖 handleFolderDownload 的 probe 分派逻辑：
 * 1. probe返回 sync -> window.open 直接流式下载，不提示打包中
 * 2. probe返回 async+task_id -> 提示打包中并轮询 status，
 *    status=success 后经 anchor 触发 ready 下载（脱离用户手势不被弹窗拦截）
 * 3. status=failed -> 提示失败且不触发下载
 * 4. probe 请求失败 -> 不触发 window.open（错误由 HTTP 拦截器提示一次）
 * 5. probe 请求必须携带 probe:'true'
 */

// --- Mock react hooks：使 hook 可在组件外直接调用 ---
jest.mock('react', () => ({
  ...jest.requireActual('react'),
  useState: (init) => [init, jest.fn()],
  useRef: (init) => ({ current: init }),
  useCallback: (fn) => fn,
}));

// --- Mock antd ---
const mockMessage = {
  info: jest.fn(),
  error: jest.fn(),
  success: jest.fn(),
  warning: jest.fn(),
};
jest.mock('antd', () => ({
  message: mockMessage,
  Modal: { confirm: jest.fn() },
}));

// --- Mock http ---
const mockHttpGet = jest.fn();
jest.mock('libs/http', () => ({
  __esModule: true,
  default: {
    get: mockHttpGet,
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
}));

// --- Mock 党建上下文（直通，不影响 URL 断言）---
jest.mock('libs/systemFolderContext', () => ({
  __esModule: true,
  appendSystemFolderParam: (url) => url,
  withSystemFolderParams: (params) => params,
  PARTY_BUILDING_DOCUMENTS_CODE: 'party_building_documents',
}));

// --- Mock Explorer utils（避免拉起 FileTypeIcon/antd 图标链）---
jest.mock('../../utils', () => ({
  CONSTANTS: {},
  getDeleteTimeout: () => 30000,
}));

const { useFileOperations } = require('../useFileOperations');

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

describe('大文件夹下载：probe 分派与异步打包轮询', () => {
  let windowOpenSpy;
  let anchorClickSpy;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    sessionStorage.setItem('token', 'a'.repeat(32));
    windowOpenSpy = jest.fn();
    window.open = windowOpenSpy;
    anchorClickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
  });

  afterEach(() => {
    jest.useRealTimers();
    anchorClickSpy.mockRestore();
  });

  function buildHook() {
    const { handleFolderDownload } = useFileOperations({
      isPublic: true,
      folderId: null,
      refresh: jest.fn(),
      onFolderChange: jest.fn(),
    });
    return handleFolderDownload;
  }

  const folder = { id: 42, name: '大文件夹', isFolder: true };

  test('probe 返回 sync 时 window.open 流式下载', async () => {
    mockHttpGet.mockResolvedValueOnce({ mode: 'sync' });
    const handleFolderDownload = buildHook();

    handleFolderDownload(folder);
    await flush();

    expect(mockHttpGet).toHaveBeenCalledWith('/api/document/folder/download/', {
      params: expect.objectContaining({ id: 42, probe: 'true' }),
    });
    expect(windowOpenSpy).toHaveBeenCalledTimes(1);
    expect(windowOpenSpy.mock.calls[0][0]).toContain('/api/document/folder/download/?id=42');
    expect(windowOpenSpy.mock.calls[0][0]).toContain('x-token=');
    expect(mockMessage.info).not.toHaveBeenCalled();
  });

  test('probe 返回 async 时轮询打包状态并在完成后触发下载', async () => {
    mockHttpGet
      .mockResolvedValueOnce({ mode: 'async', task_id: 'task-abc' })   // probe
      .mockResolvedValueOnce({ status: 'pending' })                    // 第 1 次轮询
      .mockResolvedValueOnce({ status: 'success', zip_size: 1024 });   // 第 2 次轮询
    const handleFolderDownload = buildHook();

    handleFolderDownload(folder);
    await flush();

    expect(mockMessage.info).toHaveBeenCalledWith(
      '文件夹较大，正在后台打包，完成后将自动开始下载');
    expect(windowOpenSpy).not.toHaveBeenCalled();

    jest.advanceTimersByTime(2000);
    await flush();
    expect(mockHttpGet).toHaveBeenCalledWith('/api/document/folder/download/status/', {
      params: { task_id: 'task-abc' },
      skipErrorNotification: true,
    });
    // 未完成，继续轮询，尚未下载
    expect(anchorClickSpy).not.toHaveBeenCalled();

    jest.advanceTimersByTime(2000);
    await flush();
    // 完成后经 anchor 触发 ready 下载，而不是 window.open
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);
    expect(windowOpenSpy).not.toHaveBeenCalled();
  });

  test('status=failed 时提示失败且不触发下载', async () => {
    mockHttpGet
      .mockResolvedValueOnce({ mode: 'async', task_id: 'task-fail' })
      .mockResolvedValueOnce({ status: 'failed', error: '磁盘空间不足' });
    const handleFolderDownload = buildHook();

    handleFolderDownload(folder);
    await flush();

    jest.advanceTimersByTime(2000);
    await flush();

    expect(mockMessage.error).toHaveBeenCalledWith('磁盘空间不足');
    expect(anchorClickSpy).not.toHaveBeenCalled();
    expect(windowOpenSpy).not.toHaveBeenCalled();
  });

  test('probe 请求失败时不触发下载，也不重复提示', async () => {
    mockHttpGet.mockRejectedValueOnce('文件夹不存在');
    const handleFolderDownload = buildHook();

    handleFolderDownload(folder);
    await flush();

    expect(windowOpenSpy).not.toHaveBeenCalled();
    expect(anchorClickSpy).not.toHaveBeenCalled();
    expect(mockMessage.error).not.toHaveBeenCalled();
    expect(mockMessage.info).not.toHaveBeenCalled();
  });
});

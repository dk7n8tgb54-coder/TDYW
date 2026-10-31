/**
 * exportFile 公共下载工具行为测试（2026-10-31）。
 *
 * 真实代码路径：mock http 层返回（arraybuffer + headers），捕获真实触发
 * 下载的锚点元素并断言其 download 文件名：
 * - 服务端 Content-Disposition（RFC 5987 filename*）优先，中文正确解码；
 * - 服务端未返回文件名时使用调用方 defaultFilename 兜底（Excel 台账
 *   导出兜底名回归点：兜底名必须以 .xlsx 结尾，不得再出现 .excel.xlsx）。
 */
const mockHttp = jest.fn();
jest.mock('../http', () => ({__esModule: true, default: mockHttp}));

describe('exportFile 下载文件名解析', () => {
  let createdAnchors;
  let originalCreateElement;
  let originalCreateObjectURL;
  let originalRevokeObjectURL;

  beforeEach(() => {
    mockHttp.mockReset();
    createdAnchors = [];
    // 捕获 triggerDownload 真实创建并点击的下载锚点（download 属性已反射）
    originalCreateElement = document.createElement.bind(document);
    jest.spyOn(document, 'createElement').mockImplementation(tag => {
      const el = originalCreateElement(tag);
      if (String(tag).toLowerCase() === 'a') createdAnchors.push(el);
      return el;
    });
    originalCreateObjectURL = window.URL.createObjectURL;
    originalRevokeObjectURL = window.URL.revokeObjectURL;
    window.URL.createObjectURL = jest.fn(() => 'blob:mock-url');
    window.URL.revokeObjectURL = jest.fn();
  });

  afterEach(() => {
    jest.restoreAllMocks();
    window.URL.createObjectURL = originalCreateObjectURL;
    window.URL.revokeObjectURL = originalRevokeObjectURL;
  });

  function fakeXlsxBuffer() {
    return new Uint8Array([0x50, 0x4b, 0x03, 0x04]).buffer;
  }

  test('服务端返回 filename* 时下载名用服务端文件名（中文解码）', async () => {
    const {exportFile} = require('../exportFile');
    mockHttp.mockResolvedValue({
      data: fakeXlsxBuffer(),
      headers: {
        'content-type':
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'content-disposition':
          "attachment; filename*=UTF-8''%E7%BB%B4%E6%8A%A4%E5%8F%B0%E8%B4%A6-%E8%8D%89%E7%A8%BF.xlsx",
      },
    });
    await exportFile({
      url: '/api/equipment-lifecycle/excel-ledgers/1/export/excel/',
      method: 'post',
      defaultFilename: 'fallback.xlsx',
    });
    expect(createdAnchors).toHaveLength(1);
    expect(createdAnchors[0].download).toBe('维护台账-草稿.xlsx');
  });

  test('服务端未返回 Content-Disposition 时使用 defaultFilename 兜底', async () => {
    const {exportFile} = require('../exportFile');
    mockHttp.mockResolvedValue({
      data: fakeXlsxBuffer(),
      headers: {
        'content-type':
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      },
    });
    await exportFile({
      url: '/api/equipment-lifecycle/excel-ledgers/1/export/excel/',
      method: 'post',
      defaultFilename: 'channel-草稿.xlsx',
    });
    expect(createdAnchors).toHaveLength(1);
    expect(createdAnchors[0].download).toBe('channel-草稿.xlsx');
    expect(createdAnchors[0].download.endsWith('.xlsx')).toBe(true);
  });
});

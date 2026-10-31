/**
 * Excel 台账导出兜底文件名测试（2026-10-31，真实 store 行为）。
 *
 * 回归点：exportExcel 的兜底文件名曾拼成 `<源文件名>.excel.xlsx`（把
 * 路由格式标识 excel 误当扩展名）。通过真实 ExcelLedgerStore.applyDetail
 * + exportExcel 调用，断言传给公共 exportFile 的 defaultFilename 以
 * .xlsx 结尾（服务端 Content-Disposition 正常时下载名仍以服务端为准，
 * 兜底仅在响应头缺失时生效，见 src/libs/__tests__/exportFile.test.js）。
 */
const mockHttpGet = jest.fn();
const mockExportFile = jest.fn();
jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  exportFile: mockExportFile,
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

const {ExcelLedgerStore} = require('../excelLedgerStore');
const {makeDetail} = require('../testing/fillFixtures');

describe('ExcelLedgerStore 导出兜底文件名', () => {
  beforeEach(() => {
    mockExportFile.mockReset();
    mockHttpGet.mockReset();
  });

  test('exportExcel 兜底文件名取源文件名且以 .xlsx 结尾（不再 .excel.xlsx）', () => {
    const store = new ExcelLedgerStore();
    store.applyDetail(makeDetail());
    store.exportExcel();
    expect(mockExportFile).toHaveBeenCalledTimes(1);
    const options = mockExportFile.mock.calls[0][0];
    expect(options.url).toBe('/api/equipment-lifecycle/excel-ledgers/71/export/excel/');
    expect(options.method).toBe('post');
    expect(options.defaultFilename).toBe('multi-sheet.xlsx');
    expect(options.defaultFilename.endsWith('.xlsx')).toBe(true);
    expect(options.defaultFilename).not.toContain('.excel');
  });

  test('版本缺源文件名时兜底为 维护台账.xlsx', () => {
    const store = new ExcelLedgerStore();
    store.applyDetail(makeDetail({excel: {version: {source_filename: ''}}}));
    store.exportExcel();
    const options = mockExportFile.mock.calls[0][0];
    expect(options.defaultFilename).toBe('维护台账.xlsx');
  });
});

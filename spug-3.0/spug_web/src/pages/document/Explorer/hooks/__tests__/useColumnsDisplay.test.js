/**
 * 文件名列展示优化测试（2026-08-16，列宽方案 2026-08-30 调整为全列固定宽）
 *
 * 覆盖：
 * 1. 文件名列固定宽度 400（可拖动，minWidth 200）；类型/大小/修改时间/创建人
 *    列为固定宽度；搜索模式追加固定宽度路径列
 * 2. 剩余空间由 FileTable 的表尾填充列吸收（见 FileTable.render.test.js）
 * 3. 文件名经 FileNameText 组件渲染（截断提示与复制行为见 FileNameText.test.js）
 * 4. record.display_name 缺失时回退到 name 字段
 */

// --- Mock antd：Tooltip 用字符串标记便于在元素树中断言 ---
const mockMessage = {
  info: jest.fn(),
  error: jest.fn(),
  success: jest.fn(),
  warning: jest.fn(),
};
jest.mock('antd', () => ({
  message: mockMessage,
  Tooltip: 'ANTD_TOOLTIP',
  Input: 'input',
  Tag: 'span',
}));

// --- Mock 图标：CopyOutlined 用字符串标记便于断言 ---
jest.mock('@ant-design/icons', () => ({
  CheckOutlined: 'CHECK_ICON',
  CloseOutlined: 'CLOSE_ICON',
  LoadingOutlined: 'LOADING_ICON',
  FileImageOutlined: 'FILE_IMG_ICON',
  CopyOutlined: 'COPY_ICON',
}));

// --- Mock react：useCallback 直通，使 hook 可在组件外调用 ---
jest.mock('react', () => ({
  ...jest.requireActual('react'),
  useCallback: (fn) => fn,
}));

// --- Mock 复制工具（源码中为 @/utils/common；其余 ../utils 走真实实现）---
const mockCopyToClipboard = jest.fn();
jest.mock('@/utils/common', () => ({
  copyToClipboard: mockCopyToClipboard,
}));

// --- Mock http：PreviewImage 顶层 import libs/http，避免拉起 axios/history 链 ---
jest.mock('libs/http', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), delete: jest.fn(), put: jest.fn() },
}));

const useColumns = require('../useColumns').default;
const FileNameText = require('../../components/FileNameText').default;

/**
 * 调用真实 useColumns 生成列配置
 */
function buildColumns(overrides = {}) {
  const getColumns = useColumns({
    sortOrder: {},
    isSearching: false,
    isPublic: true,
    currentUserId: 1,
    creatingFolder: false,
    tempFolderName: '',
    setTempFolderName: jest.fn(),
    confirmCreateFolder: jest.fn(),
    cancelCreateFolder: jest.fn(),
    renamingRecord: null,
    tempRenameValue: '',
    setTempRenameValue: jest.fn(),
    confirmRename: jest.fn(),
    cancelRename: jest.fn(),
    ...overrides,
  });
  return getColumns();
}

/**
 * 深度遍历 React 元素树，收集满足条件的元素（元素即普通对象，无需 DOM 渲染）
 * 非对象节点（string/boolean/null/undefined）直接终止，避免对 falsy 子节点无限递归
 */
function findAll(node, predicate, acc = []) {
  if (!node || typeof node !== 'object') return acc;
  if (predicate(node)) acc.push(node);
  const children = node.props && node.props.children;
  (Array.isArray(children) ? children : [children]).forEach((child) => findAll(child, predicate, acc));
  return acc;
}

/**
 * 深度收集元素树中的文本节点
 */
function collectText(node, acc = []) {
  if (typeof node === 'string' || typeof node === 'number') {
    acc.push(node);
  } else if (node && typeof node === 'object' && node.props) {
    const children = node.props.children;
    (Array.isArray(children) ? children : [children]).forEach((child) => collectText(child, acc));
  }
  return acc;
}

const flushMicrotasks = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('文件名列宽方案（2026-08-30 全列固定宽）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCopyToClipboard.mockResolvedValue(true);
  });

  it('文件名列固定宽度 400（可拖动，minWidth 200），元数据列使用固定宽度', () => {
    const columns = buildColumns();
    const byKey = Object.fromEntries(columns.map((c) => [c.key, c]));

    expect(columns.map((c) => c.key)).toEqual(
      expect.arrayContaining(['name', 'file_type', 'size', 'created_at', 'created_by'])
    );
    // 全列固定宽模型：文件名列默认 400px，可拖动调整（minWidth 200 防止拖没）
    expect(byKey.name.width).toBe(400);
    expect(byKey.name.minWidth).toBe(200);
    expect(byKey.file_type.width).toBe(130);
    expect(byKey.size.width).toBe(110);
    expect(byKey.created_at.width).toBe(180);
    expect(byKey.created_by.width).toBe(120);
    // 非搜索模式不出现路径列
    expect(byKey.path).toBeUndefined();
  });

  it('搜索模式追加固定宽度路径列', () => {
    const columns = buildColumns({ isSearching: true });
    const byKey = Object.fromEntries(columns.map((c) => [c.key, c]));

    expect(byKey.path.width).toBe(180);
    expect(byKey.name.width).toBe(400);
  });
});

describe('文件名单元格（2026-08-16 交互收敛）', () => {
  const longName = '关于开展2026年无线电管理专项行动的阶段性总结报告（附件3-修订版）.docx';

  function renderNameCell(record, overrides) {
    const nameCol = buildColumns(overrides).find((c) => c.key === 'name');
    return nameCol.render(record.name, record);
  }

  beforeEach(() => {
    jest.clearAllMocks();
    mockCopyToClipboard.mockResolvedValue(true);
  });

  it('文件名经 FileNameText 组件渲染，传入完整 display_name', () => {
    const el = renderNameCell({
      key: 'f1',
      name: longName,
      display_name: longName,
      isFolder: false,
      file_type: 'application/pdf',
    });

    const nodes = findAll(el, (n) => n.type === FileNameText);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].props.name).toBe(longName);
  });

  it('display_name 缺失时回退到 name 字段', () => {
    const el = renderNameCell({
      key: 'f2',
      name: 'fallback-name.txt',
      isFolder: true,
      file_type: null,
    });

    const nodes = findAll(el, (n) => n.type === FileNameText);
    expect(nodes).toHaveLength(1);
    expect(nodes[0].props.name).toBe('fallback-name.txt');
  });

  it('管理员上传的文件保留官方标识 Tag（真实 isCreatedByAdmin 实现）', () => {
    const el = renderNameCell({
      key: 'f3',
      name: 'x.txt',
      created_by: '系统管理员',
      isFolder: false,
      file_type: 'text/plain',
    });
    expect(collectText(el).join('')).toContain('官方');
  });
});

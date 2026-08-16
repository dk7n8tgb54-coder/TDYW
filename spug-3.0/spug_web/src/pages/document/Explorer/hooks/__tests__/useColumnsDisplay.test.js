/**
 * 文件名列展示优化测试（2026-08-16）
 *
 * 覆盖：
 * 1. 文件名列不设固定 width（唯一弹性列，tableLayout="fixed" 下占满剩余宽度）
 * 2. 类型/大小/修改时间/创建人列为固定宽度；搜索模式追加固定宽度路径列
 * 3. 文件名单元格悬停使用 antd Tooltip 展示完整文件名，展示 span 不再挂原生 title
 * 4. Tooltip 内复制按钮：阻止行点击冒泡、复制完整文件名、成功/失败提示
 * 5. record.display_name 缺失时回退到 name 字段
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

describe('文件名列宽方案（2026-08-16）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCopyToClipboard.mockResolvedValue(true);
  });

  it('文件名列不设固定 width，元数据列使用固定宽度', () => {
    const columns = buildColumns();
    const byKey = Object.fromEntries(columns.map((c) => [c.key, c]));

    expect(columns.map((c) => c.key)).toEqual(
      expect.arrayContaining(['name', 'file_type', 'size', 'created_at', 'created_by'])
    );
    // 文件名列为唯一弹性列：不设 width 才能在 fixed 布局下占满剩余空间
    expect(byKey.name.width).toBeUndefined();
    expect(byKey.file_type.width).toBe(130);
    expect(byKey.size.width).toBe(110);
    expect(byKey.created_at.width).toBe(180);
    expect(byKey.created_by.width).toBe(120);
    // 非搜索模式不出现路径列
    expect(byKey.path).toBeUndefined();
  });

  it('搜索模式追加固定宽度路径列，文件名列仍为弹性列', () => {
    const columns = buildColumns({ isSearching: true });
    const byKey = Object.fromEntries(columns.map((c) => [c.key, c]));

    expect(byKey.path.width).toBe(180);
    expect(byKey.name.width).toBeUndefined();
  });
});

describe('文件名 Tooltip 展示与复制（2026-08-16）', () => {
  const longName = '关于开展2026年无线电管理专项行动的阶段性总结报告（附件3-修订版）.docx';

  function renderNameCell(record, overrides) {
    const nameCol = buildColumns(overrides).find((c) => c.key === 'name');
    return nameCol.render(record.name, record);
  }

  beforeEach(() => {
    jest.clearAllMocks();
    mockCopyToClipboard.mockResolvedValue(true);
  });

  it('悬停使用 antd Tooltip 展示完整文件名，展示 span 不再挂原生 title', () => {
    const el = renderNameCell({
      key: 'f1',
      name: longName,
      display_name: longName,
      isFolder: false,
      file_type: 'application/pdf',
    });

    const tooltips = findAll(el, (n) => n.type === 'ANTD_TOOLTIP');
    expect(tooltips).toHaveLength(1);

    // Tooltip 标题内容包含完整文件名（可换行展示）
    expect(collectText(tooltips[0].props.title).join('')).toContain(longName);

    // 展示 span：保留单行省略样式，且不再挂原生 title（避免双重提示）
    const displaySpan = tooltips[0].props.children;
    expect(displaySpan.props.title).toBeUndefined();
    expect(displaySpan.props.style).toMatchObject({
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
    });
    expect(displaySpan.props.children).toBe(longName);
  });

  it('复制按钮：阻止行点击冒泡，复制完整文件名并提示成功', async () => {
    const el = renderNameCell({
      key: 'f2',
      name: longName,
      display_name: longName,
      isFolder: false,
      file_type: 'application/pdf',
    });

    // 复制按钮位于 Tooltip 的 title 内容中（非 children 树）
    const tooltip = findAll(el, (n) => n.type === 'ANTD_TOOLTIP')[0];
    const copyIcons = findAll(tooltip.props.title, (n) => n.type === 'COPY_ICON');
    expect(copyIcons).toHaveLength(1);

    const stopPropagation = jest.fn();
    copyIcons[0].props.onClick({ stopPropagation });
    expect(stopPropagation).toHaveBeenCalled();

    await flushMicrotasks();
    expect(mockCopyToClipboard).toHaveBeenCalledWith(longName);
    expect(mockMessage.success).toHaveBeenCalledWith('文件名已复制');
    expect(mockMessage.error).not.toHaveBeenCalled();
  });

  it('复制失败时提示失败且不弹成功', async () => {
    mockCopyToClipboard.mockResolvedValueOnce(false);
    const el = renderNameCell({
      key: 'f3',
      name: longName,
      display_name: longName,
      isFolder: false,
      file_type: 'application/pdf',
    });

    const tooltip = findAll(el, (n) => n.type === 'ANTD_TOOLTIP')[0];
    const copyIcon = findAll(tooltip.props.title, (n) => n.type === 'COPY_ICON')[0];
    copyIcon.props.onClick({ stopPropagation: jest.fn() });

    await flushMicrotasks();
    expect(mockMessage.error).toHaveBeenCalledWith('复制失败，请手动复制');
    expect(mockMessage.success).not.toHaveBeenCalled();
  });

  it('display_name 缺失时回退到 name 字段', () => {
    const el = renderNameCell({
      key: 'f4',
      name: 'fallback-name.txt',
      isFolder: true,
      file_type: null,
    });

    const tooltip = findAll(el, (n) => n.type === 'ANTD_TOOLTIP')[0];
    expect(collectText(tooltip.props.title).join('')).toContain('fallback-name.txt');
    expect(tooltip.props.children.props.children).toBe('fallback-name.txt');
  });
});

/**
 * 【2026-08-30 新建文件夹即时上树】FolderTree.refreshNodeChildren 行为测试。
 *
 * 背景：新建文件夹后右侧列表立即显示，但左侧文件树此前只能等手动刷新（整树重建）。
 * 修复后 Explorer 的 onFolderChange 会调用 FolderTree.refreshNodeChildren(folderId)
 * 定向刷新对应分支。本测试直接实例化真实 FolderTree 类，验证：
 *   1. 普通模式根目录：新建后刷新 public-root children，新文件夹出现在树中
 *   2. 普通模式子目录：刷新 folder-<id> children；节点原本收起时自动展开
 *   3. 党建锁定模式根目录（folderId 即锁定根 ID）：带 system_folder 参数刷新 system-root
 *   4. 党建锁定模式子目录：刷新 folder-<id> children
 *   5. 节点未在树中渲染（分支从未展开）时不发请求，展开时由 onLoadData 拉最新数据
 *   6. 刷新结果为空时节点变叶子且不自动展开
 *   7. 已展开的节点不重复加入 expandedKeys
 */

const mockHttpGet = jest.fn();
// FolderTree 从 'libs'（index）导入 http，直接 mock 掉 'libs'，
// 避免 libs/index.js -> router -> routes -> 全量页面的导入链拖垮测试加载
jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: jest.fn(),
    delete: jest.fn(),
    put: jest.fn(),
  },
}));

// 不渲染组件，antd 仅需可导入（Tree/Tooltip 在 render 中才被使用）
jest.mock('antd', () => ({
  Tree: () => null,
  Tooltip: ({ children }) => children,
}));

const FolderTree = require('../FolderTree').default;

/**
 * 实例化真实 FolderTree 并绕过 React 挂载：
 * - 手动置 _isMounted（componentDidMount 的职责）
 * - setState 用同步函数式更新替代，便于直接断言 state.data / state.expandedKeys
 */
function createTree(props, initialState = {}) {
  const tree = new FolderTree(props);
  tree._isMounted = true;
  tree.state = { data: [], loading: false, expandedKeys: [], ...initialState };
  tree.setState = (updater) => {
    const patch = typeof updater === 'function' ? updater(tree.state) : updater;
    if (patch) {
      tree.state = { ...tree.state, ...patch };
    }
  };
  return tree;
}

/** 用组件真实方法构建"根 + 已加载子节点"的树数据 */
function buildTreeWithRootChildren(tree, rootKey, folders) {
  const root = tree.buildDualRootTree().concat(tree.buildSingleRootTree())
    .find(n => n.key === rootKey);
  root.children = tree._buildFolderChildren(folders);
  return [root];
}

describe('refreshNodeChildren - 普通模式', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('根目录新建文件夹后：刷新 public-root children，新文件夹出现在树中', async () => {
    const tree = createTree({});
    tree.state.data = buildTreeWithRootChildren(tree, 'public-root', [
      { id: 11, name: '旧目录', parent_id: null, has_children: false },
    ]);
    tree.state.expandedKeys = ['public-root'];

    // 新建"新文件夹"后再刷新：后端返回包含新目录的完整子列表
    mockHttpGet.mockResolvedValueOnce([
      { id: 11, name: '旧目录', parent_id: null, has_children: false },
      { id: 22, name: '新文件夹', parent_id: null, has_children: false },
    ]);

    await tree.refreshNodeChildren(null);

    expect(mockHttpGet).toHaveBeenCalledTimes(1);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/document/folder/', {
      params: { id: null, is_public: true },
      skipErrorNotification: true,
    });

    const root = tree.state.data.find(n => n.key === 'public-root');
    const childKeys = root.children.map(n => n.key);
    expect(childKeys).toContain('folder-11');
    expect(childKeys).toContain('folder-22');
    expect(root.isLeaf).toBe(false);
    // 根已展开，不重复加入
    expect(tree.state.expandedKeys).toEqual(['public-root']);
  });

  test('子目录新建后：刷新该节点 children；节点原本收起时自动展开使新文件夹可见', async () => {
    const tree = createTree({});
    tree.state.data = buildTreeWithRootChildren(tree, 'public-root', [
      { id: 11, name: '工作目录', parent_id: null, has_children: true },
    ]);
    tree.state.expandedKeys = ['public-root']; // folder-11 尚未展开

    mockHttpGet.mockResolvedValueOnce([
      { id: 22, name: '新建子目录', parent_id: 11, has_children: false },
    ]);

    await tree.refreshNodeChildren(11);

    expect(mockHttpGet).toHaveBeenCalledWith('/api/document/folder/', {
      params: { id: 11, is_public: true },
      skipErrorNotification: true,
    });

    const target = tree.state.data[0].children.find(n => n.key === 'folder-11');
    expect(target.children.map(n => n.key)).toEqual(['folder-22']);
    // 自动展开，新建子目录立即可见
    expect(tree.state.expandedKeys).toContain('folder-11');
  });

  test('刷新结果为空：节点变叶子且不自动展开', async () => {
    const tree = createTree({});
    tree.state.data = buildTreeWithRootChildren(tree, 'public-root', [
      { id: 11, name: '工作目录', parent_id: null, has_children: true },
    ]);
    tree.state.expandedKeys = ['public-root'];

    mockHttpGet.mockResolvedValueOnce([]);

    await tree.refreshNodeChildren(11);

    const target = tree.state.data[0].children.find(n => n.key === 'folder-11');
    expect(target.isLeaf).toBe(true);
    expect(target.children).toEqual([]);
    expect(tree.state.expandedKeys).toEqual(['public-root']);
  });

  test('节点未在树中渲染（分支从未展开）时不发请求', async () => {
    const tree = createTree({});
    tree.state.data = buildTreeWithRootChildren(tree, 'public-root', []);
    tree.state.expandedKeys = ['public-root'];

    await tree.refreshNodeChildren(999);

    expect(mockHttpGet).not.toHaveBeenCalled();
  });
});

describe('refreshNodeChildren - 党建锁定模式', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('党建根目录（folderId 即锁定根 ID）：带 system_folder 参数刷新 system-root', async () => {
    const tree = createTree({ lockedRoot: true, rootFolderId: 100, rootFolderName: '党建工作' });
    tree.state.data = buildTreeWithRootChildren(tree, 'system-root', [
      { id: 101, name: '旧党建目录', parent_id: 100, has_children: false },
    ]);
    tree.state.expandedKeys = ['system-root'];

    mockHttpGet.mockResolvedValueOnce([
      { id: 101, name: '旧党建目录', parent_id: 100, has_children: false },
      { id: 201, name: '党建新文件夹', parent_id: 100, has_children: false },
    ]);

    // 党建模式根目录时 navigationStore.currentFolderId 即 lockedRootFolderId
    await tree.refreshNodeChildren(100);

    expect(mockHttpGet).toHaveBeenCalledWith('/api/document/folder/', {
      params: { id: 100, is_public: true, system_folder: 'party_building_documents' },
      skipErrorNotification: true,
    });

    const root = tree.state.data.find(n => n.key === 'system-root');
    expect(root.children.map(n => n.key)).toContain('folder-201');
  });

  test('党建子目录：刷新 folder-<id> children', async () => {
    const tree = createTree({ lockedRoot: true, rootFolderId: 100, rootFolderName: '党建工作' });
    tree.state.data = buildTreeWithRootChildren(tree, 'system-root', [
      { id: 150, name: '支部资料', parent_id: 100, has_children: true },
    ]);
    tree.state.expandedKeys = ['system-root'];

    mockHttpGet.mockResolvedValueOnce([
      { id: 202, name: '新建子目录', parent_id: 150, has_children: false },
    ]);

    await tree.refreshNodeChildren(150);

    expect(mockHttpGet).toHaveBeenCalledWith('/api/document/folder/', {
      params: { id: 150, is_public: true, system_folder: 'party_building_documents' },
      skipErrorNotification: true,
    });

    const target = tree.state.data[0].children.find(n => n.key === 'folder-150');
    expect(target.children.map(n => n.key)).toEqual(['folder-202']);
    expect(tree.state.expandedKeys).toContain('folder-150');
  });

  test('锁定根 ID 未初始化时不发请求、不报错', async () => {
    const tree = createTree({ lockedRoot: true, rootFolderId: null });

    await tree.refreshNodeChildren(null);

    expect(mockHttpGet).not.toHaveBeenCalled();
  });

  test('刷新请求失败时静默降级，不改变树数据', async () => {
    const tree = createTree({ lockedRoot: true, rootFolderId: 100 });
    tree.state.data = buildTreeWithRootChildren(tree, 'system-root', [
      { id: 101, name: '旧党建目录', parent_id: 100, has_children: false },
    ]);
    tree.state.expandedKeys = ['system-root'];
    const dataBefore = tree.state.data;

    mockHttpGet.mockRejectedValueOnce(new Error('network down'));

    await expect(tree.refreshNodeChildren(100)).resolves.toBeUndefined();

    expect(tree.state.data).toBe(dataBefore);
    expect(tree.state.expandedKeys).toEqual(['system-root']);
  });
});

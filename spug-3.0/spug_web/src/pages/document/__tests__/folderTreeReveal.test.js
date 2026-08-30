/**
 * 【2026-08-30 左右同步】右侧导航 → 左侧文件树跟随选中/展开 行为测试。
 *
 * 直接实例化真实 FolderTree（componentDidMount 内建立 currentFolderId reaction）
 * 与真实 NavigationStore（经 _bindNavigationStore 绑定），验证：
 *   1. 右侧进入树中已加载但未展开的子目录 → 树自动展开 + 选中，无额外请求
 *   2. 右侧进入树中不存在的深层目录 → 沿 path 逐级拉取物化 → 展开 + 选中
 *   3. 面包屑/返回到根目录 → 选中公共根
 *   4. 党建锁定模式：初始化选中 system-root；进入子目录（path 剔除锁定根条目）跟随；
 *      goUp 返回党建根 → 重新选中 system-root
 *   5. 点击树节点导航：选中/展开生效且无额外请求（reveal 幂等）
 *   6. 再点同一节点：currentFolderId 不变 → 无 reaction → toggle 收起且选中保持
 *   7. 定位失败（父级 children 中无该目录）→ 安全放弃，选中保持，不崩溃
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

const { NavigationStore, _bindNavigationStore } = require('../stores/navigation');
const FolderTree = require('../FolderTree').default;

let store;
const trees = [];

function createTree(props) {
  const tree = new FolderTree(props);
  tree._isMounted = true;
  tree.state = { data: [], loading: false, expandedKeys: [], selectedKeys: [] };
  // 绕过 React 挂载：setState 用同步函数式更新替代（支持 setState 回调，便于断言）
  tree.setState = (updater, callback) => {
    const patch = typeof updater === 'function' ? updater(tree.state) : updater;
    if (patch) {
      tree.state = { ...tree.state, ...patch };
    }
    if (typeof callback === 'function') callback();
  };
  trees.push(tree);
  return tree;
}

function findNode(data, key) {
  for (const n of data || []) {
    if (n.key === key) return n;
    const hit = findNode(n.children, key);
    if (hit) return hit;
  }
  return null;
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const requestedIds = () => mockHttpGet.mock.calls.map(([, config]) => config.params.id);

beforeEach(() => {
  jest.clearAllMocks();
  store = new NavigationStore();
  _bindNavigationStore(store);
});

afterEach(() => {
  // 手动释放 reaction（不调用 componentWillUnmount：未真实渲染过时
  // mobx-react 的 patched unmount 会输出无害的 render-override 警告）
  trees.splice(0).forEach((tree) => {
    if (tree._navReaction) {
      tree._navReaction();
      tree._navReaction = null;
    }
    tree._isMounted = false;
  });
});

describe('revealFolder - 普通模式右侧导航跟随', () => {
  test('右侧进入树中已加载但未展开的子目录：展开 + 选中，无额外请求', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();
    expect(findNode(tree.state.data, 'folder-11')).toBeTruthy();

    const callsBefore = mockHttpGet.mock.calls.length;
    store.enterFolder(11, 'A');
    await flush();

    expect(tree.state.selectedKeys).toEqual(['folder-11']);
    expect(tree.state.expandedKeys).toContain('folder-11');
    expect(mockHttpGet.mock.calls.length).toBe(callsBefore);
  });

  test('右侧进入树中不存在的深层目录：沿 path 逐级物化 + 展开 + 选中', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();

    // 右侧连续进入 A(11) → B(22)，B 所在分支从未在树中展开
    store.enterFolder(11, 'A');
    await flush();
    mockHttpGet.mockResolvedValueOnce([{ id: 22, name: 'B', parent_id: 11, has_children: false }]);
    store.enterFolder(22, 'B');
    await flush();

    const nodeB = findNode(tree.state.data, 'folder-22');
    expect(nodeB).toBeTruthy();
    expect(findNode(tree.state.data, 'folder-11').children.map((n) => n.key)).toContain('folder-22');
    expect(tree.state.selectedKeys).toEqual(['folder-22']);
    expect(tree.state.expandedKeys).toContain('folder-11');
    expect(tree.state.expandedKeys).toContain('folder-22');
    // 逐级请求：根 children 预加载(id:null) + 物化 B 时拉取 A 的 children(id:11)
    expect(requestedIds()).toEqual([null, 11]);
  });

  test('返回根目录：选中公共根', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();

    store.enterFolder(11, 'A');
    await flush();
    // 等价于点击面包屑根节点（-1 → 回到根目录）
    store.navigateTo(-1);
    await flush();

    expect(store.currentFolderId).toBeNull();
    expect(tree.state.selectedKeys).toEqual(['public-root']);
    expect(tree.state.expandedKeys).toContain('public-root');
  });
});

describe('revealFolder - 党建锁定模式跟随', () => {
  test('初始化选中 system-root；进入子目录跟随；goUp 返回党建根重新选中', async () => {
    mockHttpGet.mockResolvedValue([{ id: 150, name: '支部资料', parent_id: 100, has_children: false }]);
    const tree = createTree({ lockedRoot: true, rootFolderId: 100, rootFolderName: '党建工作' });
    tree.componentDidMount();
    await flush();

    store.initSystemFolder({ code: 'party_building_documents', folderId: 100, name: '党建工作' });
    await flush();
    expect(tree.state.selectedKeys).toEqual(['system-root']);

    store.enterFolder(150, '支部资料');
    await flush();
    expect(tree.state.selectedKeys).toEqual(['folder-150']);
    expect(tree.state.expandedKeys).toContain('folder-150');
    expect(findNode(tree.state.data, 'folder-150')).toBeTruthy();

    store.goUp();
    await flush();
    expect(store.currentFolderId).toBe(100);
    expect(tree.state.selectedKeys).toEqual(['system-root']);

    // 党建模式下所有请求均携带 system_folder
    for (const [, config] of mockHttpGet.mock.calls) {
      expect(config.params.system_folder).toBe('party_building_documents');
    }
  });
});

describe('树自身点击与 reveal 的协同', () => {
  test('点击树节点导航：选中/展开生效且无额外请求（reveal 幂等）', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();

    const callsBefore = mockHttpGet.mock.calls.length;
    tree.handleSelect(null, { node: { key: 'folder-11', folderName: 'A' } });
    await flush();

    expect(store.currentFolderId).toBe(11);
    expect(tree.state.selectedKeys).toEqual(['folder-11']);
    expect(tree.state.expandedKeys).toContain('folder-11');
    // 节点已在树中，reveal 不应产生额外请求
    expect(mockHttpGet.mock.calls.length).toBe(callsBefore);
  });

  test('再点同一节点：currentFolderId 不变 → 无 reaction → toggle 收起且选中保持', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();

    store.enterFolder(11, 'A');
    await flush();
    expect(tree.state.expandedKeys).toContain('folder-11');

    tree.handleSelect(null, { node: { key: 'folder-11', folderName: 'A' } });
    await flush();

    expect(store.currentFolderId).toBe(11);
    expect(tree.state.expandedKeys).not.toContain('folder-11');
    expect(tree.state.selectedKeys).toEqual(['folder-11']);
  });
});

describe('revealFolder 异常场景', () => {
  test('定位目录未出现在父级 children 中：安全放弃，选中保持，不崩溃', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();

    store.enterFolder(11, 'A');
    await flush();
    expect(tree.state.selectedKeys).toEqual(['folder-11']);

    // 右侧进入一个父级 children 中不存在的目录（数据不一致）
    mockHttpGet.mockResolvedValueOnce([]);
    store.enterFolder(99, '不一致目录');
    await expect(flush()).resolves.toBeUndefined();

    expect(tree.state.selectedKeys).toEqual(['folder-11']);
  });
});

describe('根节点固定展开（公共文档/党建工作根不可收起）', () => {
  test('点击已展开的公共根：不收起，选中根并导航到根', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();

    store.enterFolder(11, 'A');
    await flush();
    tree.handleSelect(null, { node: { key: 'public-root' } });
    await flush();

    expect(store.currentFolderId).toBeNull();
    expect(tree.state.selectedKeys).toEqual(['public-root']);
    // 根节点固定展开：点击根不会触发 toggle 收起
    expect(tree.state.expandedKeys).toContain('public-root');
  });

  test('onExpand 收起根被强制保留，收起子目录仍生效', async () => {
    mockHttpGet.mockResolvedValue([{ id: 11, name: 'A', parent_id: null, has_children: true }]);
    const tree = createTree({});
    tree.componentDidMount();
    await flush();

    // 先展开子目录 folder-11
    tree.handleExpand(['public-root', 'folder-11']);
    expect(tree.state.expandedKeys).toEqual(['public-root', 'folder-11']);

    // 用户点击根节点收起箭头：antd 传入的数组不含根 key，强制保留
    tree.handleExpand(['folder-11']);
    expect(tree.state.expandedKeys).toContain('public-root');
    expect(tree.state.expandedKeys).toContain('folder-11');

    // 收起子目录不受影响
    tree.handleExpand(['public-root']);
    expect(tree.state.expandedKeys).toEqual(['public-root']);
  });

  test('党建模式：system-root 不可收起，点击党建根导航到锁定根', async () => {
    mockHttpGet.mockResolvedValue([{ id: 150, name: '支部资料', parent_id: 100, has_children: false }]);
    const tree = createTree({ lockedRoot: true, rootFolderId: 100, rootFolderName: '党建工作' });
    tree.componentDidMount();
    await flush();

    // 尝试收起党建根：强制保留
    tree.handleExpand([]);
    expect(tree.state.expandedKeys).toEqual(['system-root']);

    store.enterFolder(150, '支部资料');
    await flush();
    tree.handleSelect(null, { node: { key: 'system-root' } });
    await flush();

    expect(store.currentFolderId).toBe(100);
    expect(tree.state.selectedKeys).toEqual(['system-root']);
    expect(tree.state.expandedKeys).toContain('system-root');
  });
});

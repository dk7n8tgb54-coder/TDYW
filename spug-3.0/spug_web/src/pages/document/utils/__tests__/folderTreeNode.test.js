/**
 * FolderTree 叶子状态映射纯函数测试。
 *
 * 验证 computeLeafState / resolveCreatorName 的映射逻辑：
 *   - has_children === false → isLeaf:true, children:[]
 *   - has_children === true  → isLeaf:false, children:undefined
 *   - has_children 缺失（旧后端兼容）→ 保守允许展开
 *   - created_by 字符串/对象/null 兼容
 *
 * 以及【2026-08-30 新建文件夹即时上树】的两个纯函数：
 *   - resolveRefreshNodeKey：目录 ID → 需要定向刷新的树节点 key
 *   - applyChildrenToTree：把刷新后的 children 合并回树数据（仅重建受影响分支）
 */
import {
  computeLeafState,
  resolveCreatorName,
  resolveRefreshNodeKey,
  applyChildrenToTree,
} from '../folderTreeNode';

describe('computeLeafState - has_children → isLeaf 映射', () => {
  test('has_children === false 映射为叶子节点', () => {
    const result = computeLeafState(false);
    expect(result.isLeaf).toBe(true);
    expect(result.children).toEqual([]);
  });

  test('has_children === true 映射为可展开节点', () => {
    const result = computeLeafState(true);
    expect(result.isLeaf).toBe(false);
    expect(result.children).toBeUndefined();
  });

  test('has_children === undefined（旧后端）保守允许展开', () => {
    const result = computeLeafState(undefined);
    expect(result.isLeaf).toBe(false);
    expect(result.children).toBeUndefined();
  });

  test('has_children === null（旧后端）保守允许展开', () => {
    const result = computeLeafState(null);
    expect(result.isLeaf).toBe(false);
    expect(result.children).toBeUndefined();
  });

  test('has_children === 0（异常值）保守允许展开', () => {
    // 仅严格匹配 false 才视为叶子，0 不是 false
    const result = computeLeafState(0);
    expect(result.isLeaf).toBe(false);
    expect(result.children).toBeUndefined();
  });
});

describe('resolveCreatorName - 创建人名解析（字符串/对象兼容）', () => {
  test('后端返回字符串（nickname）直接使用', () => {
    expect(resolveCreatorName('张三')).toBe('张三');
  });

  test('后端返回对象时取 nickname', () => {
    expect(resolveCreatorName({ nickname: '李四', username: 'lisi' })).toBe('李四');
  });

  test('后端返回对象无 nickname 时取 username', () => {
    expect(resolveCreatorName({ username: 'wangwu' })).toBe('wangwu');
  });

  test('null 返回 null', () => {
    expect(resolveCreatorName(null)).toBeNull();
  });

  test('undefined 返回 null', () => {
    expect(resolveCreatorName(undefined)).toBeNull();
  });

  test('空对象返回 null', () => {
    expect(resolveCreatorName({})).toBeNull();
  });
});

describe('resolveRefreshNodeKey - 目录结构变化后需要刷新的树节点 key', () => {
  test('普通模式：folderId 为空 → 公共根节点', () => {
    expect(resolveRefreshNodeKey(null, { lockedRoot: false, rootFolderId: null })).toBe('public-root');
    expect(resolveRefreshNodeKey(undefined, {})).toBe('public-root');
  });

  test('普通模式：子目录 → folder-<id>', () => {
    expect(resolveRefreshNodeKey(5, {})).toBe('folder-5');
  });

  test('党建锁定模式：folderId 为空或等于锁定根 ID → system-root', () => {
    // 党建模式根目录时 navigationStore.currentFolderId 即锁定根 ID
    expect(resolveRefreshNodeKey(null, { lockedRoot: true, rootFolderId: 100 })).toBe('system-root');
    expect(resolveRefreshNodeKey(100, { lockedRoot: true, rootFolderId: 100 })).toBe('system-root');
  });

  test('党建锁定模式：子目录 → folder-<id>', () => {
    expect(resolveRefreshNodeKey(150, { lockedRoot: true, rootFolderId: 100 })).toBe('folder-150');
  });

  test('党建锁定模式：锁定根 ID 未初始化时返回 null（无需刷新）', () => {
    expect(resolveRefreshNodeKey(null, { lockedRoot: true, rootFolderId: null })).toBeNull();
  });
});

describe('applyChildrenToTree - 把刷新后的 children 合并回树数据', () => {
  const makeNode = (key, extra = {}) => ({ key, ...extra });

  test('命中目标节点：替换 children 并按数量更新 isLeaf', () => {
    const tree = [makeNode('public-root', { isLeaf: false, children: [] })];
    const built = [{ key: 'folder-1' }, { key: 'folder-2' }];
    const next = applyChildrenToTree(tree, 'public-root', built);
    expect(next[0].children).toBe(built);
    expect(next[0].isLeaf).toBe(false);
  });

  test('刷新后无子目录 → 节点变为叶子', () => {
    const tree = [makeNode('folder-1', { isLeaf: false, children: [{ key: 'folder-2' }] })];
    const next = applyChildrenToTree(tree, 'folder-1', []);
    expect(next[0].isLeaf).toBe(true);
    expect(next[0].children).toEqual([]);
  });

  test('深层节点命中：仅重建根到目标节点的路径，其它分支保持原引用', () => {
    const untouchedBranch = makeNode('folder-9', { isLeaf: true, children: [] });
    const targetOldChild = makeNode('folder-22', { isLeaf: true, children: [] });
    const target = makeNode('folder-11', { isLeaf: false, children: [targetOldChild] });
    const tree = [makeNode('public-root', { isLeaf: false, children: [untouchedBranch, target] })];

    const built = [{ key: 'folder-22' }, { key: 'folder-33' }];
    const next = applyChildrenToTree(tree, 'folder-11', built);

    // 目标节点被替换
    const nextTarget = next[0].children[1];
    expect(nextTarget.key).toBe('folder-11');
    expect(nextTarget.children).toBe(built);
    expect(nextTarget.isLeaf).toBe(false);
    // 未受影响分支保持原引用
    expect(next[0].children[0]).toBe(untouchedBranch);
    // 根节点因路径变化被重建，但仍是新数组包裹
    expect(next[0].key).toBe('public-root');
    expect(next).not.toBe(tree);
  });

  test('key 未命中：原样返回原数组引用（不产生新对象）', () => {
    const tree = [makeNode('public-root', { isLeaf: false, children: [makeNode('folder-1')] })];
    const next = applyChildrenToTree(tree, 'folder-999', [{ key: 'folder-2' }]);
    expect(next).toBe(tree);
  });

  test('非数组输入原样返回', () => {
    expect(applyChildrenToTree(null, 'x', [])).toBeNull();
    expect(applyChildrenToTree(undefined, 'x', [])).toBeUndefined();
  });

  test('builtChildren 非数组时按空数组处理', () => {
    const tree = [makeNode('folder-1', { isLeaf: false, children: undefined })];
    const next = applyChildrenToTree(tree, 'folder-1', null);
    expect(next[0].isLeaf).toBe(true);
    expect(next[0].children).toEqual([]);
  });
});

/**
 * FolderTree 叶子状态映射纯函数测试。
 *
 * 验证 computeLeafState / resolveCreatorName 的映射逻辑：
 *   - has_children === false → isLeaf:true, children:[]
 *   - has_children === true  → isLeaf:false, children:undefined
 *   - has_children 缺失（旧后端兼容）→ 保守允许展开
 *   - created_by 字符串/对象/null 兼容
 */
import { computeLeafState, resolveCreatorName } from '../folderTreeNode';

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

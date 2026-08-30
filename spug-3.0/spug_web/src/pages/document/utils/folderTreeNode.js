/**
 * 文件夹树节点纯函数工具（从 FolderTree 抽出，便于单测且避免装饰器语法在 jest 中报错）。
 */
import { generateKey } from './keyUtils';

/**
 * 根据 has_children 字段计算节点的 isLeaf / children 初始状态（纯函数，可单测）。
 * - has_children === true  → isLeaf: false, children: undefined（允许 loadData 展开）
 * - has_children === false → isLeaf: true,  children: []（叶子，不显示三角但保留槽位）
 * - has_children === undefined（旧后端兼容）→ isLeaf: false, children: undefined（保守允许展开）
 */
export function computeLeafState(has_children) {
  if (has_children === false) {
    return { isLeaf: true, children: [] };
  }
  return { isLeaf: false, children: undefined };
}

/**
 * 解析创建人显示名（兼容后端返回字符串或对象两种格式，纯函数可单测）。
 */
export function resolveCreatorName(created_by) {
  if (!created_by) return null;
  if (typeof created_by === 'string') return created_by;
  return created_by.nickname || created_by.username || null;
}

/**
 * 【2026-08-30 新建文件夹即时上树】解析"目录结构变化后需要定向刷新的树节点 key"
 * （纯函数，可单测）。
 * - 普通模式：folderId 为空 → 公共根节点 'public-root'；其余 → 'folder-<id>'
 * - 党建锁定模式：folderId 为空或等于锁定根 ID → 'system-root'
 *   （党建根目录是真实文件夹，navigationStore 在根目录时 currentFolderId 即锁定根 ID）；
 *   锁定根 ID 未初始化时返回 null（无需刷新）；其余 → 'folder-<id>'
 */
export function resolveRefreshNodeKey(folderId, { lockedRoot = false, rootFolderId = null } = {}) {
  if (lockedRoot) {
    if (!rootFolderId) return null;
    if (folderId == null || folderId === rootFolderId) return 'system-root';
    return generateKey(folderId, 'folder');
  }
  if (folderId == null) return 'public-root';
  return generateKey(folderId, 'folder');
}

/**
 * 把某节点刷新后的 children 合并回树数据（纯函数，可单测）。
 * 递归查找 key 对应节点并替换其 children / isLeaf（children 为空 → 叶子）；
 * 未命中目标节点时原样返回（保持原引用），命中时仅重建受影响分支上的节点，
 * 其余分支保持原引用不变，配合 setState 可避免整树重渲染。
 */
export function applyChildrenToTree(treeData, key, builtChildren) {
  if (!Array.isArray(treeData)) return treeData;
  const children = Array.isArray(builtChildren) ? builtChildren : [];
  let matched = false;
  const updateNode = (node) => {
    if (!node) return node;
    if (node.key === key) {
      matched = true;
      return { ...node, children, isLeaf: children.length === 0 };
    }
    if (Array.isArray(node.children)) {
      const nextChildren = node.children.map(updateNode);
      // 仅当子孙中命中目标节点时才重建该分支，未受影响的分支保持原引用
      if (matched) {
        return { ...node, children: nextChildren };
      }
    }
    return node;
  };
  const nextData = treeData.map(updateNode);
  return matched ? nextData : treeData;
}

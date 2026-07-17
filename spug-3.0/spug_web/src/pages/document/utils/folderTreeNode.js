/**
 * 文件夹树节点纯函数工具（从 FolderTree 抽出，便于单测且避免装饰器语法在 jest 中报错）。
 */

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

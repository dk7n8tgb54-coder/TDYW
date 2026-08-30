/**
 * 文件列表列的响应式列显隐与列宽模型（2026-08-16 引入，2026-08-30 调整）
 *
 * 【2026-08-30 调整】接入列宽拖动（components/resizableColumns）后，所有列
 * （含文件名列）均为固定宽度列，宽度可拖动调整并持久化；剩余空间由表尾
 * 填充列（FileTable 内定义，无宽度）吸收。因此显隐规则从"为弹性文件名列
 * 保留 400px"改为"全部可见列的总宽不超过容器"：
 *   容器放不下时按 创建人 → 大小 → 类型 → 路径 顺序隐藏次要列，
 *   修改时间保留到最后；全部次要列隐藏后仍放不下时，由 FileTable 的
 *   动态 scroll.x（= 可见列总宽）兜底出横向滚动。
 */

export const SELECTION_COLUMN_WIDTH = 48;

// 隐藏顺序：越靠前越次要；列不存在的场景（个人空间无创建人/非搜索无路径）由 filter 自然跳过
export const SECONDARY_COLUMN_HIDE_ORDER = ['created_by', 'size', 'file_type', 'path'];

/**
 * 根据容器宽度计算应显示的列
 * @param {Array} columns - 完整列配置（所有列均带固定 width）
 * @param {number|null} containerWidth - 表格容器宽度（px），空值时返回全部列（首帧/无法测量）
 * @param {number} selectionWidth - 选择列宽度（非多选模式传 0）
 * @returns {Array} 过滤后的列配置
 */
export function resolveVisibleColumns(
  columns,
  containerWidth,
  selectionWidth = SELECTION_COLUMN_WIDTH
) {
  if (!containerWidth || !Array.isArray(columns)) return columns;

  let visible = columns;
  for (const key of SECONDARY_COLUMN_HIDE_ORDER) {
    // 全部可见列的总宽（所有列均为固定宽度列）+ 选择列
    const totalWidth = visible.reduce(
      (sum, col) => sum + (col.width ? col.width : 0),
      selectionWidth
    );
    if (containerWidth >= totalWidth) break;
    visible = visible.filter((col) => col.key !== key);
  }
  return visible;
}

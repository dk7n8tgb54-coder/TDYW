/**
 * 文件列表列的响应式显隐规则（2026-08-16）
 *
 * 目标：文件名列始终保持可读宽度（目标下限约 400px）。
 * 容器宽度不足时按"次要程度"顺序隐藏列，而不是压缩唯一弹性列（文件名）：
 *   创建人 → 大小 → 类型 →（搜索模式的）路径
 * 修改时间保留到最后（重要程度仅次于文件名）；
 * 所有次要列都隐藏后仍不足时，由 FileTable 的 scroll.x 最小总宽兜底出横向滚动。
 */

export const NAME_COLUMN_KEY = 'name';
export const SELECTION_COLUMN_WIDTH = 48;
export const MIN_NAME_COLUMN_WIDTH = 400;

// 隐藏顺序：越靠前越次要；列不存在的场景（个人空间无创建人/非搜索无路径）由 filter 自然跳过
export const SECONDARY_COLUMN_HIDE_ORDER = ['created_by', 'size', 'file_type', 'path'];

/**
 * 根据容器宽度计算应显示的列
 * @param {Array} columns - 完整列配置（文件名列不设 width，其余列带固定 width）
 * @param {number|null} containerWidth - 表格容器宽度（px），空值时返回全部列（首帧/无法测量）
 * @param {number} selectionWidth - 选择列宽度（非多选模式传 0）
 * @param {number} minNameWidth - 文件名列目标最小宽度
 * @returns {Array} 过滤后的列配置
 */
export function resolveVisibleColumns(
  columns,
  containerWidth,
  selectionWidth = SELECTION_COLUMN_WIDTH,
  minNameWidth = MIN_NAME_COLUMN_WIDTH
) {
  if (!containerWidth || !Array.isArray(columns)) return columns;

  let visible = columns;
  for (const key of SECONDARY_COLUMN_HIDE_ORDER) {
    // 除文件名列外的固定列宽度总和（文件名列是唯一不设 width 的弹性列）
    const fixedWidth = visible.reduce(
      (sum, col) => sum + (col.key !== NAME_COLUMN_KEY && col.width ? col.width : 0),
      selectionWidth
    );
    if (containerWidth - fixedWidth >= minNameWidth) break;
    visible = visible.filter((col) => col.key !== key);
  }
  return visible;
}

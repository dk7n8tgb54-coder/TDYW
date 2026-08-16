/**
 * 响应式列显隐规则测试（2026-08-16）
 *
 * 契约：容器变窄时按 创建人 → 大小 → 类型 → 路径 顺序隐藏次要列，
 * 保证文件名列可用宽度 ≥ 400px；修改时间保留到最后；
 * 不存在的列（个人空间无创建人/非搜索无路径）自动跳过且不引起误隐藏。
 */
import {
  resolveVisibleColumns,
  SECONDARY_COLUMN_HIDE_ORDER,
  MIN_NAME_COLUMN_WIDTH,
} from '../columnVisibility';

/** 构造与 useColumns 输出一致的列配置 */
function buildColumns({ isPublic = true, isSearching = false } = {}) {
  const columns = [
    { title: '文件名', key: 'name' },                              // 弹性列，无 width
    ...(isSearching ? [{ title: '路径', key: 'path', width: 180 }] : []),
    { title: '类型', key: 'file_type', width: 130 },
    { title: '大小', key: 'size', width: 110 },
    { title: '修改时间', key: 'created_at', width: 180 },
    ...(isPublic ? [{ title: '创建人', key: 'created_by', width: 120 }] : []),
  ];
  return columns;
}

const keys = (columns) => columns.map((c) => c.key);

describe('resolveVisibleColumns 响应式列显隐', () => {
  it('隐藏顺序与最小文件名宽度常量符合设计', () => {
    expect(SECONDARY_COLUMN_HIDE_ORDER).toEqual(['created_by', 'size', 'file_type', 'path']);
    expect(MIN_NAME_COLUMN_WIDTH).toBe(400);
  });

  it('宽容器（1600px）公共空间：全部列保留', () => {
    expect(keys(resolveVisibleColumns(buildColumns(), 1600)))
      .toEqual(['name', 'file_type', 'size', 'created_at', 'created_by']);
  });

  it('980px 公共空间：仅隐藏创建人（文件名可用 512px）', () => {
    expect(keys(resolveVisibleColumns(buildColumns(), 980)))
      .toEqual(['name', 'file_type', 'size', 'created_at']);
  });

  it('850px 公共空间：隐藏创建人+大小', () => {
    expect(keys(resolveVisibleColumns(buildColumns(), 850)))
      .toEqual(['name', 'file_type', 'created_at']);
  });

  it('700px 公共空间：隐藏创建人+大小+类型，修改时间保留', () => {
    expect(keys(resolveVisibleColumns(buildColumns(), 700)))
      .toEqual(['name', 'created_at']);
  });

  it('个人空间无创建人列：900px 不隐藏任何列（不存在的列不引起误隐藏）', () => {
    expect(keys(resolveVisibleColumns(buildColumns({ isPublic: false }), 900)))
      .toEqual(['name', 'file_type', 'size', 'created_at']);
  });

  it('个人空间 800px：隐藏大小（类型保留）', () => {
    expect(keys(resolveVisibleColumns(buildColumns({ isPublic: false }), 800)))
      .toEqual(['name', 'file_type', 'created_at']);
  });

  it('搜索模式 1000px 公共空间：隐藏创建人+大小，类型与路径保留', () => {
    expect(keys(resolveVisibleColumns(buildColumns({ isSearching: true }), 1000)))
      .toEqual(['name', 'path', 'file_type', 'created_at']);
  });

  it('极窄（500px）公共空间：可隐藏的次要列全部隐藏，仅剩文件名+修改时间', () => {
    expect(keys(resolveVisibleColumns(buildColumns(), 500)))
      .toEqual(['name', 'created_at']);
  });

  it('容器宽度未知（首帧/无 ResizeObserver）：原样返回全部列', () => {
    const columns = buildColumns();
    expect(resolveVisibleColumns(columns, null)).toBe(columns);
  });

  it('非多选模式（无选择列 48px）：900px 公共空间只隐藏创建人', () => {
    expect(keys(resolveVisibleColumns(buildColumns(), 900, 0)))
      .toEqual(['name', 'file_type', 'size', 'created_at']);
  });
});

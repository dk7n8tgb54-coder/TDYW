/**
 * 布局工具与绑定规则前端镜像的单元测试（真实函数执行）。
 * 2026-10-01 随 LayoutTable/uuidv4 自模板导入验证原型迁入 excel 路线。
 */
import {
  buildMergeInfo, bindBlockReason, colLetter, coordName, parseCoord,
} from '../components/LayoutTable';
import {uuidv4} from '../utils';

const SHEET = {
  name: 'Sheet1',
  max_row: 5,
  max_column: 6,
  merged_ranges: ['A2:A3', 'A4:A5'],
  cells: {
    A1: {v: '信道'},
    A2: {v: '第1信道'},
    C2: {s: {border: {top: {style: 'thin'}}}},
  },
};

describe('坐标与合并工具', () => {
  test('parseCoord/coordName/colLetter 双向往返', () => {
    expect(parseCoord('C2')).toEqual({row: 2, col: 3});
    expect(parseCoord('AA10')).toEqual({row: 10, col: 27});
    expect(coordName(2, 3)).toBe('C2');
    expect(colLetter(27)).toBe('AA');
    expect(coordName(parseCoord('AB12').row, parseCoord('AB12').col)).toBe('AB12');
  });

  test('buildMergeInfo 标记锚点与覆盖格', () => {
    const {anchors, covered} = buildMergeInfo(SHEET.merged_ranges);
    expect(anchors['A2']).toEqual({rowSpan: 2, colSpan: 1});
    expect(covered['A3']).toBe('A2');
    expect(covered['B2']).toBeUndefined();
  });

  test('uuidv4 是合法 UUID v4 且不重复', () => {
    const first = uuidv4();
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(uuidv4()).not.toBe(first);
  });
});

describe('绑定规则前端镜像（与服务端校验一致）', () => {
  test('合并覆盖格只能提示绑定锚点', () => {
    expect(bindBlockReason(SHEET, 'A3')).toContain('A2');
  });

  test('有内容的单元格不能绑定', () => {
    expect(bindBlockReason(SHEET, 'A1')).toContain('已有内容');
  });

  test('空白格可绑定', () => {
    expect(bindBlockReason(SHEET, 'C2')).toBeNull();
  });

  test('未选择单元格不产生原因', () => {
    expect(bindBlockReason(SHEET, '')).toBeNull();
  });
});

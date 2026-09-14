/**
 * 图表横轴自适应工具测试
 *
 * buildAxisTicks 按数据点索引均匀抽样约 10 个刻度，并按时间跨度选择
 * 刻度格式（≤24h: HH:mm / ≤72h: MM-DD HH:mm / 更长: MM-DD），
 * 供平台健康与磁盘趋势两个图表的 Axis label.formatter 查表。
 */
import {AXIS_MAX_TICKS, buildAxisTicks, formatAxisTime} from '../chartAxis';

const MINUTE = 60 * 1000;

function minutesAgo(count) {
  const d = new Date();
  d.setSeconds(0, 0);
  return new Date(d.getTime() - count * MINUTE);
}

function range5m(count) {
  // 模拟平台健康 5 分钟窗口的 bucket 时间序列（升序）
  const dates = [];
  for (let i = 0; i < count; i += 1) {
    dates.push(minutesAgo(count - i));
  }
  return dates;
}

describe('formatAxisTime', () => {
  it('输出零填充的 月-日 时:分', () => {
    expect(formatAxisTime(new Date(2026, 8, 3, 7, 5))).toBe('09-03 07:05');
    expect(formatAxisTime(new Date(2026, 11, 31, 23, 59))).toBe('12-31 23:59');
  });
});

describe('buildAxisTicks', () => {
  it('空数据返回空 Map', () => {
    expect(buildAxisTicks([], 24).size).toBe(0);
  });

  it('点数少于刻度上限时每个点都有标签', () => {
    const dates = [minutesAgo(20), minutesAgo(10), minutesAgo(0)];
    const labels = buildAxisTicks(dates, 24);
    expect(labels.size).toBe(3);
    labels.forEach(label => expect(label).toMatch(/^\d{2}:\d{2}$/));
  });

  it(`7 天 5 分钟粒度（2016 点）抽样不超过 ${AXIS_MAX_TICKS} 个刻度且格式为 MM-DD`, () => {
    const labels = buildAxisTicks(range5m(2016), 168);
    expect(labels.size).toBe(AXIS_MAX_TICKS);
    labels.forEach(label => expect(label).toMatch(/^\d{2}-\d{2}$/));
  });

  it('48h 视图刻度带日期前缀（MM-DD HH:mm）', () => {
    const labels = buildAxisTicks(range5m(100), 48);
    expect(labels.size).toBe(AXIS_MAX_TICKS);
    labels.forEach(label => expect(label).toMatch(/^\d{2}-\d{2} \d{2}:\d{2}$/));
  });

  it('6h 视图刻度为 HH:mm 且不超过上限', () => {
    const dates = [];
    for (let i = 0; i < 36; i += 1) dates.push(minutesAgo((36 - i) * 10));
    const labels = buildAxisTicks(dates, 6);
    // 36 点步长 ceil(36/10)=4 → 9 个刻度
    expect(labels.size).toBe(9);
    expect(labels.size).toBeLessThanOrEqual(AXIS_MAX_TICKS);
    labels.forEach(label => expect(label).toMatch(/^\d{2}:\d{2}$/));
  });

  it('返回的 key 与 formatAxisTime 一致，Axis formatter 可直接查表', () => {
    const dates = range5m(3);
    const labels = buildAxisTicks(dates, 24);
    dates.forEach(d => {
      const key = formatAxisTime(d);
      expect(labels.has(key)).toBe(true);
      expect(typeof labels.get(key)).toBe('string');
    });
  });
});

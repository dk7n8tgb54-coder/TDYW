// 图表时间横轴自适应工具：平台健康趋势图与系统告警磁盘趋势图共用。
// 两个图表均为 bizcharts 分类轴：若把每个数据点的完整时间戳都作为标签
// 铺在横轴上，24h 有 288 个点、7 天有 2016 个点，切换时间跨度后横轴
// 依旧是一整排旋转长标签。这里按数据点数均匀抽样约 maxTicks 个刻度，
// 并按时间跨度选择刻度粒度，坐标轴 formatter 对非刻度点返回空串。
const pad2 = n => String(n).padStart(2, '0');

export const AXIS_MAX_TICKS = 10;

// 位置字段 / tooltip 展示格式；分钟精度保证窗口内每点唯一（可作分类轴取值）
export function formatAxisTime(date) {
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function tickLabel(date, spanHours) {
  if (spanHours <= 24) {
    return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
  }
  if (spanHours <= 72) {
    return formatAxisTime(date);
  }
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

/**
 * 按索引均匀抽样生成横轴刻度标签。
 * dates: 每个数据点的时间（升序，与图表数据顺序一致，可按序列分别调用后合并）
 * spanHours: 当前视图的时间跨度（小时），决定刻度显示粒度
 * 返回 Map<formatAxisTime(date), 刻度标签>，供 Axis label.formatter 查表。
 */
export function buildAxisTicks(dates, spanHours, maxTicks = AXIS_MAX_TICKS) {
  const labels = new Map();
  if (!Array.isArray(dates) || dates.length === 0) {
    return labels;
  }
  const step = Math.max(1, Math.ceil(dates.length / maxTicks));
  for (let i = 0; i < dates.length; i += step) {
    labels.set(formatAxisTime(dates[i]), tickLabel(dates[i], spanHours));
  }
  return labels;
}

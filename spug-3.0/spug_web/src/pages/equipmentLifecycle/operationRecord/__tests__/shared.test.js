/**
 * 运行处置记录——持续时间展示格式化契约测试（2026-10-12）。
 * 口径（与后端 duration_seconds 配套，单位秒）：
 * - 无数据（null/undefined，后端对无进展/最新进展早于发生时间置空）→ "-"；
 * - 0 → "0分钟"（差值为零是有效展示值）；
 * - 不足 1 小时 → "35分钟"；不足 1 天 → "2小时15分钟"（整小时省略分钟）；
 * - 跨天 → "1天3小时"（天以上不再展示分钟）。
 */
import {formatDuration, nextStepHint, recoveryDurationSeconds} from '../shared';

describe('formatDuration 持续时间展示', () => {
  it('无数据显示"-"（null/undefined/负值防御）', () => {
    expect(formatDuration(null)).toBe('-');
    expect(formatDuration(undefined)).toBe('-');
    expect(formatDuration(-1)).toBe('-');
  });

  it('差值为零显示"0分钟"', () => {
    expect(formatDuration(0)).toBe('0分钟');
    expect(formatDuration(30)).toBe('0分钟');
  });

  it('不足一小时只显示分钟', () => {
    expect(formatDuration(35 * 60)).toBe('35分钟');
    expect(formatDuration(59 * 60 + 59)).toBe('59分钟');
  });

  it('一小时以上到一天以内显示小时（整小时省略分钟）', () => {
    expect(formatDuration(60 * 60)).toBe('1小时');
    expect(formatDuration(2 * 3600 + 15 * 60)).toBe('2小时15分钟');
    expect(formatDuration(23 * 3600 + 59 * 60)).toBe('23小时59分钟');
  });

  it('跨天显示"天+小时"，不再展示分钟', () => {
    expect(formatDuration(24 * 3600)).toBe('1天');
    expect(formatDuration(27 * 3600)).toBe('1天3小时');
    expect(formatDuration(25 * 3600 + 59 * 60)).toBe('1天1小时');
  });
});

describe('nextStepHint 下一步指引（2026-10-14）', () => {
  it('设备故障：处置中指向结案、已关闭指向归档、已撤销不提示', () => {
    expect(nextStepHint({record_type: 'fault', status: 'handling'}))
      .toContain('确认恢复并结案');
    expect(nextStepHint({record_type: 'fault', status: 'closed'}))
      .toContain('已关闭归档');
    expect(nextStepHint({record_type: 'fault', status: 'cancelled'})).toBeNull();
  });

  it('异常事件：已记录指向开始跟进/认定故障，跟进中指向完成跟进，已完成指向重新跟进', () => {
    expect(nextStepHint({record_type: 'abnormal', status: 'recorded'}))
      .toContain('添加跟进记录');
    expect(nextStepHint({record_type: 'abnormal', status: 'recorded'}))
      .toContain('认定设备故障');
    expect(nextStepHint({record_type: 'abnormal', status: 'following_up'}))
      .toContain('完成跟进');
    expect(nextStepHint({record_type: 'abnormal', status: 'completed'}))
      .toContain('重新跟进');
  });

  it('一般记录：留痕说明；类型未知返回 null', () => {
    expect(nextStepHint({record_type: 'routine', status: 'recorded'}))
      .toContain('不进入故障流程');
    expect(nextStepHint(null)).toBeNull();
    expect(nextStepHint({})).toBeNull();
  });
});

describe('recoveryDurationSeconds 恢复耗时口径（2026-10-14）', () => {
  it('恢复时间 - 发生时间（秒，取整）', () => {
    expect(recoveryDurationSeconds({
      occurred_at: '2026-10-11 08:00:00',
      recovered_at: '2026-10-11 12:00:00',
    })).toBe(4 * 3600);
    expect(recoveryDurationSeconds({
      occurred_at: '2026-10-11 08:00:00',
      recovered_at: '2026-10-12 09:30:00',
    })).toBe((24 + 1.5) * 3600);
  });

  it('时间缺失/恢复早于发生返回 null（不暗示恢复耗时）', () => {
    expect(recoveryDurationSeconds({})).toBeNull();
    expect(recoveryDurationSeconds({
      occurred_at: '2026-10-11 08:00:00', recovered_at: null,
    })).toBeNull();
    expect(recoveryDurationSeconds({
      occurred_at: '2026-10-11 12:00:00',
      recovered_at: '2026-10-11 08:00:00',
    })).toBeNull();
  });
});

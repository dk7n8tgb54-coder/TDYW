import moment from 'moment';
import { buildEventPayload } from '../EventForm';
import { buildInvestigationPayload, buildMeasurementPayload } from '../InvestigationForm';

jest.mock('libs', () => ({
  http: { get: jest.fn(), post: jest.fn(), put: jest.fn() },
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => ({
  AttachmentManager: () => null,
}));

describe('干扰事件表单载荷', () => {
  it('地面场景只写入地面明细并保留公共机号', () => {
    const payload = buildEventPayload({
      datetime: moment('2026-08-01 10:00:00'),
      scene_code: 'ground',
      aircraft_no: 'B-2026',
      ground_location: '3号机位',
      ground_frequency: '118.6',
      ground_equipment: '电源车',
      route: 'should-not-be-sent',
    });

    expect(payload.datetime).toBe('2026-08-01 10:00:00');
    expect(payload.aircraft_no).toBe('B-2026');
    expect(payload.ground_detail).toEqual({
      location: '3号机位', frequency: '118.6', ground_equipment: '电源车', remark: undefined,
    });
    expect(payload.air_detail).toBeUndefined();
    expect(payload.route).toBeUndefined();
  });

  it('跨场景同时提交两类明细', () => {
    const payload = buildEventPayload({
      scene_code: 'cross',
      ground_location: '廊桥',
      ground_frequency: '118.6',
      route: 'HFE-VVO',
      alert_frequency: '118.6',
      alert_altitude: 1200,
      duration: 45,
    });

    expect(payload.ground_detail.location).toBe('廊桥');
    expect(payload.air_detail.route).toBe('HFE-VVO');
    expect(payload.air_detail.alert_altitude).toBe(1200);
  });
});

describe('规律调查和测量载荷', () => {
  it('格式化调查日期并携带初始事件关联', () => {
    const payload = buildInvestigationPayload({
      name: '廊桥干扰专题',
      start_at: moment('2026-08-01 10:00:00'),
      end_at: moment('2026-08-08 10:00:00'),
    }, 7, [1, 2]);

    expect(payload.id).toBe(7);
    expect(payload.event_ids).toEqual([1, 2]);
    expect(payload.start_at).toBe('2026-08-01 10:00:00');
    expect(payload.end_at).toBe('2026-08-08 10:00:00');
  });

  it('格式化频谱测量时间', () => {
    expect(buildMeasurementPayload({
      measured_at: moment('2026-08-08 12:30:00'),
      center_frequency: 118.6,
    })).toEqual({
      measured_at: '2026-08-08 12:30:00',
      center_frequency: 118.6,
    });
  });
});

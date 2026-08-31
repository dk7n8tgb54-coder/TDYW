/**
 * 空中干扰 Form 提交载荷测试
 *
 * 验证：
 * 1. 表单包含任务规定的字段（日期时间/航班号/机型/航线/使用跑道/使用进近程序/
 *    被扰频率/告警高度/告警航段/持续时间/现象/处置方式/原因分析/附件）；
 * 2. 编辑模式提交载荷完整（含 id、日期时间格式化、带单位字段的数值与单位）；
 * 3. 告警高度/持续时间清空时载荷显式携带空串（后端按清除处理）；
 * 4. 新建模式载荷携带 attachment_temp_id；必填校验失败时不发起请求。
 *
 * 环境说明：沿用本仓库惯例使用 ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import moment from 'moment';
import ComForm, { buildAirPayload, ALTITUDE_UNIT_OPTIONS, DURATION_UNIT_OPTIONS } from '../Form';
import S from '../store';
import { http } from 'libs';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => Promise.resolve({})),
    post: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
  hasPermission: () => true,
}));

jest.mock('components', () => ({
  AttachmentManager: () => null,
}));

// jsdom 未实现 matchMedia，antd 弹窗链渲染需要（经典 CRA/antd 测试补丁）
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const EDIT_RECORD = {
  id: 21,
  datetime: '2026-08-02 14:30:00',
  flight_number: 'MU5678',
  aircraft_type: 'B738',
  route: 'HFE-VVO',
  runway: '16',
  approach_procedure: 'ILS',
  alert_form: 'TCAS RA',
  alert_altitude: 1200,
  alert_altitude_unit: 'm',
  alert_segment: '进场下降段',
  duration: 45,
  duration_unit: 's',
  phenomenon: '下降过程出现TCAS RA',
  handling_method: '雷达监控',
  cause_analysis: '',
};

let container = null;

function renderForm() {
  act(() => {
    ReactDOM.render(<ComForm/>, container);
  });
}

async function clickOk() {
  const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary');
  expect(okBtn).toBeTruthy();
  await act(async () => {
    okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {});
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
  S.record = {};
  S.formVisible = false;
});

describe('buildAirPayload 单元行为', () => {
  test('moment 日期格式化到分钟、编辑模式携带 id', () => {
    const payload = buildAirPayload(
      {datetime: moment('2026-08-02 14:30:45'), alert_altitude: 1200, duration: 45}, 7, 'temp-1');
    expect(payload.datetime).toBe('2026-08-02 14:30');
    expect(payload.id).toBe(7);
    expect(payload.alert_altitude).toBe(1200);
    expect(payload.duration).toBe(45);
  });

  test('未填写的高度/持续时间以空串显式提交（清除语义）', () => {
    const payload = buildAirPayload({datetime: moment()}, undefined, 'temp-abc');
    expect(payload.alert_altitude).toBe('');
    expect(payload.duration).toBe('');
    expect(payload.attachment_temp_id).toBe('temp-abc');
  });

  test('已置 null 的高度/持续时间同样以空串提交', () => {
    const payload = buildAirPayload({alert_altitude: null, duration: null}, 8, 't');
    expect(payload.alert_altitude).toBe('');
    expect(payload.duration).toBe('');
  });

  test('单位选项与后端 choices 一致', () => {
    expect(ALTITUDE_UNIT_OPTIONS.map(x => x.value)).toEqual(['m', 'ft']);
    expect(DURATION_UNIT_OPTIONS.map(x => x.value)).toEqual(['s', 'min', 'h']);
  });
});

describe('空中表单字段与提交载荷', () => {
  test('表单包含全部规定字段标签', () => {
    S.record = EDIT_RECORD;
    S.formVisible = true;
    renderForm();
    const text = document.body.textContent;
    for (const label of ['日期时间', '航班号', '机型', '航线', '使用跑道', '使用进近程序',
      '被扰频率', '告警高度', '告警航段', '持续时间', '现象', '处置方式', '原因分析']) {
      expect(text).toContain(label);
    }
  });

  test('编辑模式提交载荷完整（含单位字段）', async () => {
    S.record = EDIT_RECORD;
    S.formVisible = true;
    renderForm();
    await clickOk();
    expect(http.post).toHaveBeenCalledTimes(1);
    const [url, payload] = http.post.mock.calls[0];
    expect(url).toBe('/api/interference/air/');
    expect(payload).toEqual(expect.objectContaining({
      id: 21,
      datetime: '2026-08-02 14:30',
      flight_number: 'MU5678',
      aircraft_type: 'B738',
      route: 'HFE-VVO',
      runway: '16',
      approach_procedure: 'ILS',
      alert_form: 'TCAS RA',
      alert_altitude: 1200,
      alert_altitude_unit: 'm',
      alert_segment: '进场下降段',
      duration: 45,
      duration_unit: 's',
      phenomenon: '下降过程出现TCAS RA',
      handling_method: '雷达监控',
    }));
  });

  test('必填字段缺失时不发起请求', async () => {
    S.record = {};
    S.formVisible = true;
    renderForm();
    await clickOk();
    expect(http.post).not.toHaveBeenCalled();
  });
});

/**
 * 地面干扰记录 Form 提交载荷测试
 *
 * 验证：
 * 1. 表单包含任务规定的字段（日期时间/航班号/机号/机型/位置机位/频率/现象/
 *    处置方式/原因分析/备注/附件）；
 * 2. 编辑模式提交载荷携带 id、格式化日期时间与全部业务字段；
 * 3. 新建模式载荷携带 attachment_temp_id（未保存记录临时附件关联）；
 * 4. 必填校验失败时不发起请求。
 *
 * 环境说明：沿用本仓库惯例使用 ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import moment from 'moment';
import ComForm, { buildBridgePayload } from '../Form';
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
  id: 11,
  datetime: '2026-08-01 10:00:00',
  flight_number: 'CA1234',
  aircraft_no: 'B-2026',
  aircraft_type: 'A320',
  location: 'T2航站楼3号廊桥/12号机位',
  frequency: '118.6',
  phenomenon: '甚高频通信出现杂音',
  handling_method: '通知机务排查',
  cause_analysis: '判断为地面电源车干扰',
  remark: '测试备注',
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
  // 冲刷 validateFields -> http.post 的微任务链
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

describe('buildBridgePayload 单元行为', () => {
  test('moment 日期格式化为 YYYY-MM-DD HH:mm（到分钟）', () => {
    const payload = buildBridgePayload({datetime: moment('2026-08-01 10:00:45')}, 3, 'temp-1');
    expect(payload.datetime).toBe('2026-08-01 10:00');
    expect(payload.id).toBe(3);
    expect(payload.attachment_temp_id).toBeUndefined();
  });

  test('新建模式携带临时附件 ID', () => {
    const payload = buildBridgePayload({}, undefined, 'temp-abc');
    expect(payload.attachment_temp_id).toBe('temp-abc');
    expect(payload.id).toBeUndefined();
  });
});

describe('地面表单字段与提交载荷', () => {
  test('表单包含全部规定字段标签', () => {
    S.record = EDIT_RECORD;
    S.formVisible = true;
    renderForm();
    const text = document.body.textContent;
    for (const label of ['日期时间', '航班号', '机号', '机型', '位置/机位', '频率', '现象',
      '处置方式', '原因分析', '备注']) {
      expect(text).toContain(label);
    }
  });

  test('编辑模式提交载荷完整（含 id 与格式化日期时间）', async () => {
    S.record = EDIT_RECORD;
    S.formVisible = true;
    renderForm();
    await clickOk();
    expect(http.post).toHaveBeenCalledTimes(1);
    const [url, payload] = http.post.mock.calls[0];
    expect(url).toBe('/api/interference/bridge/');
    expect(payload).toEqual(expect.objectContaining({
      id: 11,
      datetime: '2026-08-01 10:00',
      flight_number: 'CA1234',
      aircraft_no: 'B-2026',
      aircraft_type: 'A320',
      location: 'T2航站楼3号廊桥/12号机位',
      frequency: '118.6',
      phenomenon: '甚高频通信出现杂音',
      handling_method: '通知机务排查',
      cause_analysis: '判断为地面电源车干扰',
      remark: '测试备注',
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

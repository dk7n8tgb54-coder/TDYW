/**
 * 巡检单记录列表页测试（今日巡检改造）：
 * 列表展示值班巡检单（值班日/单号/模板/状态/异常数），详情抽屉只读回显
 * 值班人员与四轮检查内容；巡检单不关联系统（页面无系统列/系统选择）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function bodyText() {
  return document.body.textContent.replace(/\s+/g, '');
}

const LIST_ROWS = [
  {id: 5, sheet_no: 'XJ20260924-0001', duty_date: '2026-09-24',
    template: 7, template_name: '机房巡检模板', status: 'submitted',
    status_text: '已提交', version: 3, abnormal_count: 1,
    submitted_at: '2026-09-24 18:30', submitted_by_name: 'admin'},
  {id: 6, sheet_no: 'XJ20260923-0001', duty_date: '2026-09-23',
    template: 7, template_name: '机房巡检模板', status: 'void',
    status_text: '已作废', version: 2, abnormal_count: 0,
    submitted_at: '2026-09-23 18:00', submitted_by_name: 'admin'},
];

const SHEET_DETAIL = {
  id: 5, sheet_no: 'XJ20260924-0001', duty_date: '2026-09-24',
  template: 7, template_name: '机房巡检模板', status: 'submitted',
  status_text: '已提交', version: 3, abnormal_count: 1,
  void_reason: '', voided_at: null, voided_by_name: '',
  persons: [
    {id: 1, user: 3, user_name: 'admin', person_name: '值班员甲'},
    {id: 2, user: null, user_name: '', person_name: '外聘代班（无账号）'},
  ],
  records: [
    {id: 31, sheet: 5, round_no: 'r1', round_text: '当日 11:00',
      template_item: 21, is_temporary: false, client_key: '',
      device_name: '1号收发信机', item_name: '面板指示灯', input_type: 'choice',
      choices: ['正常', '不正常'], is_required: true,
      display_order: 0,
      value_text: '不正常', value_number: null, result: 'abnormal',
      abnormal_desc: '告警灯红色', onsite_action: '已切换备用',
      disposition: {status: 'converted_fault',
        fault: {id: 9, fault_no: 'GZ20260924-0001', status: 'pending'},
        work_order: null}},
    {id: 32, sheet: 5, round_no: 'r2', round_text: '当日 16:00',
      template_item: 22, is_temporary: false, client_key: '',
      device_name: '1号收发信机', item_name: '输出功率读数', input_type: 'text',
      choices: '', is_required: true,
      display_order: 1,
      value_text: '512', value_number: 512, result: 'normal',
      abnormal_desc: '', onsite_action: ''},
    {id: 33, sheet: 5, round_no: 'r3', round_text: '当日 22:00',
      template_item: null, is_temporary: true, client_key: 'tmp-1',
      device_name: '', item_name: '机房温度', input_type: 'text',
      choices: '', is_required: false,
      display_order: 0,
      value_text: '26.5', value_number: 26.5, result: 'normal',
      abnormal_desc: '', onsite_action: ''},
  ],
};

function mockFlow() {
  mockHttpGet.mockImplementation((url) => {
    // 列表：http 拦截器解包后为 {data: rows, total}
    if (/\/inspection-sheets\/\d+\/$/.test(url)) {
      // 单对象响应：拦截器直接 resolve 载荷本体
      return Promise.resolve(SHEET_DETAIL);
    }
    if (url.includes('/inspection-sheets/')) {
      return Promise.resolve({data: LIST_ROWS, total: 2});
    }
    return Promise.resolve({data: {}});
  });
}

async function renderPage() {
  const SheetIndex = require('../SheetIndex').default;
  await act(async () => {
    ReactDOM.render(<SheetIndex/>, container);
  });
  await act(flush);
  await act(flush);
}

describe('巡检单记录列表页', () => {
  it('列表展示值班日/单号/模板/状态/异常数，无系统列', async () => {
    mockFlow();
    await renderPage();
    const text = bodyText();
    expect(text).toContain('XJ20260924-0001');
    expect(text).toContain('XJ20260923-0001');
    expect(text).toContain('机房巡检模板');
    expect(text).toContain('已提交');
    expect(text).toContain('已作废');
    // 异常数红色加粗
    expect(text).toContain('1');
    // 巡检单不关联系统：页面不出现系统列，也不请求系统候选
    expect(text).not.toContain('故障系统');
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    expect(urls.some(u => u.includes('candidate-systems'))).toBe(false);
  });

  it('详情抽屉展示值班人员与四轮回显（异常红色+处置状态）', async () => {
    mockFlow();
    await renderPage();
    const detailBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '详情');
    await act(async () => {
      detailBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    await act(flush);
    const text = bodyText();
    expect(text).toContain('巡检单详情');
    // 值班人员（含手工补录无账号人员）
    expect(text).toContain('值班员甲');
    expect(text).toContain('外聘代班（无账号）');
    // 四轮列头
    expect(text).toContain('当日11:00');
    expect(text).toContain('次日06:30');
    // 记录值与处置状态
    expect(text).toContain('不正常');
    expect(text).toContain('已转故障');
    expect(text).toContain('512');
    // 临时加项（设备名为空归入"临时检查项"）
    expect(text).toContain('临时检查项');
    expect(text).toContain('机房温度');
    // 检查项目为第一列、检查内容第二列（组名不再悬于表上方）
    const headers = Array.from(
      document.querySelectorAll('.ant-drawer table.el-ins-recap-table th'))
      .map(th => th.textContent.trim());
    expect(headers).toEqual(
      ['检查项目', '检查内容', '当日 11:00', '当日 16:00', '当日 22:00', '次日 06:30']);
    expect(text).toContain('1号收发信机');
    // 请求只指向巡检单详情端点
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    expect(urls.some(u => /\/inspection-sheets\/5\/$/.test(u))).toBe(true);
  });
});

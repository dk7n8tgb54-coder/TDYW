/**
 * 故障"撤销登记"改版测试（2026-10-03，自作废改版拆出）。
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 撤销按钮文案为"撤销故障登记"（不再使用"作废"），仅处置中详情提供；
 * - 确认弹窗明确说明操作后果（不删除历史记录/退出有效统计与健康计算/
 *   原因必填）并展示故障编号防误操作；
 * - 撤销原因为空或纯空格被前端拦截（不发请求，不乐观更新）；
 * - 真实提交后等待后端成功才提示并刷新（列表 + 详情重新拉取）；
 * - 列表默认请求不携带已撤销筛选（后端默认排除），状态下拉含"已撤销"
 *   供有权限用户主动查询；已撤销行不显示编辑按钮，状态标签为虚线灰样式。
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
// 注意：组件渲染测试不使用 jest.resetModules()（会导致 React 多副本触发 Invalid hook call）

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const FAULT_DETAIL = {
  id: 11, fault_no: 'GZ20261003-0001',
  system: 7, system_name: '烟台通信系统', system_code: 'SYS-A1',
  system_location: '机房A',
  impact_status: 'fault', impact_status_text: '故障',
  status: 'handling', status_text: '处置中',
  occurred_at: '2026-10-03 08:30', phenomenon: '主用链路频繁丢包',
  reason_analysis: '', recovered_at: null,
  recovery_close_note: '',
  recovered_by_name: '', recovered_confirmed_at: null,
  cancel_reason: '', cancelled_at: null, cancelled_by_name: '',
  registrar_name: '登记员甲',
  created_by_name: 'admin', created_at: '2026-10-03 08:40',
};

const HANDLING_RECORDS = {data: [], total: 0, page: 1, page_size: 100};

async function renderDetail(status, overrides) {
  const store = require('../faultStore').default;
  const FaultDetail = require('../FaultDetail').default;
  const detail = {...FAULT_DETAIL, status, ...(overrides || {})};
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/handling-records')) {
      return Promise.resolve(HANDLING_RECORDS);
    }
    // 详情接口：后端 json_response(详情) 经 http 拦截器解包后 resolve 详情本体
    return Promise.resolve(detail);
  });
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    store.showDetail(detail);
    ReactDOM.render(<FaultDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

function topModal() {
  const modals = document.querySelectorAll('.ant-modal');
  return modals.length ? modals[modals.length - 1] : null;
}

function modalText() {
  const modal = topModal();
  return modal ? modal.textContent.replace(/\s+/g, '') : '';
}

function findButtonByText(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === text);
}

// 弹窗主按钮（antd locale 无关：按主按钮样式定位，与 faultRecoverClose 同法）
function modalPrimaryButton() {
  const footer = topModal() && topModal().querySelector('.ant-modal-footer');
  if (!footer) return null;
  return Array.from(footer.querySelectorAll('button'))
    .find(b => b.className.includes('ant-btn-primary')) || null;
}

async function clickButton(button) {
  await act(async () => {
    button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

async function setTextareaValue(textarea, value) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

describe('撤销故障登记（2026-10-03 作废改版）', () => {
  async function openCancelModal() {
    const store = await renderDetail('handling');
    const cancelButton = findButtonByText('撤销故障登记');
    expect(cancelButton).toBeTruthy();
    await clickButton(cancelButton);
    return store;
  }

  it('按钮文案为"撤销故障登记"，不再出现"作废"字样', async () => {
    await renderDetail('handling');
    expect(findButtonByText('撤销故障登记')).toBeTruthy();
    expect(document.body.textContent).not.toContain('作废');
  });

  it('确认弹窗展示故障编号并说明操作后果（不删历史/退出统计与健康计算/原因必填）', async () => {
    await openCancelModal();
    const text = modalText();
    expect(text).toContain('GZ20261003-0001');
    expect(text).toContain('撤销错误或重复的故障登记');
    expect(text).toContain('不会删除历史记录');
    expect(text).toContain('不再参与有效故障统计和系统健康状态计算');
    expect(text).toContain('撤销原因必须填写');
  });

  it('撤销原因为空或纯空格被拦截，不发请求（不乐观更新）', async () => {
    await openCancelModal();
    // 直接点确定：原因为空
    await clickButton(modalPrimaryButton());
    expect(mockHttpPost).toHaveBeenCalledTimes(0);
    // 仅空格：同样拦截
    const textarea = topModal().querySelector('textarea');
    await setTextareaValue(textarea, '   ');
    await clickButton(modalPrimaryButton());
    expect(mockHttpPost).toHaveBeenCalledTimes(0);
  });

  it('真实提交撤销原因（trim）到 cancel 端点，成功后重新拉取详情与列表', async () => {
    await openCancelModal();
    const textarea = topModal().querySelector('textarea');
    await setTextareaValue(textarea, '  重复登记，需重建正确记录  ');
    const detailCallsBefore = mockHttpGet.mock.calls.filter(
      c => c[0].includes('/faults/11/')).length;
    const listCallsBefore = mockHttpGet.mock.calls.filter(
      c => c[0].endsWith('/faults/')).length;
    mockHttpPost.mockResolvedValue({});
    await clickButton(modalPrimaryButton());
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/cancel/');
    expect(payload.cancel_reason).toBe('重复登记，需重建正确记录');
    // 等待后端真实成功后才重新拉取详情与列表（不乐观更新）
    await act(async () => {await flush();});
    expect(
      mockHttpGet.mock.calls.filter(c => c[0].includes('/faults/11/')).length
    ).toBeGreaterThan(detailCallsBefore);
    expect(
      mockHttpGet.mock.calls.filter(c => c[0].endsWith('/faults/')).length
    ).toBeGreaterThan(listCallsBefore);
  });

  it('已撤销详情展示只读追溯横幅与撤销信息，不提供撤销入口', async () => {
    await renderDetail('cancelled', {
      status_text: '已撤销',
      cancel_reason: '误报',
      cancelled_at: '2026-10-03 09:30',
      cancelled_by_name: 'admin',
    });
    const text = document.body.textContent.replace(/\s+/g, '');
    expect(text).toContain('该登记已撤销，仅供历史追溯');
    expect(text).toContain('撤销原因');
    expect(text).toContain('误报');
    expect(text).toContain('撤销时间');
    expect(text).toContain('撤销人');
    expect(text).toContain('admin');
    // 撤销时间为原始文本（含空格的时间串），用未去空白的正文断言
    expect(document.body.textContent).toContain('2026-10-03 09:30');
    expect(findButtonByText('撤销故障登记')).toBeFalsy();
  });
});

describe('故障列表默认排除已撤销（前端配合后端口径）', () => {
  const LIST_ROWS = [
    {id: 1, fault_no: 'GZ20261003-0001', system_name: '烟台通信系统',
      affects_system_operation: true, impact_status: 'fault',
      status: 'handling', status_text: '处置中',
      occurred_at: '2026-10-03 08:30', phenomenon: '主用链路频繁丢包',
      handling_record_count: 0},
    {id: 2, fault_no: 'GZ20261003-0002', system_name: '烟台通信系统',
      affects_system_operation: false, impact_status: '',
      status: 'cancelled', status_text: '已撤销',
      occurred_at: '2026-10-03 07:30', phenomenon: '重复登记的故障',
      handling_record_count: 0},
  ];

  async function renderIndex(listResponse) {
    const FaultIndex = require('../FaultIndex').default;
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/candidate-systems')) {
        return Promise.resolve({data: []});
      }
      return Promise.resolve(listResponse ||
        {data: [LIST_ROWS[0]], total: 1, page: 1, page_size: 20});
    });
    await act(async () => {
      ReactDOM.render(<FaultIndex location={{search: ''}}/>, container);
    });
    await act(async () => {await flush();});
  }

  it('默认列表请求不携带状态筛选（由后端默认排除已撤销）', async () => {
    await renderIndex();
    const listCalls = mockHttpGet.mock.calls.filter(c => c[0].endsWith('/faults/'));
    expect(listCalls.length).toBeGreaterThan(0);
    const params = listCalls[0][1] || {};
    expect(params.status).toBeUndefined();
  });

  it('状态下拉提供"已撤销"选项（有权限用户可主动查询）', async () => {
    await renderIndex();
    // 状态选择器为页面第二个 Select（故障系统在前）：mousedown 打开下拉
    const selectors = document.querySelectorAll('.ant-select');
    expect(selectors.length).toBeGreaterThanOrEqual(2);
    const statusSelector = selectors[1].querySelector('.ant-select-selector');
    expect(statusSelector).toBeTruthy();
    await act(async () => {
      statusSelector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await act(async () => {await flush();});
    const opened = Array.from(document.querySelectorAll(
      '.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option'))
      .map(n => n.textContent);
    expect(opened).toContain('已撤销');
    expect(opened).toContain('处置中');
    expect(opened).toContain('已关闭');
  });

  it('已撤销行不显示编辑按钮，状态标签为虚线灰（克制区分）', async () => {
    // 显式查询已撤销时后端返回已撤销行（默认列表不会返回，此处验证渲染样式）
    await renderIndex({data: LIST_ROWS, total: 2, page: 1, page_size: 20});
    const text = document.body.textContent.replace(/\s+/g, '');
    expect(text).toContain('GZ20261003-0002');
    expect(text).toContain('已撤销');
    const cancelledRow = Array.from(document.querySelectorAll('tr'))
      .find(tr => tr.textContent.includes('GZ20261003-0002'));
    expect(cancelledRow).toBeTruthy();
    const rowButtons = Array.from(cancelledRow.querySelectorAll('button'))
      .map(b => b.textContent.replace(/\s+/g, ''));
    expect(rowButtons).toContain('详情');
    expect(rowButtons).not.toContain('编辑');
    const statusTag = Array.from(cancelledRow.querySelectorAll('.ant-tag'))
      .find(t => t.textContent.includes('已撤销'));
    expect(statusTag).toBeTruthy();
    expect(statusTag.style.borderStyle).toBe('dashed');
    // 处置中行保留编辑入口
    const handlingRow = Array.from(document.querySelectorAll('tr'))
      .find(tr => tr.textContent.includes('GZ20261003-0001'));
    const handlingButtons = Array.from(handlingRow.querySelectorAll('button'))
      .map(b => b.textContent.replace(/\s+/g, ''));
    expect(handlingButtons).toContain('编辑');
  });
});

/**
 * 运行处置记录——编辑表单提交 payload 契约测试（2026-10-27 D2 修复回归）。
 *
 * 缺陷：编辑弹窗类别 Select allowClear 清除后值为 undefined，JSON 序列化丢键，
 * 后端按"缺键保留原值"处理——用户清空类别静默失效。
 * 修复：非故障记录显式提交 category（清空/未填 = 显式空串，后端清空为未选择；
 * 已有值原样回传）。本测试以真实渲染 + 真实 antd Form 校验路径断言提交载荷：
 * - 编辑异常事件（类别 device，未触碰）→ payload.category === 'device'；
 * - 编辑异常事件（无类别）→ payload.category === ''（显式空串，修复点）；
 * - 编辑设备故障 → payload.category 为 undefined（故障不发类别，后端拒绝类别）。
 * 编辑提交不携带 registrar_name/record_type（后端保留原登记人、类型不可改）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

import RecordForm from '../RecordForm';
import store from '../store';

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const flushPromises = async () => {
  for (let i = 0; i < 6; i++) {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  }
};

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  store.record = {};
  store.formVisible = false;
  store.systems = [{id: 7, name: '测试系统', install_location: '机房X'}];
  store.isSubmitting = false;
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-message, .ant-select-dropdown')
    .forEach(node => node.parentNode && node.parentNode.removeChild(node));
  store.record = {};
  store.formVisible = false;
});

// 编辑态挂载：store.record 带 id + mock 详情回填，点确定提交
async function mountEditAndSubmit(detail) {
  mockHttpGet.mockImplementation((url) => {
    if (typeof url === 'string' && url.endsWith(`/records/${detail.id}/`)) {
      return Promise.resolve(detail);
    }
    return Promise.resolve({data: [], total: 0});
  });
  mockHttpPut.mockResolvedValue({});
  store.record = {id: detail.id, record_type: detail.record_type};
  store.formVisible = true;

  await act(async () => {
    ReactDOM.render(React.createElement(RecordForm), container);
  });
  await act(async () => {
    await flushPromises();
  });
  const okButton = document.querySelector('.ant-modal-footer .ant-btn-primary');
  expect(okButton).toBeTruthy();
  await act(async () => {
    okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flushPromises();
  });
}

describe('RecordForm 编辑提交 payload 契约（D2 修复回归）', () => {
  test('异常事件已有类别未触碰：原值显式回传', async () => {
    await mountEditAndSubmit({
      id: 51, record_type: 'abnormal', status: 'following_up',
      system: 7, occurred_at: '2026-10-11 08:00:00',
      title: '异常事件A', description: '描述A', category: 'device',
    });
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/records/51/');
    expect(payload.category).toBe('device');
    expect(payload.registrar_name).toBeUndefined();
    expect(payload.record_type).toBeUndefined();
  });

  test('异常事件无类别（含清空后 undefined）→ 显式空串提交', async () => {
    await mountEditAndSubmit({
      id: 52, record_type: 'abnormal', status: 'recorded',
      system: 7, occurred_at: '2026-10-11 08:00:00',
      title: '异常事件B', description: '描述B', category: '',
    });
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPut.mock.calls[0];
    // 修复点：清空/未填不再丢键，显式空串让后端"清空为未选择"生效
    expect(payload.category).toBe('');
  });

  test('设备故障编辑不提交类别键（后端对故障拒绝类别）', async () => {
    await mountEditAndSubmit({
      id: 53, record_type: 'fault', status: 'handling',
      system: 7, occurred_at: '2026-10-11 08:00:00',
      title: '设备故障C', description: '描述C', category: '',
      affects_system_operation: false, impact_status: '', fault_level: '',
    });
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPut.mock.calls[0];
    expect(payload.category).toBeUndefined();
    expect(payload.record_type).toBeUndefined();
  });
});

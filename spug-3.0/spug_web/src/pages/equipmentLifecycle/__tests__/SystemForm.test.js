/**
 * 设备全生命周期系统新增/编辑表单测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 编辑模式：回填扩展信息（呼号/安装经纬度/工作频率），PUT 载荷为
 *   结构化聚合格式 {system}，不请求 form-fields（自定义字段已下线）
 * - 新增模式：扩展信息选填，确定走 POST；不含自定义字段入口
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

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
  syncAttachmentCount: jest.fn(),
}));

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
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = jest.fn();
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

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {});
}

async function setInputValue(input, value) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {});
}

function findFormItem(labelText, scope) {
  const root = scope || document.body;
  const items = Array.from(root.querySelectorAll('.ant-form-item'));
  const item = items.find(n => {
    const label = n.querySelector('.ant-form-item-label');
    return label && label.textContent.includes(labelText);
  });
  return item || null;
}

function findButtonByText(text) {
  const normalized = text.replace(/\s/g, '');
  return Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s/g, '') === normalized) || null;
}

const RECORD = {
  id: 5, system_code: 'SYS-001', name: '烟台中心站通信系统',
  system_model: 'HX-100', install_location: '烟台中心站机房A', geo_coordinate: '',
  callsign: 'XZ5792', work_frequency: '438.500MHz',
  system_purpose: '', manufacturer: '某通信设备厂', install_unit: '安装一队',
  use_unit: '运行一科', install_time: '2026-01-01', enable_time: '2026-02-01',
  responsible_user_name: '张三', health_status: 'normal', remark: '',
};

function renderEditForm() {
  const store = require('../store').default;
  const SystemForm = require('../SystemForm').default;
  store.record = RECORD;
  store.formVisible = true;
  act(() => {
    ReactDOM.render(<SystemForm/>, container);
  });
  return store;
}

function renderCreateForm() {
  const store = require('../store').default;
  const SystemForm = require('../SystemForm').default;
  store.record = {};
  store.formVisible = true;
  act(() => {
    ReactDOM.render(<SystemForm/>, container);
  });
  return store;
}

describe('编辑系统（聚合提交）', () => {
  it('扩展信息回填并随固定字段一次提交，PUT 为结构化聚合载荷', async () => {
    renderEditForm();
    await flush();
    // 扩展信息区块与字段
    expect(document.body.textContent).toContain('扩展信息');
    const callsignInput = findFormItem('呼号').querySelector('input');
    const freqInput = findFormItem('工作频率').querySelector('input');
    expect(callsignInput.value).toBe('XZ5792');
    expect(freqInput.value).toBe('438.500MHz');
    expect(findFormItem('安装经纬度')).toBeTruthy();
    // 修改呼号后提交
    await setInputValue(callsignInput, 'XZ0007');
    const saveBtn = findButtonByText('保 存');
    expect(saveBtn).toBeTruthy();
    await click(saveBtn);
    await flush();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/systems/5/');
    // 固定字段在 system 键下；系统编号由后端自动生成，前端不传
    expect(payload.system.system_code).toBeUndefined();
    expect(payload.system.name).toBe('烟台中心站通信系统');
    expect(payload.system.install_time).toBe('2026-01-01');
    // 扩展信息随载荷提交
    expect(payload.system.callsign).toBe('XZ0007');
    expect(payload.system.work_frequency).toBe('438.500MHz');
    // 自定义字段机制已下线：不再有 config_values / custom_fields 键
    expect(payload.config_values).toBeUndefined();
    expect(payload.custom_fields).toBeUndefined();
    expect(payload.components).toBeUndefined();
  });

  it('编辑模式不请求 form-fields，不提供自定义字段入口', async () => {
    renderEditForm();
    await flush();
    expect(mockHttpGet).not.toHaveBeenCalled();
    expect(findButtonByText('添加自定义字段')).toBeNull();
    expect(document.body.textContent).not.toContain('系统自定义字段');
  });

  it('选填字段清空后随载荷提交空串', async () => {
    renderEditForm();
    await flush();
    const callsignInput = findFormItem('呼号').querySelector('input');
    await setInputValue(callsignInput, '');
    await click(findButtonByText('保 存'));
    await flush();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPut.mock.calls[0];
    expect(payload.system.callsign).toBe('');
  });

  it('安装经纬度格式非法时前端拦截，不发请求', async () => {
    renderEditForm();
    await flush();
    const geoInput = findFormItem('安装经纬度').querySelector('input');
    await setInputValue(geoInput, 'abc');
    await click(findButtonByText('保 存'));
    await flush();
    expect(mockHttpPut).not.toHaveBeenCalled();
  });
});

describe('新增系统', () => {
  it('扩展信息字段渲染且不含自定义字段入口', async () => {
    renderCreateForm();
    await flush();
    expect(findFormItem('呼号')).toBeTruthy();
    expect(findFormItem('工作频率')).toBeTruthy();
    expect(findFormItem('安装经纬度')).toBeTruthy();
    expect(findButtonByText('添加自定义字段')).toBeNull();
    expect(document.body.textContent).toContain('扩展信息');
  });
});

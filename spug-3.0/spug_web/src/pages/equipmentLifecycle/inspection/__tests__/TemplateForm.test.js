/**
 * 巡检模板管理测试（今日巡检改造）：
 * 模板 → 设备名称 → 检查内容 两级结构聚合提交；设备名称不关联系统。
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

async function setNativeValue(input, value) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {});
}

function findButtonByText(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === text);
}

describe('巡检模板表单（设备 → 检查内容）', () => {
  it('新增模板：默认一设备一检查内容，聚合提交载荷结构正确', async () => {
    const store = require('../store').default;
    const TemplateForm = require('../TemplateForm').default;
    store.tplRecord = null;
    store.tplFormVisible = true;
    await act(async () => {
      ReactDOM.render(<TemplateForm/>, container);
    });
    await act(flush);
    // 填写模板名称
    const nameInput = document.querySelector('input[id="name"]');
    await setNativeValue(nameInput, '机房值班巡检');
    // 填写设备名称与检查内容
    const deviceInput = Array.from(document.querySelectorAll('input'))
      .find(i => i.placeholder && i.placeholder.includes('不关联系统'));
    await setNativeValue(deviceInput, '1号收发信机');
    const itemInput = Array.from(document.querySelectorAll('input'))
      .find(i => i.placeholder === '检查内容');
    await setNativeValue(itemInput, '面板指示灯');
    // 提交（无 ConfigProvider 时 antd Modal 默认 footer 为 OK）
    const ok = findButtonByText('OK') || findButtonByText('确定');
    mockHttpPost.mockResolvedValue({data: {id: 9}});
    await act(async () => {
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    expect(mockHttpPost).toHaveBeenCalled();
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toContain('/inspection-templates/');
    expect(payload.name).toBe('机房值班巡检');
    expect(payload.devices.length).toBe(1);
    expect(payload.devices[0].device_name).toBe('1号收发信机');
    expect(payload.devices[0].items.length).toBe(1);
    expect(payload.devices[0].items[0].name).toBe('面板指示灯');
    expect(payload.devices[0].items[0].input_type).toBe('choice');
    // 设备名称层不关联系统：载荷中无 system 字段
    expect(payload.devices[0]).not.toHaveProperty('system');
  });

  it('编辑模板回填设备与检查内容，提交走 PUT', async () => {
    const store = require('../store').default;
    const TemplateForm = require('../TemplateForm').default;
    store.tplRecord = {
      id: 7, name: '机房巡检模板', description: '', is_active: true,
      devices: [
        {id: 11, device_name: '1号收发信机', display_order: 0, is_active: true, items: [
          {id: 21, name: '面板指示灯', input_type: 'choice',
            choices: ['正常', '不正常'], is_required: true, display_order: 0},
        ]},
      ],
    };
    store.tplFormVisible = true;
    await act(async () => {
      ReactDOM.render(<TemplateForm/>, container);
    });
    await act(flush);
    // 编辑回填：受控输入断言 value（textContent 不含输入值）
    const deviceInput = Array.from(document.querySelectorAll('input'))
      .find(i => i.placeholder && i.placeholder.includes('不关联系统'));
    expect(deviceInput).toBeTruthy();
    expect(deviceInput.value).toBe('1号收发信机');
    const itemInput = Array.from(document.querySelectorAll('input'))
      .find(i => i.placeholder === '检查内容');
    expect(itemInput.value).toBe('面板指示灯');
    const ok = findButtonByText('OK') || findButtonByText('确定');
    mockHttpPut.mockResolvedValue({data: {id: 7}});
    await act(async () => {
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    expect(mockHttpPut).toHaveBeenCalled();
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toContain('/inspection-templates/7/');
    expect(payload.devices[0].id).toBe(11);
    expect(payload.devices[0].items[0].id).toBe(21);
  });
});

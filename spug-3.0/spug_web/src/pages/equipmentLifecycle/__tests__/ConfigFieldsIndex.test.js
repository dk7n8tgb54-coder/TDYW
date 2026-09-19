/**
 * 设备全生命周期（步骤 3.5）配置字段独立入口页面测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 页面提示"仅管理字段定义"，选择系统后加载系统详情并渲染配置字段管理
 * - 系统候选通过 /systems/ 查询（system.view 权限域），只列可用系统
 * - 选中系统后展示类型模板字段与自定义字段两组定义
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  history: {push: jest.fn()},
  Permission: {isSuper: true},
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

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  mockHttpGet.mockReset();
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const SYSTEMS_PAYLOAD = {
  data: [{id: 5, system_code: 'SYS-001', name: '通信系统', system_type_name: '通信系统'}],
  total: 1,
};

const DETAIL_PAYLOAD = {
  id: 5, system_code: 'SYS-001', name: '通信系统', system_type_name: '通信系统',
  config_fields: [
    {id: 101, scope_type: 'template', field_code: 'frequency', display_name: '工作频率',
      field_type: 'text', is_required: true, is_active: true, display: '438.000MHz'},
    {id: 102, scope_type: 'custom', field_code: 'antenna_h', display_name: '天线高度',
      field_type: 'number', is_required: false, is_active: true, display: '25'},
  ],
};

describe('配置字段独立入口', () => {
  it('选择系统后加载详情并渲染字段定义管理（不录入值）', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/systems/5/')) return Promise.resolve(DETAIL_PAYLOAD);
      return Promise.resolve(SYSTEMS_PAYLOAD);
    });
    // eslint-disable-next-line global-require
    const ConfigFieldsIndex = require('../ConfigFieldsIndex').default;
    await act(async () => {
      ReactDOM.render(<ConfigFieldsIndex/>, container);
    });
    await act(flush);
    const text = document.body.textContent;
    expect(text).toContain('配置字段');
    expect(text).toContain('仅管理字段定义');
    // 通过 antd Select 搜索框选择系统（mousedown 打开下拉并触发候选查询）
    const selector = container.querySelector('.ant-select-selector');
    await act(async () => {
      selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      selector.dispatchEvent(new Event('focus', {bubbles: true}));
      selector.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      selector.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
      .find(o => o.textContent.includes('SYS-001'));
    expect(option).toBeTruthy();
    await act(async () => {
      option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      option.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
      option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(flush);
    // 详情按系统 ID 加载
    expect(mockHttpGet).toHaveBeenCalledWith('/api/equipment-lifecycle/systems/5/');
    const after = document.body.textContent;
    expect(after).toContain('类型模板字段');
    expect(after).toContain('工作频率');
    expect(after).toContain('本系统自定义字段');
    expect(after).toContain('天线高度');
  });
});

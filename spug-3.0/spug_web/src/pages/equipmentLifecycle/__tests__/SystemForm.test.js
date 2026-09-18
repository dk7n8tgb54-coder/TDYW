/**
 * 设备全生命周期（步骤二交互重构）系统新增/编辑表单测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 编辑模式：修改模板字段值后一次提交，PUT 载荷为结构化聚合格式
 *   {system, config_values, components}，只提交发生变化的字段值
 * - 编辑模式：表单内联添加自定义字段后立即出现在当前表单（无需先保存系统），
 *   值随本次编辑一并提交（custom_fields 携带 client_key 与 value）
 * - 新增模式：选择系统类型后自动加载该类型模板字段
 * - 新增模式：切换系统类型时弹出确认提醒，不静默丢弃已填写值
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

async function chooseSelectOption(labelText, optionText) {
  const item = findFormItem(labelText);
  const selector = item.querySelector('.ant-select-selector');
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
  });
  await act(async () => {});
  const option = Array.from(
    document.querySelectorAll('.ant-select-dropdown .ant-select-item-option'))
    .find(o => o.textContent.trim() === optionText);
  expect(option).toBeTruthy();
  await click(option);
}

const RECORD = {
  id: 5, system_code: 'SYS-001', name: '烟台中心站通信系统', system_type: 3,
  system_model: 'HX-100', install_location: '烟台中心站机房A', geo_coordinate: '',
  system_purpose: '', manufacturer: '某通信设备厂', install_unit: '安装一队',
  use_unit: '运行一科', install_time: '2026-01-01 08:00', enable_time: '2026-02-01 09:00',
  responsible_user_name: '张三', health_status: 'normal', remark: '',
};

const FORM_FIELDS_PAYLOAD = {
  data: [
    {id: 101, scope_type: 'template', field_code: 'frequency', display_name: '工作频率',
      field_type: 'text', is_required: true, is_active: true, is_sensitive: false,
      choices: '', choices_parsed: [], number_min: null, number_max: null,
      text_regex: '', help_text: '', default_parsed: ''},
    {id: 102, scope_type: 'custom', field_code: 'antenna_h', display_name: '天线高度',
      field_type: 'number', is_required: false, is_active: true, is_sensitive: false,
      choices: '', choices_parsed: [], number_min: 0, number_max: 100,
      text_regex: '', help_text: '', default_parsed: ''},
  ],
  values: {
    101: {value: '438.000MHz', display: '438.000MHz'},
    102: {value: 25, display: '25'},
  },
  components: [{id: 7, name: '接入交换机', category: '', model_version: 'S5735',
    quantity: 4, purpose: '', asset_sn: '', external_ref: '', remark: '',
    display_order: 0}],
  system: {id: 5, system_code: 'SYS-001', name: '烟台中心站通信系统',
    system_type: 3, system_type_name: '通信系统'},
};

function renderEditForm() {
  const store = require('../store').default;
  const SystemForm = require('../SystemForm').default;
  store.record = RECORD;
  store.formVisible = true;
  mockHttpGet.mockResolvedValue(FORM_FIELDS_PAYLOAD);
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
  store.types = [
    {id: 3, name: '通信系统', is_active: true},
    {id: 4, name: '软件系统', is_active: true},
  ];
  act(() => {
    ReactDOM.render(<SystemForm/>, container);
  });
  return store;
}

describe('编辑系统（聚合提交）', () => {
  it('修改模板字段值后一次提交，PUT 为结构化聚合载荷且只含变化字段', async () => {
    renderEditForm();
    await flush();
    // 模板字段与自定义字段均渲染，且带当前值
    const freqInput = findFormItem('工作频率').querySelector('input');
    expect(freqInput.value).toBe('438.000MHz');
    expect(findFormItem('天线高度')).toBeTruthy();
    // 修改模板字段值
    await setInputValue(freqInput, '439.000MHz');
    // 提交
    const saveBtn = findButtonByText('保 存');
    expect(saveBtn).toBeTruthy();
    await click(saveBtn);
    await flush();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/systems/5/');
    // 固定字段在 system 键下，编号原样回传
    expect(payload.system.system_code).toBe('SYS-001');
    expect(payload.system.name).toBe('烟台中心站通信系统');
    expect(payload.system.install_time).toBe('2026-01-01 08:00');
    // 动态字段值只提交发生变化的
    expect(payload.config_values).toEqual({101: '439.000MHz'});
    expect(payload.custom_fields).toBeUndefined();
    // 组成项全量同步（带已有 id，不含内部键）
    expect(payload.components).toEqual([{
      id: 7, name: '接入交换机', category: '', model_version: 'S5735', quantity: 4,
      purpose: '', asset_sn: '', external_ref: '', remark: '', display_order: 0,
    }]);
  });

  it('编辑时内联添加自定义字段立即出现，值随本次编辑一并提交', async () => {
    renderEditForm();
    await flush();
    // 打开添加自定义字段弹窗
    const addBtn = findButtonByText('添加自定义字段');
    expect(addBtn).toBeTruthy();
    await click(addBtn);
    const defModal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => {
        const header = m.querySelector('.ant-modal-header');
        return header && header.textContent.includes('添加自定义字段');
      });
    expect(defModal).toBeTruthy();
    // 填写字段定义（仅名称，编码由后端生成）
    const nameInput = defModal.querySelector('.ant-modal-body input');
    await setInputValue(nameInput, '天线方位角');
    const confirmBtn = Array.from(defModal.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.textContent.replace(/\s/g, '') === '添加');
    await click(confirmBtn);
    await flush();
    // 新字段立即加入当前表单，无需先保存系统
    const newItem = findFormItem('天线方位角');
    expect(newItem).toBeTruthy();
    expect(document.body.textContent).toContain('本次新增自定义字段');
    // 填写新字段值后提交
    const newInput = newItem.querySelector('input');
    await setInputValue(newInput, '正北 15 度');
    await click(findButtonByText('保 存'));
    await flush();
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPut.mock.calls[0];
    expect(payload.custom_fields).toEqual([{
      client_key: 'temp_1',
      name: '天线方位角',
      field_type: 'text',
      required: false,
      value: '正北 15 度',
      choices: [],
      number_min: null,
      number_max: null,
      text_regex: '',
      help_text: '',
      is_sensitive: false,
      is_exportable: false,
    }]);
  });
});

describe('新增系统（类型模板字段）', () => {
  it('选择系统类型后自动加载该类型模板字段', async () => {
    const store = renderCreateForm();
    mockHttpGet.mockResolvedValue({
      data: [FORM_FIELDS_PAYLOAD.data[0]],
      values: {},
      components: [],
      system: null,
    });
    await chooseSelectOption('系统类型', '通信系统');
    await flush();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/form-fields/', {params: {system_type: 3}});
    expect(document.body.textContent).toContain('类型扩展字段');
    expect(document.body.textContent).toContain('工作频率');
    expect(store.formFields.length).toBe(1);
  });

  it('切换系统类型弹出确认提醒，不静默丢弃已填写值', async () => {
    renderCreateForm();
    mockHttpGet.mockImplementation((url, config) => {
      const systemType = config && config.params ? config.params.system_type : null;
      return Promise.resolve({
        data: [{
          id: systemType === 4 ? 201 : 101,
          scope_type: 'template',
          field_code: systemType === 4 ? 'db_version' : 'frequency',
          display_name: systemType === 4 ? '数据库版本' : '工作频率',
          field_type: 'text', is_required: false, is_active: true, is_sensitive: false,
          choices: '', choices_parsed: [], number_min: null, number_max: null,
          text_regex: '', help_text: '', default_parsed: '',
        }],
        values: {},
        components: [],
        system: null,
      });
    });
    await chooseSelectOption('系统类型', '通信系统');
    await flush();
    // 在模板字段中填写值
    const freqInput = findFormItem('工作频率').querySelector('input');
    await setInputValue(freqInput, '438.000MHz');
    // 切换类型 → 出现确认提醒
    await chooseSelectOption('系统类型', '软件系统');
    expect(document.body.textContent).toContain('更换模板字段');
    expect(document.body.textContent).toContain('确定切换');
    // 确认后加载新类型的模板字段
    const confirmBtn = findButtonByText('确定切换');
    await click(confirmBtn);
    await flush();
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/systems/form-fields/', {params: {system_type: 4}});
    expect(document.body.textContent).toContain('数据库版本');
  });
});

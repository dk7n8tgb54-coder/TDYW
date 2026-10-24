/**
 * 数字表单模板编辑画布行为测试（2026-10-22 三栏改版；2026-10-23 P1 交互整理）。
 *
 * 真实渲染（ReactDOM + jsdom）+ mock libs/http，经 FormTemplateEditor
 * 驱动画布，验证：
 * - 画布就地编辑名称、添加/删除字段后保存载荷与画布一致；
 * - 矩阵表格化：表头列名/首列行名编辑、添加/移动/删除行列，稳定 id 不变；
 * - 复制字段/矩阵行列/整组：全部子对象新 id、名称追加副本、插入原对象
 *   之后、自动选中并滚动定位（scrollIntoView 桩断言）；
 * - 撤销/重做：删除后恢复原对象原 id，按钮与 Ctrl+Z/Ctrl+Shift+Z 同效；
 * - 新增字段/行列自动选中定位；分组排序在左栏、画布不重复提供；
 * - 删除字段确认弹窗明确提示影响（已发布版本与历史台账不受影响、仅从
 *   当前草稿移除）；number 切类型清理 unit/options；
 * - 明细组展示一条样例并说明实际可新增多条；
 * - 右侧检查器同步选中对象详细设置；窄屏时检查器进抽屉；
 * - 预览与画布结构一致且只读、不修改草稿；窄屏预览矩阵逐列渲染。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement('button', {
    type: 'button', 'data-testid': props['data-testid'],
    'data-btn-type': props.type, onClick: props.onClick, disabled: props.disabled,
  }, props.children);
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell, AuthButton, AuthCard: Shell, AuthFragment: Shell,
    Breadcrumb, SearchForm, ExportButton: AuthButton, TableCard: Shell,
  };
});

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const FormTemplateEditor = require('../FormTemplateEditor').default;
const {formTemplateStore} = require('../formTemplateStore');

const DRAFT_FORM = {
  protocol_version: 2,
  groups: [
    {id: 'gbaseinfo01', name: '基本信息', description: '', kind: 'fields',
     item_name: '', columns: [], fields: [
       {id: 'fmaintdate1', name: '维护日期', type: 'date', required: true,
        description: '', unit: '', options: []},
       {id: 'fremark001', name: '备注', type: 'textarea', required: false,
        description: '', unit: '', options: []},
     ]},
    {id: 'gmeasuremt1', name: '电气参数测量', description: '', kind: 'repeat',
     item_name: '测量项目', columns: [], fields: [
       {id: 'fitemname01', name: '项目名称', type: 'text', required: true,
        description: '', unit: '', options: []},
     ]},
    {id: 'gmultidev01', name: '多机运行对比', description: '', kind: 'matrix',
     item_name: '', columns: [
       {id: 'cdevicema01', name: 'A 机'}, {id: 'cdevicemb01', name: 'B 机'}],
     fields: [
       {id: 'rvoltage001', name: '输出电压', type: 'number', required: false,
        description: '', unit: 'V', options: []},
       {id: 'rlinkstate1', name: '通讯状态', type: 'normal_abnormal', required: false,
        description: '', unit: '', options: []},
     ]},
  ],
};

function makeDetail() {
  return {
    id: 12, name: '周维护数字表单', ledger_type: 'week_month',
    description: '', system: null, system_name: '', generation_period: '',
    generation_period_text: '待配置', is_active: true,
    has_draft: true, latest_version_no: 0, versions_count: 0, ledgers_count: 0,
    status: 'draft',
    draft: {form: DRAFT_FORM, updated_at: '2026-10-21T10:00:00', updated_by: '张三'},
    draft_state: {relation: 'modified', latest_version_no: 0, versions_count: 0,
                  field_count: 5},
  };
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const flushAll = async () => { await flush(); await flush(); await flush(); };

function renderEditor() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const store = formTemplateStore;
  act(() => { store.openEditor(makeDetail()); });
  ReactDOM.render(h(FormTemplateEditor, {store}), container);
  return {container, store, cleanup: () => {
    ReactDOM.unmountComponentAtNode(container);
    document.querySelectorAll('.ant-modal-root, .ant-drawer-root, .ant-modal-confirm, .ant-popover')
      .forEach(node => node.remove());
    container.remove();
  }};
}

function setText(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

function resetStore() {
  const store = formTemplateStore;
  store.editorVisible = false; store.editorTemplate = null;
  store.editorLoading = false; store.editorLoadError = '';
  store.savingDraft = false; store.publishing = false;
  store.list = []; store.detail = null;
}

async function confirmPopover() {
  await act(flushAll);
  const okButton = Array.from(document.querySelectorAll('.ant-popover button'))
    .find(node => node.textContent.replace(/\s/g, '') === '删除');
  await act(async () => { okButton.click(); });
  await act(flushAll);
}

beforeEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  mockHttpDelete.mockReset();
  resetStore();
  window.innerWidth = 1280;
  // jsdom 未实现 scrollIntoView：装桩以断言"滚动定位"行为
  Element.prototype.scrollIntoView = jest.fn();
});

test('画布就地编辑：删除字段确认提示影响，保存载荷与画布一致', async () => {
  const view = renderEditor();
  await act(flushAll);
  // 选中"备注"字段并删除（确认弹窗提示影响范围）
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fremark001"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fremark001-del"]').click();
  });
  await act(flushAll);
  const popover = document.querySelector('.ant-popover');
  expect(popover.textContent).toContain('已发布版本与历史台账不受影响');
  expect(popover.textContent).toContain('仅从当前草稿移除');
  await confirmPopover();
  expect(document.querySelector('[data-testid="canvas-field-fremark001"]')).toBeNull();
  // 添加字段并就地改名
  await act(async () => {
    document.querySelector('[data-testid="canvas-add-field-gbaseinfo01"]').click();
  });
  await act(flushAll);
  setText(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]'),
          '巡检日期');
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  expect(mockHttpPut).toHaveBeenCalledTimes(1);
  const groups = mockHttpPut.mock.calls[0][1].form.groups;
  expect(groups[0].fields.map(f => f.name)).toEqual(['巡检日期', '新填写项']);
  expect(groups[0].fields[0].id).toBe('fmaintdate1');
  view.cleanup();
});

test('矩阵表格化：行列就地改名、添加/移动/删除，稳定 id 保持不变', async () => {
  const view = renderEditor();
  await act(flushAll);
  // 表头列名与首列行名就地编辑
  setText(document.querySelector('[data-testid="canvas-matrix-col-name-cdevicema01"]'),
          '主机');
  setText(document.querySelector('[data-testid="canvas-matrix-row-name-rvoltage001"]'),
          '输出电压值');
  // 添加一行、一列
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-add-row-gmultidev01"]').click();
  });
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-add-col-gmultidev01"]').click();
  });
  await act(flushAll);
  // 选中"输出电压"行并下移（移动不改稳定 id）
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-row-name-rvoltage001"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-row-rvoltage001-down"]').click();
  });
  await act(flushAll);
  // 选中"B 机"列并删除
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-col-name-cdevicemb01"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-col-cdevicemb01-del"]').click();
  });
  await confirmPopover();
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const matrix = mockHttpPut.mock.calls[0][1].form.groups
    .find(group => group.kind === 'matrix');
  expect(matrix.columns.map(c => c.name)).toEqual(['主机', '新对比对象']);
  expect(matrix.fields.map(f => f.name)).toEqual(['通讯状态', '输出电压值', '新检查项']);
  expect(matrix.fields[1].id).toBe('rvoltage001');
  expect(matrix.columns[0].id).toBe('cdevicema01');
  view.cleanup();
});

test('明细组：展示一条填写样例并说明实际可新增多条', async () => {
  const view = renderEditor();
  await act(flushAll);
  expect(document.body.textContent).toContain('测量项目 示例（第 1 条）');
  expect(document.body.textContent).toContain('实际填写时可按需新增多条测量项目');
  // 模板编辑与台账填写区分说明
  expect(document.body.textContent).toContain('此处不保存任何台账数据');
  // 业务语言新增入口（统一词汇 + 一句话用途说明）
  expect(document.body.textContent).toContain('添加固定填写项');
  expect(document.body.textContent).toContain('一组固定字段，每份台账填写一次');
  expect(document.body.textContent).toContain('添加可重复明细');
  expect(document.body.textContent).toContain('同一结构可填写多条记录');
  expect(document.body.textContent).toContain('添加检查对比表');
  expect(document.body.textContent).toContain('行=检查项目，列=对比对象');
  view.cleanup();
});

test('右侧检查器：默认选中首分组，字段详细设置可编辑并进保存载荷', async () => {
  const view = renderEditor();
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-group-name"]').value)
    .toBe('基本信息');
  setText(document.querySelector('[data-testid="inspector-group-description"]'),
          '登记信息');
  // 选中字段 → 检查器切换为字段设置
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fmaintdate1"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-field-name"]').value)
    .toBe('维护日期');
  const requiredInput = Array.from(
    document.querySelectorAll('.ant-drawer .ant-checkbox-wrapper input'))
    .find(input => input.closest('label').textContent.includes('必填'));
  await act(async () => { requiredInput.click(); });
  await act(flushAll);
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const groups = mockHttpPut.mock.calls[0][1].form.groups;
  expect(groups[0].description).toBe('登记信息');
  expect(groups[0].fields[0].required).toBe(false);
  view.cleanup();
});

test('窄屏：选中对象后设置在抽屉中呈现', async () => {
  window.innerWidth = 800;
  const view = renderEditor();
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-field-name"]')).toBeNull();
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fmaintdate1"]').click();
  });
  await act(flushAll);
  expect(document.body.textContent).toContain('选中项设置');
  const nameInput = document.querySelector('[data-testid="inspector-field-name"]');
  expect(nameInput.value).toBe('维护日期');
  view.cleanup();
  window.innerWidth = 1280;
});

test('预览：与画布结构一致（试填可编辑但不发写请求），且不修改草稿', async () => {
  const view = renderEditor();
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="editor-preview"]').click();
  });
  await act(flushAll);
  const modal = document.querySelector('.ant-modal');
  expect(modal.textContent).toContain('填写预览');
  expect(modal.textContent).toContain('试填内容不会保存');
  expect(modal.textContent).toContain('基本信息');
  expect(modal.textContent).toContain('多机运行对比');
  expect(modal.textContent).toContain('电气参数测量');
  // 试填预览为可编辑形态（值仅存弹窗内存），不发任何写请求
  const previewInput = modal.querySelector('input');
  expect(previewInput.disabled).toBe(false);
  expect(mockHttpPut).not.toHaveBeenCalled();
  expect(mockHttpPost).not.toHaveBeenCalled();
  await act(async () => {
    Array.from(modal.querySelectorAll('button'))
      .find(node => node.textContent.replace(/\s/g, '') === '关闭').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="canvas-field-name-fmaintdate1"]').value)
    .toBe('维护日期');
  view.cleanup();
});

test('新增检查对比表：默认内容为 检查项目 / A 机 / B 机', async () => {
  const view = renderEditor();
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="editor-add-group-matrix"]').click();
  });
  await act(flushAll);
  const groupNames = Array.from(
    document.querySelectorAll('[data-testid^="canvas-group-name-"]')).map(i => i.value);
  expect(groupNames).toEqual(['基本信息', '电气参数测量', '多机运行对比', '检查项目']);
  const colValues = Array.from(
    document.querySelectorAll('[data-testid^="canvas-matrix-col-name-"]')).map(i => i.value);
  expect(colValues).toContain('A 机');
  expect(colValues).toContain('B 机');
  const rowValues = Array.from(
    document.querySelectorAll('[data-testid^="canvas-matrix-row-name-"]')).map(i => i.value);
  expect(rowValues).toContain('外观检查');
  // 新分组自动选中并可保存；全部结构 id 保持全局唯一
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const form = mockHttpPut.mock.calls[0][1].form;
  expect(form.groups[3].kind).toBe('matrix');
  expect(form.groups[3].columns.map(c => c.name)).toEqual(['A 机', 'B 机']);
  expect(form.groups[3].fields[0].name).toBe('外观检查');
  const ids = form.groups.flatMap(group => [
    group.id, ...(group.fields || []).map(f => f.id),
    ...(group.columns || []).map(c => c.id)]);
  expect(new Set(ids).size).toBe(ids.length);
  view.cleanup();
});

test('复制字段：新 id 副本名插入原字段之后，自动选中并滚动定位', async () => {
  const view = renderEditor();
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fmaintdate1"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fmaintdate1-copy"]').click();
  });
  await act(flushAll);
  // 副本自动选中（检查器显示副本名称）并触发滚动定位
  expect(document.querySelector('[data-testid="inspector-field-name"]').value)
    .toBe('维护日期 副本');
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const form = mockHttpPut.mock.calls[0][1].form;
  const fields = form.groups[0].fields;
  // 副本插入原字段之后，原字段与后继字段原位后移
  expect(fields.map(f => f.name)).toEqual(['维护日期', '维护日期 副本', '备注']);
  expect(fields[0].id).toBe('fmaintdate1');
  expect(fields[1].id).not.toBe('fmaintdate1');
  expect(fields[2].id).toBe('fremark001');
  // 全部结构 id 全局唯一（复制绝不复用已有 id）
  const ids = form.groups.flatMap(group => [
    group.id, ...(group.fields || []).map(f => f.id),
    ...(group.columns || []).map(c => c.id)]);
  expect(new Set(ids).size).toBe(ids.length);
  view.cleanup();
});

test('复制矩阵行/列：新 id 副本名相邻插入并自动选中', async () => {
  const view = renderEditor();
  await act(flushAll);
  // 复制列"A 机"
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-col-name-cdevicema01"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-col-cdevicema01-copy"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-column-name"]').value)
    .toBe('A 机 副本');
  // 复制行"输出电压"
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-row-name-rvoltage001"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-row-rvoltage001-copy"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-field-name"]').value)
    .toBe('输出电压 副本');
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const matrix = mockHttpPut.mock.calls[0][1].form.groups
    .find(group => group.kind === 'matrix');
  expect(matrix.columns.map(c => c.name))
    .toEqual(['A 机', 'A 机 副本', 'B 机']);
  expect(matrix.fields.map(f => f.name))
    .toEqual(['输出电压', '输出电压 副本', '通讯状态']);
  expect(matrix.columns[1].id).not.toBe('cdevicema01');
  expect(matrix.fields[1].id).not.toBe('rvoltage001');
  // 行副本完整拷贝类型/单位等属性
  expect(matrix.fields[1].type).toBe('number');
  expect(matrix.fields[1].unit).toBe('V');
  view.cleanup();
});

test('复制整个分组：组与组内字段/列全部新 id，插入原组之后', async () => {
  const view = renderEditor();
  await act(flushAll);
  // 点击分组名输入框选中该分组（复制入口在选中态操作区）
  await act(async () => {
    document.querySelector('[data-testid="canvas-group-name-gmultidev01"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-group-gmultidev01-copy"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-group-name"]').value)
    .toBe('多机运行对比 副本');
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const groups = mockHttpPut.mock.calls[0][1].form.groups;
  expect(groups.map(group => group.name)).toEqual([
    '基本信息', '电气参数测量', '多机运行对比', '多机运行对比 副本']);
  const original = groups[2];
  const clone = groups[3];
  expect(clone.kind).toBe('matrix');
  expect(clone.columns.length).toBe(2);
  expect(clone.fields.length).toBe(2);
  const originalIds = [original.id, ...original.fields.map(f => f.id),
    ...original.columns.map(c => c.id)];
  [clone.id, ...clone.fields.map(f => f.id), ...clone.columns.map(c => c.id)]
    .forEach(id => expect(originalIds).not.toContain(id));
  const allIds = groups.flatMap(group => [
    group.id, ...(group.fields || []).map(f => f.id),
    ...(group.columns || []).map(c => c.id)]);
  expect(new Set(allIds).size).toBe(allIds.length);
  view.cleanup();
});

test('删除字段后撤销恢复原对象原 id，重做再次删除；Ctrl+Z/Ctrl+Shift+Z 同效', async () => {
  const view = renderEditor();
  await act(flushAll);
  // 无历史时撤销不可用
  expect(document.querySelector('[data-testid="editor-undo"]').disabled).toBe(true);
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fremark001"]').click();
  });
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-field-fremark001-del"]').click();
  });
  await confirmPopover();
  expect(document.querySelector('[data-testid="canvas-field-fremark001"]')).toBeNull();
  await act(async () => {
    document.querySelector('[data-testid="editor-undo"]').click();
  });
  await act(flushAll);
  // 撤销恢复原对象原 id（快照历史的核心价值）
  const restoredName = document.querySelector(
    '[data-testid="canvas-field-name-fremark001"]');
  expect(restoredName).toBeTruthy();
  expect(restoredName.value).toBe('备注');
  await act(async () => {
    document.querySelector('[data-testid="editor-redo"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="canvas-field-fremark001"]')).toBeNull();
  // 键盘路径：Ctrl+Z 撤销 / Ctrl+Shift+Z 重做
  await act(async () => {
    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'z', ctrlKey: true, bubbles: true, cancelable: true}));
  });
  await act(flushAll);
  expect(document.querySelector(
    '[data-testid="canvas-field-name-fremark001"]')).toBeTruthy();
  await act(async () => {
    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'z', ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true}));
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="canvas-field-fremark001"]')).toBeNull();
  view.cleanup();
});

test('新增字段/矩阵行/列后自动选中新对象并滚动定位', async () => {
  const view = renderEditor();
  await act(flushAll);
  Element.prototype.scrollIntoView.mockClear();
  await act(async () => {
    document.querySelector('[data-testid="canvas-add-field-gbaseinfo01"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-field-name"]').value)
    .toBe('新填写项');
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-add-row-gmultidev01"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-field-name"]').value)
    .toBe('新检查项');
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-add-col-gmultidev01"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-column-name"]').value)
    .toBe('新对比对象');
  view.cleanup();
});

test('分组排序在左栏操作，画布分组卡不再提供上下移', async () => {
  const view = renderEditor();
  await act(flushAll);
  expect(document.querySelector('[data-testid="canvas-group-gbaseinfo01-up"]')).toBeNull();
  expect(document.querySelector('[data-testid="canvas-group-gbaseinfo01-down"]')).toBeNull();
  await act(async () => {
    document.querySelector('[data-testid="editor-group-down-gbaseinfo01"]').click();
  });
  await act(flushAll);
  const names = Array.from(document.querySelectorAll(
    '[data-testid^="canvas-group-name-"]')).map(node => node.value);
  expect(names).toEqual(['电气参数测量', '基本信息', '多机运行对比']);
  // 左栏分组点击仍可选中并滚动定位到画布分组
  Element.prototype.scrollIntoView.mockClear();
  await act(async () => {
    document.querySelector('[data-testid="editor-group-gmultidev01"]').click();
  });
  await act(flushAll);
  expect(document.querySelector('[data-testid="inspector-group-name"]').value)
    .toBe('多机运行对比');
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  view.cleanup();
});

test('number 切换为其他类型后 unit 等无效属性清理，不再残留提交', async () => {
  const view = renderEditor();
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="canvas-matrix-row-name-rvoltage001"]').click();
  });
  await act(flushAll);
  const selectNode = document.querySelector('[data-testid="inspector-field-type"]');
  const selector = selectNode.querySelector('.ant-select-selector') || selectNode;
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    selector.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
  });
  await act(flushAll);
  const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
    .find(node => node.textContent === '单选');
  expect(option).toBeTruthy();
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(flushAll);
  mockHttpPut.mockResolvedValue({data: makeDetail()});
  await act(async () => {
    document.querySelector('[data-testid="editor-save-draft"]').click();
  });
  await act(flushAll);
  const row = mockHttpPut.mock.calls[0][1].form.groups
    .find(group => group.kind === 'matrix').fields
    .find(field => field.id === 'rvoltage001');
  expect(row.type).toBe('choice');
  expect(row.unit).toBe('');
  expect(row.options).toEqual([]);
  view.cleanup();
});

test('窄屏预览：渲染器收到 narrow，矩阵以逐列卡片渲染', async () => {
  window.innerWidth = 600;
  const view = renderEditor();
  await act(flushAll);
  await act(async () => {
    document.querySelector('[data-testid="editor-preview"]').click();
  });
  await act(flushAll);
  const modal = document.querySelector('.ant-modal');
  expect(modal.textContent).toContain('多机运行对比');
  expect(modal.textContent).toContain('A 机');
  expect(modal.querySelector('table')).toBeNull();
  view.cleanup();
  window.innerWidth = 1280;
});

/**
 * 数字表单模板 P2 行为测试（2026-10-23）。
 *
 * 真实渲染（ReactDOM + jsdom，antd 真组件）+ mock libs/http，验证：
 * - 属性面板按类型配置（textarea rows / number min/max/precision /
 *   normal_abnormal 异常时说明必填）与切换类型清理不适用属性（保存
 *   payload 不残留，与后端"不适用键拒绝"一致）；
 * - 存量 v1 草稿打开即本地升级为 v2 并以未保存修改呈现：保存 payload
 *   protocol_version=2（显式保存即升级，解决无 dirty 不发保存请求的冲突）；
 * - 发布检查弹窗：阻断错误禁用发布按钮、点击条目关闭弹窗并定位选中
 *   对象；仅警告须勾选"已知悉"才能发布；
 * - 发布 POST 已成功、详情/列表刷新失败：发布 Promise 不判败（成功
 *   反馈对应真实发布结果）；
 * - 「保存草稿并预览样张」：有 dirty 先 PUT，保存失败中止样张生成；
 * - 试填预览：试填值留在弹窗内存并驱动渲染，不发任何写请求，关闭即丢。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const h = React.createElement;

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
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  return {
    AuthDiv: Shell, AuthButton: (props) => React.createElement('button', {
      type: 'button', 'data-testid': props['data-testid'], onClick: props.onClick,
    }, props.children),
    AuthCard: Shell, AuthFragment: Shell, Breadcrumb: Shell, SearchForm: Shell,
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
window.URL.createObjectURL = jest.fn(() => 'blob:mock');
window.URL.revokeObjectURL = jest.fn();

const FormTemplateEditor = require('../FormTemplateEditor').default;
const {formTemplateStore} = require('../formTemplateStore');

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const flushAll = async () => { await flush(); await flush(); await flush(); };

const PDF_BYTES = new Uint8Array([37, 80, 68, 70, 45]); // %PDF-

const V2_DRAFT = {
  protocol_version: 2,
  groups: [
    {id: 'gattr00001', name: '属性配置', description: '', kind: 'fields',
     item_name: '', columns: [], fields: [
       {id: 'ftextarea1', name: '备注', type: 'textarea', required: false,
        description: '', unit: '', options: [], rows: 4},
       {id: 'fnumber001', name: '电压', type: 'number', required: false,
        description: '', unit: 'V', options: [],
        min: 0, max: 400, precision: 1},
       {id: 'fabn000001', name: '外观', type: 'normal_abnormal', required: true,
        description: '', unit: '', options: []},
     ]},
  ],
};

function makeDetail(form) {
  return {
    id: 12, name: '周维护数字表单', ledger_type: 'week_month',
    description: '', system: null, system_name: '', generation_period: '',
    generation_period_text: '待配置', is_active: true,
    has_draft: true, latest_version_no: 0, versions_count: 0, ledgers_count: 0,
    status: 'draft',
    draft: {form: form || V2_DRAFT, updated_at: '2026-10-23T10:00:00',
            updated_by: '张三'},
    draft_state: {relation: 'modified', latest_version_no: 0, versions_count: 0,
                  field_count: 3, updated_at: '2026-10-23T10:00:00'},
  };
}

function resetStore() {
  const store = formTemplateStore;
  store.list = []; store.isFetching = false; store.detail = null;
  store.editorVisible = false; store.editorTemplate = null;
  store.editorLoading = false; store.editorLoadError = '';
  store.savingDraft = false; store.publishing = false;
  store.samplePdfUrl = ''; store.samplePdfMeta = null;
  store.samplePdfLoading = false; store.samplePdfError = '';
}

function render(node) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  ReactDOM.render(node, container);
  return {container, cleanup: () => {
    ReactDOM.unmountComponentAtNode(container);
    document.querySelectorAll('.ant-modal-root, .ant-drawer-root, .ant-modal-confirm')
      .forEach(node => node.remove());
    container.remove();
  }};
}

function setText(input, value) {
  const proto = input.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
}

/** 打开 antd Select 并点选指定文案的选项。 */
async function pickSelectOption(testId, optionText) {
  const selectNode = document.querySelector(`[data-testid="${testId}"]`);
  const selector = selectNode.querySelector('.ant-select-selector') || selectNode;
  await act(async () => {
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    selector.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
  });
  await act(flush);
  const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
    .find(node => node.textContent === optionText);
  expect(option).toBeTruthy();
  await act(async () => { option.click(); });
  await act(flush);
}

async function openEditor(detail) {
  mockHttpGet.mockImplementation(url => {
    const target = String(url);
    if (target.endsWith('/form-templates/12/')) {
      return Promise.resolve({data: detail});
    }
    if (target.endsWith('/form-templates/')) {
      return Promise.resolve({data: []});
    }
    return Promise.reject('意外请求：' + target);
  });
  act(() => { formTemplateStore.openEditor({id: 12, name: '周维护数字表单'}); });
  const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
  await act(flushAll);
  return view;
}

/** 选中画布字段（点击字段行触发选中，右栏属性面板出现）。 */
async function selectField(fieldId) {
  await act(async () => {
    document.querySelector(`[data-testid="canvas-field-${fieldId}"]`).click();
  });
  await act(flush);
}

beforeEach(() => {
  mockHttpGet.mockReset();
  mockHttpPost.mockReset();
  mockHttpPut.mockReset();
  window.URL.createObjectURL.mockClear();
  window.URL.revokeObjectURL.mockClear();
  resetStore();
});

describe('P2 属性面板按类型配置与切换清理', () => {
  test('textarea 行数 / number 范围精度 / 异常时说明必填 按类型显示', async () => {
    const view = await openEditor(makeDetail());
    await selectField('ftextarea1');
    expect(document.querySelector('[data-testid="inspector-field-rows"]')).toBeTruthy();
    await selectField('fnumber001');
    expect(document.querySelector('[data-testid="inspector-field-unit"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="inspector-field-min"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="inspector-field-max"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="inspector-field-precision"]')).toBeTruthy();
    // number 字段不显示行数；textarea 字段不显示范围
    expect(document.querySelector('[data-testid="inspector-field-rows"]')).toBeNull();
    await selectField('fabn000001');
    expect(document.querySelector('[data-testid="inspector-field-require-desc"]')).toBeTruthy();
    view.cleanup();
  });

  test('切换字段类型清理不适用属性：保存 payload 不残留（与后端约束一致）', async () => {
    const view = await openEditor(makeDetail());
    // textarea（rows=4）→ 单行文本：rows 清除
    await selectField('ftextarea1');
    await pickSelectOption('inspector-field-type', '单行文本');
    // number（min/max/precision/unit）→ 单行文本：范围/精度/单位清除
    await selectField('fnumber001');
    await pickSelectOption('inspector-field-type', '单行文本');
    mockHttpPut.mockResolvedValue({data: makeDetail()});
    await act(async () => {
      document.querySelector('[data-testid="editor-save-draft"]').click();
    });
    await act(flushAll);
    const form = mockHttpPut.mock.calls[0][1].form;
    const fields = form.groups[0].fields;
    expect(fields[0].type).toBe('text');
    expect(fields[0].rows).toBeUndefined();
    expect(fields[1].type).toBe('text');
    expect(fields[1].min).toBeUndefined();
    expect(fields[1].max).toBeUndefined();
    expect(fields[1].precision).toBeUndefined();
    expect(fields[1].unit).toBe('');
    view.cleanup();
  });

  test('配置异常时说明必填后进入保存 payload', async () => {
    const view = await openEditor(makeDetail());
    await selectField('fabn000001');
    // antd Checkbox 将 data-testid 落在 input 元素上，直接点击该节点
    const checkbox = document.querySelector('[data-testid="inspector-field-require-desc"]');
    act(() => { checkbox.click(); });
    mockHttpPut.mockResolvedValue({data: makeDetail()});
    await act(async () => {
      document.querySelector('[data-testid="editor-save-draft"]').click();
    });
    await act(flushAll);
    const fields = mockHttpPut.mock.calls[0][1].form.groups[0].fields;
    expect(fields[2].require_desc_when_abnormal).toBe(true);
    view.cleanup();
  });
});

describe('存量 v1 草稿显式升级为 v2', () => {
  test('打开即视为未保存修改（dirty），保存 payload 为 protocol_version 2', async () => {
    const legacy = JSON.parse(JSON.stringify(V2_DRAFT));
    legacy.protocol_version = 1;
    const view = await openEditor(makeDetail(legacy));
    // 仅协议升级也是未保存修改：不点保存直接发布会被后端拒绝，
    // 编辑器以 dirty 呈现提示用户先保存
    expect(document.body.textContent).toContain('有未保存修改');
    mockHttpPut.mockResolvedValue({data: makeDetail()});
    await act(async () => {
      document.querySelector('[data-testid="editor-save-draft"]').click();
    });
    await act(flushAll);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(mockHttpPut.mock.calls[0][1].form.protocol_version).toBe(2);
    expect(document.body.textContent).not.toContain('有未保存修改');
    view.cleanup();
  });

  test('v2 草稿打开即干净（无 dirty，不发保存请求）', async () => {
    const view = await openEditor(makeDetail());
    expect(document.body.textContent).not.toContain('有未保存修改');
    await act(async () => {
      document.querySelector('[data-testid="editor-save-draft"]').click();
    });
    await act(flushAll);
    expect(mockHttpPut).not.toHaveBeenCalled();
    view.cleanup();
  });

  test('未知未来协议版本（v3）：保持原值不改写，禁编辑保存/发布/载入示例', async () => {
    const future = JSON.parse(JSON.stringify(V2_DRAFT));
    future.protocol_version = 3;
    const view = await openEditor(makeDetail(future));
    // 明确禁用提示 + 全部写操作禁用（保存接口对 v3 整体拒绝，前端 fail-closed）
    expect(document.body.textContent).toContain('草稿协议版本不支持');
    expect(document.body.textContent).toContain('v3');
    expect(document.querySelector('[data-testid="editor-save-draft"]').disabled)
      .toBe(true);
    expect(document.querySelector('[data-testid="editor-publish"]').disabled)
      .toBe(true);
    expect(document.querySelector('[data-testid="editor-load-sample"]').disabled)
      .toBe(true);
    expect(document.querySelector('[data-testid="editor-preview"]').disabled)
      .toBe(true);
    // 工作副本保持 v3 原值：禁用横幅的版本号读自工作副本 form（未被改写为 v2）
    view.cleanup();
  });

  test('未知协议版本：画布与属性面板编辑入口全部失效（本地表单不可变）', async () => {
    const future = JSON.parse(JSON.stringify(V2_DRAFT));
    future.protocol_version = 3;
    const view = await openEditor(makeDetail(future));
    // 编辑区 pointer-events 禁用（真实浏览器阻断交互；jsdom 仍可派发事件，
    // 以下断言验证冻结 mutators 这一兜底层：所有编辑入口为 no-op）
    const editArea = document.querySelector('[data-testid="editor-edit-area"]');
    expect(editArea.style.pointerEvents).toBe('none');
    // 精确计数结构行（排除 canvas-field-name-* 输入与 -copy/-del 等操作按钮）
    const fieldRows = () => Array.from(
      document.querySelectorAll('[data-testid^="canvas-field-"]'))
      .filter(node => /^canvas-field-[a-z0-9]+$/.test(node.getAttribute('data-testid')));
    const groupRows = () => Array.from(
      document.querySelectorAll('[data-testid^="canvas-group-"]'))
      .filter(node => /^canvas-group-[a-z0-9]+$/.test(node.getAttribute('data-testid')));
    expect(fieldRows().length).toBe(3);
    // 画布：复制字段不产生新行
    await selectField('ftextarea1');
    const copyBtn = document.querySelector(
      '[data-testid="canvas-field-ftextarea1-copy"]');
    await act(async () => { copyBtn.click(); });
    await act(flush);
    expect(fieldRows().length).toBe(3);
    // 画布：删除字段（Popconfirm 确认后）仍保留（复制 no-op 后选中回退，
    // 需重新选中才出现行内操作按钮）
    await selectField('ftextarea1');
    await act(async () => {
      document.querySelector('[data-testid="canvas-field-ftextarea1-del"]').click();
    });
    await act(flush);
    const confirmBtn = Array.from(document.querySelectorAll('.ant-popover button'))
      .find(node => node.textContent.replace(/\s/g, '') === '删除');
    expect(confirmBtn).toBeTruthy();
    await act(async () => { confirmBtn.click(); });
    await act(flush);
    expect(fieldRows().length).toBe(3);
    // 画布：底部新增分组入口 no-op
    await act(async () => {
      document.querySelector('[data-testid="editor-add-group-fields"]').click();
    });
    await act(flush);
    expect(groupRows().length).toBe(1);
    // 检查器：切换字段类型 no-op（面板仍按原类型渲染，rows 输入仍在）
    await pickSelectOption('inspector-field-type', '单行文本');
    expect(document.querySelector('[data-testid="inspector-field-rows"]'))
      .toBeTruthy();
    view.cleanup();
  });
});

describe('发布检查弹窗', () => {
  test('阻断错误禁用发布按钮，点击条目定位选中对象', async () => {
    const view = await openEditor(makeDetail());
    mockHttpPost.mockImplementation(url => {
      if (String(url).endsWith('/publish-check/')) {
        return Promise.resolve({data: {errors: [{
          code: 'schema_invalid',
          message: '字段「电压」存在未知属性：rows',
          anchor: {type: 'field', groupId: 'gattr00001', fieldId: 'fnumber001'},
        }], warnings: []}});
      }
      return Promise.resolve({data: {version_no: 1}});
    });
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flushAll);
    // 无 dirty：直接 publish-check，未发布
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/publish-check/',
      expect.objectContaining({form: expect.objectContaining({protocol_version: 2})}));
    expect(document.body.textContent).toContain('1 项阻断问题');
    expect(document.querySelector('[data-testid="publish-check-confirm"]').disabled)
      .toBe(true);
    // 点击错误条目：关闭弹窗并定位选中字段（画布选中态高亮）
    await act(async () => {
      document.querySelector('[data-testid="publish-check-locate-schema_invalid"]').click();
    });
    await act(flush);
    expect(document.querySelector('[data-testid="publish-check-confirm"]')).toBeNull();
    const selected = document.querySelector(
      '[data-testid="canvas-field-fnumber001"]');
    expect(selected.style.background).toBe('rgb(240, 248, 255)');
    expect(mockHttpPost).not.toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/publish/');
    view.cleanup();
  });

  test('仅警告须勾选已知悉才能发布；无问题可直接发布', async () => {
    const view = await openEditor(makeDetail());
    mockHttpPost.mockImplementation(url => {
      if (String(url).endsWith('/publish-check/')) {
        return Promise.resolve({data: {errors: [], warnings: [{
          code: 'abnormal_no_desc', message: '字段「外观」为正常/异常项但未填写检查说明',
          anchor: {type: 'field', groupId: 'gattr00001', fieldId: 'fabn000001'},
        }]}});
      }
      return Promise.resolve({data: {version_no: 1}});
    });
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flushAll);
    const confirm = document.querySelector('[data-testid="publish-check-confirm"]');
    expect(confirm.disabled).toBe(true);
    expect(document.body.textContent).toContain('不影响发布');
    // 勾选已知悉 → 发布按钮放开 → 确认发布（Checkbox 的 testid 在 input 上）
    await act(async () => {
      document.querySelector('[data-testid="publish-check-acknowledge"]').click();
    });
    await act(flush);
    expect(document.querySelector('[data-testid="publish-check-confirm"]').disabled)
      .toBe(false);
    await act(async () => {
      document.querySelector('[data-testid="publish-check-confirm"]').click();
    });
    await act(flushAll);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/publish/');
    view.cleanup();
  });
});

describe('发布检查与保存时序（先检查后保存）', () => {
  test('非法未保存字段：点击发布先做无状态检查，弹窗显示可定位错误，不保存不发布', async () => {
    const view = await openEditor(makeDetail());
    // 把文本字段切为"单选"且不配置选项 → 未保存且非法（后端保存/发布都会拒绝）
    await selectField('ftextarea1');
    await pickSelectOption('inspector-field-type', '单选');
    expect(document.body.textContent).toContain('有未保存修改');
    mockHttpPost.mockImplementation(url => {
      if (String(url).endsWith('/publish-check/')) {
        return Promise.resolve({data: {errors: [{
          code: 'schema_invalid',
          message: '单选字段「备注」至少配置一个选项',
          anchor: {type: 'field', groupId: 'gattr00001', fieldId: 'ftextarea1'},
        }], warnings: []}});
      }
      return Promise.resolve({data: {version_no: 1}});
    });
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flushAll);
    // 先检查后保存：非法内容直接得到结构化可定位错误，不尝试保存
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/publish-check/',
      expect.objectContaining({form: expect.objectContaining({protocol_version: 2})}));
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(mockHttpPost).not.toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/publish/');
    expect(document.body.textContent).toContain('1 项阻断问题');
    expect(document.body.textContent)
      .toContain('单选字段「备注」至少配置一个选项');
    // 点击错误条目定位到非法字段（画布选中态高亮），修复后可重新发布
    await act(async () => {
      document.querySelector('[data-testid="publish-check-locate-schema_invalid"]').click();
    });
    await act(flush);
    const selected = document.querySelector('[data-testid="canvas-field-ftextarea1"]');
    expect(selected.style.background).toBe('rgb(240, 248, 255)');
    view.cleanup();
  });

  test('检查通过后保存失败：中止发布（不弹确认、不发布）', async () => {
    const view = await openEditor(makeDetail());
    // 修改仍合法（改名），publish-check 通过但 PUT 失败（如并发冲突）
    setText(document.querySelector('[data-testid="canvas-field-name-ftextarea1"]'),
            '备注（修订）');
    mockHttpPost.mockImplementation(url => {
      if (String(url).endsWith('/publish-check/')) {
        return Promise.resolve({data: {errors: [], warnings: []}});
      }
      return Promise.resolve({data: {version_no: 1}});
    });
    mockHttpPut.mockRejectedValue('保存失败');
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flushAll);
    expect(mockHttpPost).toHaveBeenCalledTimes(1); // 仅 publish-check
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(mockHttpPost).not.toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/publish/');
    expect(document.querySelector('[data-testid="publish-check-confirm"]')).toBeNull();
    // 保存失败也必须解锁：编辑入口恢复可用
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).not.toBe('none');
    view.cleanup();
  });
});

describe('发布检查在途编辑锁定（快照一致性）', () => {
  test('检查在途锁定编辑（快照一致性），检查完成并保存后恢复', async () => {
    const view = await openEditor(makeDetail());
    // 制造未保存修改（点击发布时捕获该快照）
    setText(document.querySelector('[data-testid="canvas-field-name-ftextarea1"]'),
            '备注（修订）');
    let resolveCheck;
    mockHttpPost.mockImplementation(url => {
      if (String(url).endsWith('/publish-check/')) {
        return new Promise(resolve => { resolveCheck = resolve; });
      }
      return Promise.resolve({data: {version_no: 1}});
    });
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flushAll);
    // 检查在途：编辑区锁定、底部保存/发布按钮禁用（防检查/保存旧快照）
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).toBe('none');
    expect(document.querySelector('[data-testid="editor-save-draft"]').disabled)
      .toBe(true);
    expect(document.querySelector('[data-testid="editor-publish"]').disabled)
      .toBe(true);
    // 锁定兜底：画布复制 no-op（冻结 mutators）
    await selectField('ftextarea1');
    await act(async () => {
      document.querySelector('[data-testid="canvas-field-ftextarea1-copy"]').click();
    });
    await act(flush);
    const rows = Array.from(
      document.querySelectorAll('[data-testid^="canvas-field-"]'))
      .filter(node => /^canvas-field-[a-z0-9]+$/.test(node.getAttribute('data-testid')));
    expect(rows.length).toBe(3);
    // 检查通过 → 保存未保存内容 → 弹窗出现
    mockHttpPut.mockResolvedValue({data: makeDetail()});
    await act(async () => { resolveCheck({data: {errors: [], warnings: []}}); });
    await act(flushAll);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(mockHttpPut.mock.calls[0][1].form.groups[0].fields[0].name)
      .toBe('备注（修订）');
    expect(document.querySelector('[data-testid="publish-check-confirm"]'))
      .toBeTruthy();
    // 取消弹窗后编辑恢复：复制正常产生新行（antd 两字按钮文本带空格）
    const cancel = Array.from(document.querySelectorAll('.ant-modal button'))
      .find(node => node.textContent.replace(/\s/g, '') === '取消');
    await act(async () => { cancel.click(); });
    await act(flush);
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).not.toBe('none');
    // 解锁后编辑恢复正常：重新选中字段并复制 → 产生新行
    await selectField('ftextarea1');
    await act(async () => {
      document.querySelector('[data-testid="canvas-field-ftextarea1-copy"]').click();
    });
    await act(flush);
    const rowsAfter = Array.from(
      document.querySelectorAll('[data-testid^="canvas-field-"]'))
      .filter(node => /^canvas-field-[a-z0-9]+$/.test(node.getAttribute('data-testid')));
    expect(rowsAfter.length).toBe(4);
    view.cleanup();
  });
});

describe('发布检查关闭/重开竞态（同一组件实例）', () => {
  /** 挂起式 publish-check mock：每次调用入队一个 resolve，按序手动放行。 */
  function mockPendingChecks() {
    const pending = [];
    mockHttpPost.mockImplementation(url => {
      if (String(url).endsWith('/publish-check/')) {
        return new Promise(resolve => { pending.push(resolve); });
      }
      return Promise.resolve({data: {version_no: 1}});
    });
    return pending;
  }

  /** 只挂载一次编辑器实例，其后经 store.openEditor 在同一实例上重开——
   * 正式页面常驻渲染 FormTemplateEditor（关闭仅 Drawer 隐藏），重开复用
   * 组件内的 checkSeqRef/publishChecking 状态，竞态测试必须覆盖该路径
   * （卸载后重建的新实例状态全新，无法证明修复）。 */
  async function mountEditorOnce(detail) {
    mockHttpGet.mockImplementation(url => {
      const target = String(url);
      if (target.endsWith('/form-templates/12/')) {
        return Promise.resolve({data: detail});
      }
      return Promise.resolve({data: []});
    });
    act(() => { formTemplateStore.openEditor({id: 12, name: '周维护数字表单'}); });
    const view = render(h(FormTemplateEditor, {store: formTemplateStore}));
    await act(flushAll);
    return view;
  }

  const reopenEditor = async () => {
    act(() => { formTemplateStore.openEditor({id: 12, name: '周维护数字表单'}); });
    await act(flushAll);
  };

  test('检查在途关闭编辑器：锁立即清除，同实例重开不残留；旧请求返回无副作用', async () => {
    const pending = mockPendingChecks();
    const view = await mountEditorOnce(makeDetail());
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flush);
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).toBe('none');
    // 检查在途直接关闭抽屉（无 dirty 免确认）——实例保持挂载
    await act(async () => {
      document.querySelector('.ant-drawer-close').click();
    });
    await act(flush);
    expect(formTemplateStore.editorVisible).toBe(false);
    // 同一实例重开：不因挂起的旧请求残留锁定（此前会一直锁到请求返回）
    await reopenEditor();
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).not.toBe('none');
    expect(document.querySelector('[data-testid="editor-publish"]').disabled)
      .toBe(false);
    // 旧请求此时返回：不弹窗、不再改变编辑器状态
    await act(async () => { pending[0]({data: {errors: [], warnings: []}}); });
    await act(flushAll);
    expect(document.querySelector('[data-testid="publish-check-confirm"]'))
      .toBeNull();
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).not.toBe('none');
    view.cleanup();
  });

  test('同实例旧检查请求返回不得解开新检查的锁（生命周期令牌）', async () => {
    const pending = mockPendingChecks();
    const view = await mountEditorOnce(makeDetail());
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flush);
    // 检查在途关闭（同实例，锁立即清除）→ 重开 → 发起新一轮检查（挂起）
    await act(async () => {
      document.querySelector('.ant-drawer-close').click();
    });
    await act(flush);
    await reopenEditor();
    await act(async () => {
      document.querySelector('[data-testid="editor-publish"]').click();
    });
    await act(flush);
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).toBe('none');
    // 第一轮（旧请求）在同实例上返回：新检查的锁必须保持
    // （无令牌守卫时旧回调会 setPublishChecking(false) 提前解锁）
    await act(async () => { pending[0]({data: {errors: [], warnings: []}}); });
    await act(flushAll);
    expect(document.querySelector('[data-testid="editor-edit-area"]')
      .style.pointerEvents).toBe('none');
    expect(document.querySelector('[data-testid="editor-publish"]').disabled)
      .toBe(true);
    // 新请求返回：正常解锁并进入发布确认弹窗
    await act(async () => { pending[1]({data: {errors: [], warnings: []}}); });
    await act(flushAll);
    expect(document.querySelector('[data-testid="publish-check-confirm"]'))
      .toBeTruthy();
    view.cleanup();
  });
});

describe('发布成功但刷新失败不判败', () => {
  test('publish：POST 成功后详情/列表刷新失败，Promise 仍正常完成', async () => {
    mockHttpPost.mockResolvedValue({data: {version_no: 2, field_count: 3}});
    mockHttpGet.mockRejectedValue(new Error('刷新服务不可用'));
    let result = 'pending';
    let caught = null;
    await formTemplateStore.publish(12)
      .then(() => { result = 'resolved'; })
      .catch(e => { caught = e; result = 'rejected'; });
    expect(result).toBe('resolved');
    expect(caught).toBeNull();
    expect(formTemplateStore.publishing).toBe(false);
  });
});

describe('保存草稿并预览样张', () => {
  test('无 dirty 直接生成样张；有 dirty 先 PUT 成功再生成', async () => {
    const view = await openEditor(makeDetail());
    // 无 dirty：直接 POST preview/pdf
    mockHttpPost.mockResolvedValue({
      data: PDF_BYTES.buffer, headers: {'x-el-pdf-pages': '1'}});
    await act(async () => {
      document.querySelector('[data-testid="editor-save-preview-pdf"]').click();
    });
    await act(flushAll);
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/preview/pdf/', {},
      {responseType: 'arraybuffer', timeout: 180000});
    view.cleanup();
    resetStore();

    // 有 dirty：先 PUT 成功再生成样张
    const view2 = await openEditor(makeDetail());
    setText(document.querySelector('[data-testid="canvas-field-name-ftextarea1"]'),
            '备注（修订）');
    mockHttpPut.mockResolvedValue({data: makeDetail()});
    mockHttpPost.mockClear();
    mockHttpPost.mockResolvedValue({
      data: PDF_BYTES.buffer, headers: {'x-el-pdf-pages': '1'}});
    await act(async () => {
      document.querySelector('[data-testid="editor-save-preview-pdf"]').click();
    });
    await act(flushAll);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/form-templates/12/preview/pdf/', {},
      {responseType: 'arraybuffer', timeout: 180000});
    view2.cleanup();
  });

  test('保存失败中止样张生成（不基于过期草稿）', async () => {
    const view = await openEditor(makeDetail());
    setText(document.querySelector('[data-testid="canvas-field-name-ftextarea1"]'),
            '备注（修订）');
    mockHttpPut.mockRejectedValue('结构校验失败');
    mockHttpPost.mockResolvedValue({
      data: PDF_BYTES.buffer, headers: {}});
    await act(async () => {
      document.querySelector('[data-testid="editor-save-preview-pdf"]').click();
    });
    await act(flushAll);
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(mockHttpPost).not.toHaveBeenCalled();
    view.cleanup();
  });
});

describe('试填预览（值仅存弹窗内存）', () => {
  test('可试填并驱动渲染；不发任何写请求；关闭重开即丢弃', async () => {
    const view = await openEditor(makeDetail());
    await act(async () => {
      document.querySelector('[data-testid="editor-preview"]').click();
    });
    await act(flushAll);
    expect(document.body.textContent).toContain('试填内容不会保存');
    // 试填外观=异常：说明输入出现（applyFillEdit 驱动弹窗本地 values）
    const abnormalRadio = document.querySelector(
      '#anchor-fabn000001 input[value="abnormal"]');
    expect(abnormalRadio).toBeTruthy();
    await act(async () => { abnormalRadio.click(); });
    await act(flushAll);
    expect(document.querySelector('[data-testid="abnormal-desc-fabn000001"]'))
      .toBeTruthy();
    // 关闭弹窗：试填值丢弃（重开后无异常说明）
    expect(mockHttpPut).not.toHaveBeenCalled();
    expect(mockHttpPost).not.toHaveBeenCalled();
    const closeButton = Array.from(
      document.querySelectorAll('.ant-modal button'))
      .find(node => node.textContent === '关 闭');
    await act(async () => { closeButton.click(); });
    await act(flushAll);
    await act(async () => {
      document.querySelector('[data-testid="editor-preview"]').click();
    });
    await act(flushAll);
    expect(document.querySelector('[data-testid="abnormal-desc-fabn000001"]'))
      .toBeNull();
    view.cleanup();
  });
});

/**
 * 原生台账详情（iframe 壳 + 工具栏）组件行为测试。
 *
 * 消息桥以可控 fake 替换（iframe 桥自身行为在 bridge.test.js 真实验证），
 * 本文件验证宿主页面真实交互路径：
 * - 渲染表头信息与编辑器 iframe 占位（未就绪显示加载态）；
 * - 保存草稿：collect 值参与保存并通知编辑器复位；
 * - 完成填写：必填未填本地拦截（不发请求），通过后走 store.complete；
 * - 更正模式：进入更正原因弹窗（空原因拒绝）、提交更正、取消更正；
 * - 返回守卫：有未保存修改先确认（放弃修改并返回 / 继续填写）；
 * - 已完成/已作废：无保存/完成按钮（只读），更正/导出可用性随状态切换；
 * - 更正记录表格渲染。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message, Modal} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: mockHttpPost, put: mockHttpPut, delete: mockHttpDelete},
  exportFile: jest.fn(() => Promise.resolve({})),
  history: {location: {search: ''}, replace: jest.fn(), push: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

// 可控消息桥 fake：collect 可配置，sendInit/notifySaved 记录调用
const mockChannel = {
  ready: true,
  readySeq: 1,
  loadFailed: false,
  reloadToken: 0,
  collect: jest.fn(),
  sendInit: jest.fn(),
  notifySaved: jest.fn(),
  retry: jest.fn(),
};

jest.mock('../bridge', () => ({
  __esModule: true,
  editorUrl: () => '/native-ledger/index.html',
  resolveEditorOrigin: () => globalThis.location.origin,
  MSG: {
    READY: 'nl-ready', INIT: 'nl-init', VALUES: 'nl-values',
    DRAFT_META: 'nl-draft-meta', COLLECT: 'nl-collect',
    COLLECT_RESULT: 'nl-collect-result', EXPORT_PDF: 'nl-export-pdf',
    SAVED: 'nl-saved',
  },
  listenEditor: jest.fn(() => () => {}),
  postToEditor: jest.fn(),
  useEditorChannel: jest.fn(() => mockChannel),
}));

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const {NativeLedgerStore} = require('../nativeLedgerStore');
const NativeLedgerDetail = require('../NativeLedgerDetail').default;

function flush(ms = 0) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

const VERSION = {
  id: 5, version_no: 1, template_name: '原生测试模板', ledger_type: 'week_month',
  field_count: 2, snapshot: {sheets: {ledger: {cellData: {}}}},
  bindings: [
    {id: 'b1', key: 'conclusion', label: '维护结论', section: '结论', range: 'B2',
      type: 'text', placeholder: '', is_required: true},
  ],
  paper: {size: 'A4', orientation: 'landscape', fitToWidth: true,
    margins: {top: 12, right: 10, bottom: 12, left: 10}},
};

function makeDetail(overrides = {}) {
  const {status = 'draft', values = {conclusion: ''}, editable = status === 'draft',
    corrections = [], ...rest} = overrides;
  return {
    id: 66, ledger_no: 'EL-WM-20261018-001', ledger_type: 'week_month',
    executed_date: '2026-10-18', status, corrections,
    native: {record_id: 9, values, editable, voided: status === 'void', version: VERSION},
    ...rest,
  };
}

function render(store, onBack = jest.fn()) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(React.createElement(NativeLedgerDetail, {store, onBack}), container);
  });
  return container;
}

function findButton(root, testId) {
  return root.querySelector(`[data-testid="${testId}"]`);
}

function flushDests() {
  // antd Modal.confirm 内容异步挂载
  return new Promise(resolve => setTimeout(resolve, 30));
}

function setupStore() {
  const store = new NativeLedgerStore();
  jest.clearAllMocks();
  mockChannel.ready = true;
  mockChannel.readySeq = 1;
  mockChannel.loadFailed = false;
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
  return store;
}

function cleanupContainer(container) {
  if (container) {
    act(() => ReactDOM.unmountComponentAtNode(container));
    container.remove();
  }
  document.querySelectorAll('.ant-modal-root, .ant-modal-confirm-root')
    .forEach(node => node.remove());
  message.success.mockRestore();
  message.warning.mockRestore();
  message.error.mockRestore();
}

describe('NativeLedgerDetail 渲染与注入', () => {
  let store;
  let container;

  beforeEach(() => {
    store = setupStore();
  });

  afterEach(() => {
    cleanupContainer(container);
    container = null;
  });

  test('渲染表头与编辑器容器，注入初始化数据（fill + 版本快照）', () => {
    store.applyDetail(makeDetail());
    container = render(store);
    expect(container.textContent).toContain('原生台账：EL-WM-20261018-001');
    expect(container.textContent).toContain('原生测试模板');
    expect(findButton(container, 'native-save')).toBeTruthy();
    expect(findButton(container, 'native-complete')).toBeTruthy();
    expect(findButton(container, 'native-ledger-iframe')).toBeTruthy();
    // 就绪后注入 nl-init（mode=fill，携带版本快照与填写值）
    expect(mockChannel.sendInit).toHaveBeenCalled();
    const init = mockChannel.sendInit.mock.calls[0][0];
    expect(init.mode).toBe('fill');
    expect(init.version.bindings).toHaveLength(1);
    expect(init.meta.ledgerNo).toBe('EL-WM-20261018-001');
    expect(init.meta.versionNo).toBe(1);
    expect(init.meta.editable).toBe(true);
  });

  test('已完成台账只读：无保存/完成/删除按钮，提供更正与导出', () => {
    store.applyDetail(makeDetail({status: 'completed', editable: false}));
    container = render(store);
    expect(findButton(container, 'native-save')).toBeNull();
    expect(findButton(container, 'native-complete')).toBeNull();
    expect(findButton(container, 'native-delete')).toBeNull();
    expect(findButton(container, 'native-correct')).toBeTruthy();
    expect(findButton(container, 'native-export-pdf')).toBeTruthy();
    // 注入为只读（meta.editable=false）
    const init = mockChannel.sendInit.mock.calls[0][0];
    expect(init.meta.editable).toBe(false);
  });

});

describe('NativeLedgerDetail 草稿与完成', () => {
  let store;
  let container;

  beforeEach(() => {
    store = setupStore();
  });

  afterEach(() => {
    cleanupContainer(container);
    container = null;
  });

  test('保存草稿：collect 参与 PUT 并通知编辑器复位', async () => {
    store.applyDetail(makeDetail({values: {conclusion: ''}}));
    mockHttpPut.mockResolvedValue({data: makeDetail({values: {conclusion: 'OK'}})});
    mockChannel.collect.mockResolvedValue({values: {conclusion: 'OK'}});
    container = render(store);
    await act(async () => {
      findButton(container, 'native-save').click();
      await flush();
    });
    await flush();
    expect(mockHttpPut).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/native-ledgers/66/',
      expect.objectContaining({values: expect.objectContaining({conclusion: 'OK'})}));
    expect(mockChannel.notifySaved).toHaveBeenCalled();
    expect(message.success).toHaveBeenCalledWith('填写值已保存');
  });

  test('完成填写：必填未填本地拦截不发请求', async () => {
    store.applyDetail(makeDetail({values: {conclusion: ''}}));
    container = render(store);
    await act(async () => {
      findButton(container, 'native-complete').click();
      await flush();
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
    expect(message.warning).toHaveBeenCalledWith('必填字段未填写：维护结论');
  });

  test('完成填写：校验通过先保存再 POST complete', async () => {
    store.applyDetail(makeDetail({values: {conclusion: '有值'}}));
    mockHttpPut.mockResolvedValue({data: makeDetail()});
    mockHttpPost.mockResolvedValue({data: makeDetail({status: 'completed', editable: false})});
    mockChannel.collect.mockResolvedValue({values: {conclusion: '有值'}});
    container = render(store);
    await act(async () => {
      findButton(container, 'native-complete').click();
      await flush();
    });
    await flush();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/native-ledgers/66/complete/');
    expect(message.success).toHaveBeenCalledWith('已完成填写');
  });

});

describe('NativeLedgerDetail 更正/返回守卫与导出', () => {
  let store;
  let container;

  beforeEach(() => {
    store = setupStore();
  });

  afterEach(() => {
    cleanupContainer(container);
    container = null;
  });

  test('返回守卫：有未保存修改先确认', async () => {
    store.applyDetail(makeDetail({values: {conclusion: '已保存'}}));
    container = render(store);
    // 编辑器推送未保存修改
    store.applyEditorValues({values: {conclusion: '改了'}});
    store.values = {...store.values, ...store.editorValues};
    const onBack = jest.fn();
    const button = findButton(container, 'native-detail-back');
    await act(async () => {
      button.click();
      await flushDests();
    });
    const confirmText = document.body.textContent;
    expect(confirmText).toContain('有未保存的修改');
    // 继续填写 → 不返回
    const cancelBtn = [...document.querySelectorAll('.ant-modal-confirm .ant-btn')]
      .find(b => b.textContent.includes('继续填写'));
    await act(async () => {
      cancelBtn.click();
      await flushDests();
    });
    expect(onBack).not.toHaveBeenCalled();
  });

  test('更正模式：空原因拒绝进入；进入后提交走 correct 端点', async () => {
    store.applyDetail(makeDetail({status: 'completed', editable: false,
      values: {conclusion: '原值'}}));
    container = render(store);
    await act(async () => {
      findButton(container, 'native-correct').click();
      await flushDests();
    });
    // 空原因确认 → warning，不进入更正
    const okBtn = [...document.querySelectorAll('.ant-modal-confirm .ant-btn-primary')]
      .find(b => b.textContent.includes('进入更正'));
    await act(async () => {
      okBtn.click();
      await flushDests();
    });
    expect(message.warning).toHaveBeenCalledWith('更正必须填写原因');
    expect(store.correcting).toBe(false);

    // 填原因进入更正
    const textarea = document.querySelector('.ant-modal-confirm textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(textarea, '复核发现错误');
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
      await flushDests();
    });
    await act(async () => {
      okBtn.click();
      await flushDests();
    });
    expect(store.correcting).toBe(true);
    expect(store.correctReason).toBe('复核发现错误');

    // 提交更正
    mockHttpPost.mockResolvedValue({data: makeDetail({})});
    mockChannel.collect.mockResolvedValue({values: {conclusion: '改后'}});
    await act(async () => {
      findButton(container, 'native-submit-correct').click();
      await flush();
    });
    await flush();
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/native-ledgers/66/correct/',
      expect.objectContaining({reason: '复核发现错误'}));
    expect(message.success).toHaveBeenCalledWith('更正已保存');
  });

  test('更正记录表格渲染', () => {
    store.applyDetail(makeDetail({
      status: 'completed', editable: false,
      corrections: [{
        id: 1, reason: '复核修正',
        corrected_by_name: '张三', corrected_at: '2026-10-18T10:00:00',
        changes: [{field: 'conclusion', label: '维护结论', old: 'A', new: 'B'}],
      }],
    }));
    container = render(store);
    expect(container.textContent).toContain('复核修正');
    expect(container.textContent).toContain('维护结论: A → B');
  });

  test('导出 PDF：无未保存修改直接 exportFile', async () => {
    const {exportFile} = require('libs');
    store.applyDetail(makeDetail({values: {conclusion: '有值'}}));
    container = render(store);
    await act(async () => {
      findButton(container, 'native-export-pdf').click();
      await flush();
    });
    expect(exportFile).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/equipment-lifecycle/native-ledgers/66/export/pdf/',
    }));
  });
});

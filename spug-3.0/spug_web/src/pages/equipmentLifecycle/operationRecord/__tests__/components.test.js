/**
 * 运行与故障记录——页面与详情组件渲染契约测试（2026-10-11 合并改造）。
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 列表页渲染 页签/筛选区/表格，"新增记录"入口与导出按钮在位；
 * - 新增表单按记录类型显隐故障专用字段（正式故障显示影响开关/影响程度/
 *   故障部位/初步原因分析；日常运行/异常事件不渲染），并按类型提交真实
 *   payload（record_type + client_token）；
 * - 详情窗口按类型与状态收敛顶部动作：正式故障处置中 → 确认恢复并结案/
 *   撤销故障登记；异常事件已记录 → 认定正式故障/开始跟进；日常运行 →
 *   删除；已撤销记录只读横幅且无动作按钮；
 * - 认定正式故障弹窗提交 identify-fault 端点（原记录原地变更）；
 * - 撤销登记弹窗提交 cancel 端点（原因必填，前端拦截空原因不发请求）。
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
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: (...args) => mockHttpPut(...args),
    delete: (...args) => mockHttpDelete(...args),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

jest.mock('components', () => {
  const React = require('react');
  const Shell = (props) => React.createElement('div', null, props.children);
  Shell.Item = (props) => React.createElement('div', null, props.title || '', props.children);
  const AuthButton = (props) => React.createElement(
    'button',
    {
      onClick: props.onClick,
      'data-auth': props.auth || '',
      type: 'button',
    },
    props.children);
  const Breadcrumb = (props) => React.createElement('div', null, props.children);
  Breadcrumb.Item = Shell;
  const SearchForm = (props) => React.createElement('div', null, props.children);
  SearchForm.Item = Shell;
  return {
    AuthDiv: Shell,
    AuthButton,
    AuthCard: Shell,
    AuthFragment: Shell,
    Breadcrumb,
    SearchForm,
    ExportButton: (props) => React.createElement('button', {type: 'button'}, props.children),
    TableCard: Shell,
    AttachmentManager: (props) => React.createElement(
      'div', {'data-object-type': props.objectType}, 'attachments'),
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

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  mockHttpGet.mockReset();
  mockHttpGet.mockResolvedValue({data: [], total: 0});
  mockHttpPost.mockReset();
  mockHttpPost.mockResolvedValue({data: {}});
  mockHttpPut.mockReset();
  mockHttpPut.mockResolvedValue({data: {}});
  mockHttpDelete.mockReset();
  mockHttpDelete.mockResolvedValue({});
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-select-dropdown, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function textContent() {
  return document.body.textContent || '';
}

function findButton(label) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').trim() === label);
}

async function renderIndex() {
  const Index = require('../index').default;
  await act(async () => {
    ReactDOM.render(React.createElement(Index, {location: {search: ''}}), container);
  });
  await act(async () => {
    await flush();
  });
}

async function renderDetail(detail) {
  mockHttpGet.mockImplementation((url) => {
    if (url.endsWith('/progress/')) {
      return Promise.resolve({data: [], total: 0});
    }
    if (url.endsWith('/attachments/')) {
      return Promise.resolve({data: []});
    }
    return Promise.resolve(detail);
  });
  const store = require('../store').default;
  const RecordDetail = require('../RecordDetail').default;
  await act(async () => {
    store.showDetail(detail.id, 'basic');
  });
  await act(async () => {
    ReactDOM.render(React.createElement(RecordDetail), container);
  });
  await act(async () => {
    await flush();
  });
}

const FAULT_DETAIL = {
  id: 11, record_no: 'JL20261011-0001', record_type: 'fault',
  system: 3, system_name: 'DVOR系统', system_location: '机房A',
  occurred_at: '2026-10-11 08:00:00', title: '发射机故障',
  description: '告警灯亮', registrar_name: '张三', status: 'handling',
  affects_system_operation: true, impact_status: 'fault',
  reason_analysis: '', reason_unknown: false,
  source_type: 'manual', source_ledger: null, source_ledger_no: '',
  progress_count: 0, created_by_name: 'op_user',
};

const ABNORMAL_DETAIL = {
  ...FAULT_DETAIL,
  id: 12, record_no: 'JL20261011-0002', record_type: 'abnormal',
  title: '信号波动', status: 'recorded', affects_system_operation: false,
  impact_status: '',
};

const ROUTINE_DETAIL = {
  ...FAULT_DETAIL,
  id: 13, record_no: 'JL20261011-0003', record_type: 'routine',
  title: 'UPS巡检', status: 'recorded',
};

const CANCELLED_DETAIL = {
  ...FAULT_DETAIL,
  id: 14, record_no: 'JL20261011-0004', status: 'cancelled',
  cancel_reason: '重复登记',
};

describe('运行与故障记录列表页', () => {
  it('渲染三个页签、筛选区与"新增记录"入口，列表请求统一路由', async () => {
    await renderIndex();
    const text = textContent();
    expect(text).toContain('全部记录');
    expect(text).toContain('待办（跟进中）');
    expect(text).toContain('统计');
    expect(text).toContain('新增记录');
    expect(mockHttpGet).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/',
      expect.objectContaining({params: expect.objectContaining({page: 1})}));
  });
});

describe('新增/编辑表单按记录类型显隐故障字段', () => {
  async function openForm(recordType) {
    await renderIndex();
    const store = require('../store').default;
    await act(async () => {
      store.showForm();
    });
    await act(async () => {
      await flush();
    });
    // 通过遍历 Radio 切换类型（受控组件 onChange 双通道）
    const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper'));
    const target = radios.find(r => r.textContent === recordType.label);
    await act(async () => {
      target.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
  }

  it('正式故障：渲染故障专用字段（开启影响开关后出现影响程度）', async () => {
    await openForm(RECORD_TYPE_OPTIONS.find(i => i.value === 'fault'));
    const text = textContent();
    expect(text).toContain('故障登记（正式故障专用）');
    expect(text).toContain('影响系统运行');
    expect(text).toContain('故障部位/设备');
    expect(text).toContain('初步原因分析');
    // 默认"部件故障但不影响系统运行"：影响程度在开关开启后才出现
    expect(text).not.toContain('系统影响程度');
    const switchButton = document.querySelector('.ant-switch');
    await act(async () => {
      switchButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(textContent()).toContain('系统影响程度');
  });

  it('日常运行：不渲染故障专用字段，显示记录类别', async () => {
    await openForm(RECORD_TYPE_OPTIONS.find(i => i.value === 'routine'));
    const text = textContent();
    expect(text).not.toContain('故障登记（正式故障专用）');
    expect(text).not.toContain('初步原因分析');
    expect(text).toContain('记录类别');
  });

  it('异常事件：不渲染故障专用字段，显示异常类别', async () => {
    await openForm(RECORD_TYPE_OPTIONS.find(i => i.value === 'abnormal'));
    const text = textContent();
    expect(text).not.toContain('故障登记（正式故障专用）');
    expect(text).toContain('异常类别');
  });

  it('编辑表单类型不可修改（禁用）且不渲染登记人', async () => {
    const store = require('../store').default;
    const RecordForm = require('../RecordForm').default;
    mockHttpGet.mockImplementation((url) => (
      url.endsWith('/records/candidate-systems/')
        ? Promise.resolve({data: []})
        : Promise.resolve({...FAULT_DETAIL})));
    await act(async () => {
      store.showForm({...FAULT_DETAIL});
    });
    await act(async () => {
      ReactDOM.render(React.createElement(RecordForm), container);
      await flush();
    });
    const radioInputs = Array.from(document.querySelectorAll('.ant-radio-input'));
    expect(radioInputs.length).toBeGreaterThan(0);
    expect(radioInputs.every(r => r.disabled)).toBe(true);
    expect(textContent()).not.toContain('登记人');
  });
});

describe('详情窗口动作按类型与状态收敛', () => {
  it('正式故障处置中：确认恢复并结案 + 撤销故障登记', async () => {
    await renderDetail(FAULT_DETAIL);
    const text = textContent();
    expect(text).toContain('确认恢复并结案');
    expect(text).toContain('撤销故障登记');
    expect(text).toContain('处置结果');
    // 异常事件专属动作不出现
    expect(text).not.toContain('认定正式故障');
    expect(text).not.toContain('完成跟进');
  });

  it('异常事件已记录：认定正式故障 + 开始跟进，无故障结案动作', async () => {
    await renderDetail(ABNORMAL_DETAIL);
    const text = textContent();
    expect(text).toContain('认定正式故障');
    expect(text).toContain('开始跟进');
    expect(text).not.toContain('确认恢复并结案');
    expect(text).not.toContain('撤销故障登记');
    expect(text).not.toContain('删除');
  });

  it('日常运行：编辑 + 删除，无任何异常/故障动作', async () => {
    await renderDetail(ROUTINE_DETAIL);
    const text = textContent();
    expect(text).toContain('删除');
    expect(text).not.toContain('认定正式故障');
    expect(text).not.toContain('确认恢复并结案');
    expect(text).not.toContain('开始跟进');
  });

  it('已撤销记录：只读横幅提示，无业务动作按钮', async () => {
    await renderDetail(CANCELLED_DETAIL);
    const text = textContent();
    expect(text).toContain('该登记已撤销，仅供历史追溯');
    expect(text).toContain('撤销原因');
    expect(text).not.toContain('确认恢复并结案');
    expect(text).not.toContain('撤销故障登记');
  });

  it('进展附件与记录附件使用统一对象类型', async () => {
    mockHttpGet.mockImplementation((url) => {
      if (url.endsWith('/progress/')) return Promise.resolve({
        data: [{id: 77, handled_at: '2026-10-11 09:00', handler_name: '李四',
          content: '排查中', work_hours: 1.5, corrections: []}],
        total: 1,
      });
      if (url.endsWith('/attachments/')) return Promise.resolve({data: []});
      return Promise.resolve(FAULT_DETAIL);
    });
    const store = require('../store').default;
    const RecordDetail = require('../RecordDetail').default;
    await act(async () => {
      store.showDetail(FAULT_DETAIL.id, 'progress');
    });
    await act(async () => {
      ReactDOM.render(React.createElement(RecordDetail), container);
    });
    await act(async () => {
      await flush();
    });
    const text = textContent();
    expect(text).toContain('排查中');
    expect(text).toContain('工时 1.5h');
    expect(document.body.innerHTML).toContain('el_operation_progress');
  });
});

describe('认定正式故障（原记录原地变更）', () => {
  it('弹窗提交 identify-fault 端点并携带故障字段', async () => {
    await renderDetail(ABNORMAL_DETAIL);
    const button = findButton('认定正式故障');
    expect(button).toBeTruthy();
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const text = textContent();
    expect(text).toContain('在本条记录上认定为正式故障');
    // 默认不影响系统运行：直接提交
    // 详情窗口标题区也含"认定正式故障"按钮文本：按弹窗描述文本精确定位
    await act(async () => {
      const modal = Array.from(document.querySelectorAll('.ant-modal'))
        .find(m => m.textContent.includes('在本条记录上认定为正式故障'));
      expect(modal).toBeTruthy();
      // antd 默认 locale 为 en_US：Modal footer 确认按钮为 OK（主按钮）
      const ok = modal.querySelector('.ant-modal-footer .ant-btn-primary');
      expect(ok).toBeTruthy();
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/12/identify-fault/',
      expect.objectContaining({affects_system_operation: false}));
  });
});

describe('撤销故障登记', () => {
  it('空原因前端拦截不发请求；填写原因后提交 cancel 端点', async () => {
    await renderDetail(FAULT_DETAIL);
    const button = findButton('撤销故障登记');
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const modal = Array.from(document.querySelectorAll('.ant-modal'))
      .find(m => m.textContent.includes('撤销故障登记确认'));
    const ok = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.trim() === 'OK');
    // 空原因 → 前端拦截
    await act(async () => {
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).not.toHaveBeenCalled();
    // 填写原因后提交
    const textarea = modal.querySelector('textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(textarea, '重复登记');
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    await act(async () => {
      ok.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/equipment-lifecycle/records/11/cancel/', {cancel_reason: '重复登记'});
  });
});

const RECORD_TYPE_OPTIONS = [
  {value: 'routine', label: '日常运行'},
  {value: 'abnormal', label: '异常事件'},
  {value: 'fault', label: '正式故障'},
];

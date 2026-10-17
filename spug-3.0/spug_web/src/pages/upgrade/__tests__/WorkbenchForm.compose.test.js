/**
 * 升级工作台表单组合渲染测试（2026-10 编号回归 + 门禁拆分重构）。
 *
 * 真实渲染 WorkbenchForm（ReactDOM + jsdom，仓库惯例），mock libs http 与
 * AttachmentManager，验证拆分后两个模式的组装完整性：
 * - 查看模式：头部信息栏（含编号/标题）、步骤清单、状态时间线、附件面板；
 * - 新建模式：基本信息/升级说明/初始化配置三张卡片。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => new Promise(() => {})),
    post: jest.fn(() => Promise.resolve()),
    put: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => ({
  AttachmentManager: () => <div>附件管理器</div>,
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
let store = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  store = require('../store').default;
  store.record = {};
  store.recordSteps = [];
  store.statusLogs = [];
  store.plans = [];
  store.systems = [];
  store.filterOptions = {phases: []};
  store.attachmentCount = 0;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  container = null;
  store = null;
});

function renderForm(props) {
  const WorkbenchForm = require('../WorkbenchForm').default;
  act(() => {
    ReactDOM.render(<WorkbenchForm {...props}/>, container);
  });
}

describe('WorkbenchForm 查看模式（拆分后组装）', () => {
  beforeEach(() => {
    store.record = {
      id: 1,
      upgrade_no: 'SJ20261001-0007',
      title: 'DVOR 软件升级',
      system_name: 'DVOR系统',
      system_id: 3,
      upgrade_type: '功能升级',
      upgrade_time: '2026-10-01 10:00:00',
      status: '处理中',
      owner: '张三',
      upgrade_content: '升级核心服务版本',
      impact_scope: '台站终端',
      risk_desc: '停机 10 分钟',
      rollback_plan: '回退到上一版本',
    };
    store.recordSteps = [{
      id: 11, sequence: 1, title: '备份数据库', status: 'pending',
      is_required: true, phase: '准备',
      description: '备份主库与备库数据',
    }];
    store.filterOptions = {phases: ['准备']};
  });

  it('信息栏展示标题/编号/主字段，打印按钮存在', () => {
    renderForm({isNew: false, recordId: '1'});
    expect(container.textContent).toContain('DVOR 软件升级');
    expect(container.textContent).toContain('SJ20261001-0007');
    expect(container.textContent).toContain('计划升级时间');
    expect(container.textContent).toContain('打印基本信息');
  });

  it('查看模式不渲染全局保存按钮与编辑面板（默认收起）', () => {
    renderForm({isNew: false, recordId: '1'});
    const buttons = Array.from(container.querySelectorAll('button'))
      .map(b => b.textContent);
    expect(buttons).not.toContain('保存');
    expect(buttons).not.toContain('保存修改');
    // 编辑面板默认收起，入口存在
    expect(buttons.some(t => t.includes('编辑基本信息'))).toBe(true);
    expect(container.textContent).not.toContain('保存修改');
  });

  it('详细说明默认收起，展开后只读展示四段说明', () => {
    renderForm({isNew: false, recordId: '1'});
    expect(container.textContent).not.toContain('升级核心服务版本');
    const toggle = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.includes('详细说明'));
    act(() => {
      toggle.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    });
    expect(container.textContent).toContain('升级核心服务版本');
    expect(container.textContent).toContain('台站终端');
    expect(container.textContent).toContain('回退到上一版本');
    // 再次点击收起
    const toggleAgain = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.includes('收起详细说明'));
    act(() => {
      toggleAgain.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    });
    expect(container.textContent).not.toContain('升级核心服务版本');
  });

  it('步骤清单与状态时间线面板均挂载，当前阶段在流程区展示', () => {
    renderForm({isNew: false, recordId: '1'});
    expect(container.textContent).toContain('步骤清单');
    expect(container.textContent).toContain('备份数据库');
    expect(container.textContent).toContain('状态时间线');
    expect(container.textContent).toContain('附件');
    // 唯一阶段"准备"有未完成步骤 → 流程区显示当前阶段
    expect(container.textContent).toContain('当前阶段：【准备】');
    // 说明可展开
    const descBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent === '说明');
    act(() => {
      descBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    });
    expect(container.textContent).toContain('备份主库与备库数据');
  });
});

describe('WorkbenchForm 新建模式', () => {
  it('渲染基本信息/升级说明/初始化配置三张卡片', () => {
    renderForm({isNew: true});
    expect(container.textContent).toContain('基本信息');
    expect(container.textContent).toContain('升级说明');
    expect(container.textContent).toContain('初始化配置');
  });
});

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
    };
    store.recordSteps = [{
      id: 11, sequence: 1, title: '备份数据库', status: 'pending',
      is_required: true, phase: '准备',
    }];
    store.filterOptions = {phases: ['准备']};
  });

  it('头部展示编号与基本信息，打印按钮存在', () => {
    renderForm({isNew: false, recordId: '1'});
    expect(container.textContent).toContain('编号：');
    expect(container.textContent).toContain('SJ20261001-0007');
    expect(container.textContent).toContain('DVOR 软件升级');
    expect(container.textContent).toContain('打印基本信息');
  });

  it('步骤清单与状态时间线面板均挂载', () => {
    renderForm({isNew: false, recordId: '1'});
    expect(container.textContent).toContain('步骤清单');
    expect(container.textContent).toContain('备份数据库');
    expect(container.textContent).toContain('状态时间线');
    expect(container.textContent).toContain('附件');
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

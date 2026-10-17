/**
 * 升级工作台步骤清单行为测试（2026-10-15 体验改造）。
 *
 * 真实渲染 WorkbenchForm（ReactDOM + jsdom），验证：
 * - 当前阶段分组：分组头出现"当前阶段"标记（复用 computeStepFlowState，不另加判断）；
 * - 待执行步骤：行内"完成"为主操作，真实提交 PUT；"更多"菜单收纳跳过/删除（权限）；
 * - 已完成步骤：无"完成"按钮，"更多"菜单含重置（step_reset 权限）；
 * - 说明展开/收起；"定位待执行"仅在存在待执行步骤时出现；
 * - 完成提交失败：保持现场不提示成功（错误提示由 http 拦截器弹一次）。
 *
 * jsdom 约定：antd Dropdown 用 trigger=['click']，点击后 flush 等待门户渲染；
 * scrollIntoView 无布局，测试中打桩断言被调用。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => new Promise(() => {})),
    post: jest.fn(() => Promise.resolve({})),
    put: jest.fn(() => Promise.resolve({})),
    delete: jest.fn(() => Promise.resolve({})),
  },
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => ({
  AttachmentManager: () => <div>附件管理器</div>,
}));

jest.mock('antd', () => {
  const actual = jest.requireActual('antd');
  return {
    ...actual,
    message: {
      success: jest.fn(),
      error: jest.fn(),
      warning: jest.fn(),
      info: jest.fn(),
      confirm: jest.fn(),
    },
  };
});

const {http, hasPermission} = require('libs');
const {message} = require('antd');
const store = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const STEPS = [
  {id: 11, sequence: 1, phase: '备份', title: '备份数据库', status: 'completed',
    is_required: true, completed_by: '张三', completed_at: '2026-10-15 09:00:00'},
  {id: 12, sequence: 2, phase: '灰度发布', title: '执行数据库脚本', status: 'pending',
    is_required: true, description: '依次执行 3 个升级脚本'},
];

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  store.record = {
    id: 1, upgrade_no: 'SJ20261001-0007', title: 'DVOR 软件升级',
    system_name: 'DVOR系统', system_id: 3, upgrade_type: '功能升级',
    upgrade_time: '2026-10-01 10:00:00', status: '处理中', owner: '张三',
  };
  store.recordSteps = STEPS.map(s => ({...s}));
  store.recordStepStats = {total: 2, completed: 1, skipped: 0, pending: 1};
  store.statusLogs = [];
  store.plans = [];
  store.systems = [];
  store.filterOptions = {phases: ['备份', '灰度发布']};
  store.attachmentCount = 0;
  hasPermission.mockReturnValue(true);
  window.Element.prototype.scrollIntoView = jest.fn();
});

afterEach(async () => {
  await act(async () => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  container = null;
});

function renderForm() {
  const WorkbenchForm = require('../WorkbenchForm').default;
  act(() => {
    ReactDOM.render(<WorkbenchForm isNew={false} recordId="1"/>, container);
  });
}

function findButton(text, root = container) {
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s/g, '') === text);
}

async function clickButton(text, root = container) {
  const btn = findButton(text, root);
  if (!btn) throw new Error(`button not found: ${text}`);
  await act(async () => {
    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    await flush();
  });
  return btn;
}

describe('当前阶段分组标记', () => {
  it('待执行阶段分组头出现"当前阶段"文字与高亮类，已完成阶段没有', () => {
    renderForm();
    const headers = Array.from(container.querySelectorAll('[class*="stepGroupHeader"]'));
    const currentHeader = headers.find(h => h.textContent.includes('灰度发布'));
    const doneHeader = headers.find(h => h.textContent.includes('备份'));
    expect(currentHeader).toBeDefined();
    expect(currentHeader.textContent).toContain('当前阶段');
    expect(currentHeader.className).toContain('stepGroupHeaderCurrent');
    expect(doneHeader.className).not.toContain('stepGroupHeaderCurrent');
    expect(doneHeader.textContent).not.toContain('当前阶段');
  });
});

describe('待执行步骤操作', () => {
  it('行内"完成"为唯一主操作按钮，点击真实提交 PUT', async () => {
    renderForm();
    http.put.mockResolvedValue({});
    const rows = Array.from(container.querySelectorAll('[data-step-id]'));
    const pendingRow = rows.find(r => r.dataset.stepId === '12');
    const completeBtn = Array.from(pendingRow.querySelectorAll('button'))
      .find(b => b.textContent.includes('完成'));
    expect(completeBtn).toBeDefined();
    await clickButton('完成', pendingRow);
    await act(async () => { await flush(); await flush(); });
    expect(http.put).toHaveBeenCalledWith(
      '/api/upgrade/record-steps/12/update/', {action: 'complete'});
    expect(message.success).toHaveBeenCalledWith('步骤已标记为完成');
  });

  it('"更多"菜单收纳跳过/删除（有删除权限），不含重置', async () => {
    renderForm();
    const rows = Array.from(container.querySelectorAll('[data-step-id]'));
    const pendingRow = rows.find(r => r.dataset.stepId === '12');
    const moreBtn = pendingRow.querySelector('[aria-label="步骤2更多操作"]');
    expect(moreBtn).not.toBeNull();
    await act(async () => {
      moreBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
      await flush();
      await flush();
    });
    const menu = Array.from(document.querySelectorAll('.ant-dropdown-menu'))
      .find(m => m.offsetParent !== null || m.textContent.includes('跳过'));
    expect(menu).toBeDefined();
    expect(menu.textContent).toContain('跳过');
    expect(menu.textContent).toContain('删除');
    expect(menu.textContent).not.toContain('重置');
  });

  it('无删除权限时"更多"菜单不含删除项', async () => {
    hasPermission.mockImplementation(
      (code) => code !== 'upgrade.upgrade.step_del');
    renderForm();
    const rows = Array.from(container.querySelectorAll('[data-step-id]'));
    const pendingRow = rows.find(r => r.dataset.stepId === '12');
    const moreBtn = pendingRow.querySelector('[aria-label="步骤2更多操作"]');
    await act(async () => {
      moreBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
      await flush();
      await flush();
    });
    const menu = Array.from(document.querySelectorAll('.ant-dropdown-menu'))
      .find(m => m.textContent.includes('跳过'));
    expect(menu).toBeDefined();
    expect(menu.textContent).not.toContain('删除');
  });

  it('完成提交失败保持现场：无成功提示，错误只提示一次', async () => {
    renderForm();
    const rows = Array.from(container.querySelectorAll('[data-step-id]'));
    const pendingRow = rows.find(r => r.dataset.stepId === '12');
    http.put.mockImplementation(() => {
      // 模拟 http 拦截器：真实错误提示一次后 reject
      message.error('请求失败: 500');
      return Promise.reject('请求失败: 500');
    });
    await clickButton('完成', pendingRow);
    await act(async () => { await flush(); await flush(); });
    expect(message.error).toHaveBeenCalledTimes(1);
    expect(message.success).not.toHaveBeenCalled();
  });
});

describe('已完成步骤操作', () => {
  it('无"完成"按钮；"更多"菜单含重置（step_reset）与删除', async () => {
    renderForm();
    const rows = Array.from(container.querySelectorAll('[data-step-id]'));
    const doneRow = rows.find(r => r.dataset.stepId === '11');
    expect(Array.from(doneRow.querySelectorAll('button'))
      .find(b => b.textContent.includes('完成'))).toBeUndefined();
    const moreBtn = doneRow.querySelector('[aria-label="步骤1更多操作"]');
    await act(async () => {
      moreBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
      await flush();
      await flush();
    });
    const menu = Array.from(document.querySelectorAll('.ant-dropdown-menu'))
      .find(m => m.textContent.includes('重置'));
    expect(menu).toBeDefined();
    expect(menu.textContent).toContain('删除');
    expect(menu.textContent).not.toContain('跳过');
  });

  it('无 step_reset 权限时菜单只有删除', async () => {
    hasPermission.mockImplementation(
      (code) => code !== 'upgrade.upgrade.step_reset');
    renderForm();
    const rows = Array.from(container.querySelectorAll('[data-step-id]'));
    const doneRow = rows.find(r => r.dataset.stepId === '11');
    const moreBtn = doneRow.querySelector('[aria-label="步骤1更多操作"]');
    await act(async () => {
      moreBtn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
      await flush();
      await flush();
    });
    const menu = Array.from(document.querySelectorAll('.ant-dropdown-menu'))
      .find(m => m.textContent.includes('删除'));
    expect(menu).toBeDefined();
    expect(menu.textContent).not.toContain('重置');
  });
});

describe('说明展开与定位待执行', () => {
  it('点击"说明"展开描述，点击"收起说明"折叠', async () => {
    renderForm();
    expect(container.textContent).not.toContain('依次执行 3 个升级脚本');
    await clickButton('说明');
    expect(container.textContent).toContain('依次执行 3 个升级脚本');
    await clickButton('收起说明');
    expect(container.textContent).not.toContain('依次执行 3 个升级脚本');
  });

  it('"定位待执行"仅在存在待执行步骤时出现，点击调用 scrollIntoView', async () => {
    renderForm();
    expect(container.textContent).toContain('定位待执行');
    await clickButton('定位待执行');
    expect(window.Element.prototype.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({block: 'nearest'}));

    // 全部完成后入口消失
    store.recordSteps = STEPS.map(s => ({...s, status: 'completed'}));
    await act(async () => { await flush(); });
    expect(container.textContent).not.toContain('定位待执行');
  });
});

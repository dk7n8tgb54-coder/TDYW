/**
 * 升级工作台状态时间线行为测试（2026-10-15 体验改造）。
 *
 * 真实渲染 WorkbenchForm（ReactDOM + jsdom），验证：
 * - 日志以事件结果为一级文案：phase_done → "备份阶段已完成/未通过/已撤销"，
 *   不再重复 ✓ 图标与额外标签；回退/失败保留区分；
 * - 流程区标题展示当前阶段（flowHeadline）；
 * - "阶段操作"菜单按真实状态生成（当前阶段暂停/标记失败 + 可回退目标）；
 * - 完成节点点击弹出回退确认：预览目标阶段、将被重置的阶段与步骤数量，
 *   基于真实步骤数据（口径与后端 _reset_steps_for_rollback 一致）；
 * - 新日志短暂高亮；用户滚离顶部时不抢滚动，显示"有新记录"按钮。
 *
 * jsdom 约定：scrollTop 无布局，用 Object.defineProperty 打桩；
 * Modal.confirm 以 jest.fn 捕获参数，content 用 renderToStaticMarkup 断言。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import ReactDOMServer from 'react-dom/server';

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
      success: jest.fn(), error: jest.fn(),
      warning: jest.fn(), info: jest.fn(), confirm: jest.fn(),
    },
    // Modal 组件本体保留（AddStepModal 等真实渲染），静态 confirm 由测试 spyOn 拦截
  };
});

const {http, hasPermission} = require('libs');
const antd = require('antd');
const {message} = antd;
const store = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;
let confirmSpy = null;
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

const STEPS = [
  {id: 11, sequence: 1, phase: '备份', title: '备份数据库', status: 'completed',
    is_required: true, completed_by: '张三', completed_at: '2026-10-15 09:00:00'},
  {id: 12, sequence: 2, phase: '灰度发布', title: '执行数据库脚本', status: 'pending',
    is_required: true},
];

const LOG_BASE = {operator_name: '张三', created_at: '2026-10-15 09:00:00'};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  // Modal.confirm 以 spyOn 拦截（Modal 组件本体保持真实，供 AddStepModal 渲染）
  confirmSpy = jest.spyOn(antd.Modal, 'confirm').mockImplementation(() => {});
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
});

afterEach(async () => {
  await act(async () => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  container = null;
  if (confirmSpy) {
    confirmSpy.mockRestore();
    confirmSpy = null;
  }
});

function renderForm() {
  const WorkbenchForm = require('../WorkbenchForm').default;
  act(() => {
    ReactDOM.render(<WorkbenchForm isNew={false} recordId="1"/>, container);
  });
}

function findButton(text) {
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s/g, '') === text);
}

async function clickButton(text) {
  const btn = findButton(text);
  if (!btn) throw new Error(`button not found: ${text}`);
  await act(async () => {
    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
    await flush();
    await flush();
  });
  return btn;
}

describe('日志条目事件结果文案', () => {
  it('phase_done 完成展示"备份阶段已完成"，不重复 ✓ 与已失败标签', () => {
    store.statusLogs = [{...LOG_BASE, id: 1, action: 'phase_done', phase: '备份',
      outcome: 'done'}];
    renderForm();
    expect(container.textContent).toContain('备份阶段已完成');
    expect(container.textContent).not.toContain('✓');
  });

  it('phase_done 失败/撤销分别展示未通过/已撤销并弱化撤销条目', () => {
    store.statusLogs = [
      {...LOG_BASE, id: 2, action: 'phase_done', phase: '备份', outcome: 'revoked'},
      {...LOG_BASE, id: 1, action: 'phase_done', phase: '备份', outcome: 'done'},
    ];
    renderForm();
    expect(container.textContent).toContain('备份阶段已撤销');
    const revokedRow = Array.from(container.querySelectorAll('[class*="logRow"]'))
      .find(el => el.textContent.includes('已撤销'));
    expect(revokedRow.style.opacity).toBe('0.55');
  });

  it('rollback 日志保留"回退到"关键区别', () => {
    store.statusLogs = [{...LOG_BASE, id: 3, action: 'rollback',
      target_action_text: '备份', from_status: '处理中', to_status: '已回退'}];
    renderForm();
    expect(container.textContent).toContain('回退到：备份');
    expect(container.textContent).toContain('处理中→已回退');
  });

  it('操作人与时间为次要信息，备注保持可读', () => {
    store.statusLogs = [{...LOG_BASE, id: 4, action: 'start', action_text: '升级启动',
      remark: '今晚 22:00 开始窗口'}];
    renderForm();
    expect(container.textContent).toContain('张三 · 2026-10-15 09:00:00');
    expect(container.textContent).toContain('今晚 22:00 开始窗口');
  });
});

describe('流程区与阶段操作菜单', () => {
  it('流程区展示当前阶段标题', () => {
    renderForm();
    expect(container.textContent).toContain('当前阶段：【灰度发布】');
  });

  it('"阶段操作"菜单按真实状态生成暂停/标记失败/回退项', async () => {
    renderForm();
    await clickButton('阶段操作');
    const menu = Array.from(document.querySelectorAll('.ant-dropdown-menu'))
      .find(m => m.textContent.includes('当前阶段'));
    expect(menu).toBeDefined();
    expect(menu.textContent).toContain('暂停【灰度发布】');
    expect(menu.textContent).toContain('标记【灰度发布】失败');
    expect(menu.textContent).toContain('回退到【备份】');
  });

  it('无编辑权限时无阶段操作菜单与节点交互', () => {
    hasPermission.mockImplementation((code) => code !== 'upgrade.upgrade.edit');
    renderForm();
    expect(findButton('阶段操作')).toBeUndefined();
    const node = Array.from(container.querySelectorAll('[class*="nodeClickable"]'));
    expect(node).toHaveLength(0);
  });
});

describe('回退确认预览（真实步骤数据）', () => {
  it('完成节点点击弹出确认：目标阶段/重置阶段/步骤数与后端口径一致', async () => {
    renderForm();
    // completed 节点（备份）可点击回退
    const node = Array.from(container.querySelectorAll('[class*="nodeClickable"]'))
      .find(el => el.textContent.includes('备份'));
    expect(node).toBeDefined();
    await act(async () => {
      node.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
      await flush();
    });
    expect(antd.Modal.confirm).toHaveBeenCalledTimes(1);
    const options = antd.Modal.confirm.mock.calls[0][0];
    expect(options.title).toBe('回退到【备份】');
    expect(options.okText).toBe('确认回退');
    expect(options.okButtonProps.danger).toBe(true);
    const html = ReactDOMServer.renderToStaticMarkup(options.content);
    // 目标=备份，其后阶段=灰度发布，共 2 个步骤（真实步骤数据）
    expect(html).toContain('将回退到阶段');
    expect(html).toContain('备份');
    expect(html).toContain('灰度发布');
    expect(html).toContain('2 个步骤');
  });

  it('确认后真实提交 rollback 请求', async () => {
    renderForm();
    http.post.mockResolvedValue({id: 99});
    const node = Array.from(container.querySelectorAll('[class*="nodeClickable"]'))
      .find(el => el.textContent.includes('备份'));
    await act(async () => {
      node.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
      await flush();
    });
    const options = antd.Modal.confirm.mock.calls[0][0];
    await act(async () => {
      await options.onOk();
      await flush();
      await flush();
    });
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/status-logs/',
      expect.objectContaining({action: 'rollback', target_action: '备份'}));
  });
});

describe('新日志高亮与不抢滚动', () => {
  function scrollEl() {
    return container.querySelector('[class*="timelineScroll"]');
  }

  it('首次加载不高亮；顶部出现新日志时短暂高亮', async () => {
    jest.useFakeTimers();
    try {
      // 模拟真实挂载时序：日志随初始化加载完成后再渲染（首载不高亮）
      const firstLog = {...LOG_BASE, id: 1, action: 'start', action_text: '升级启动'};
      store.statusLogs = [firstLog];
      renderForm();
      expect(container.querySelectorAll('[class*="logItemHighlight"]')).toHaveLength(0);

      const newLog = {...LOG_BASE, id: 2, action: 'phase_done', phase: '备份',
        outcome: 'done'};
      await act(async () => {
        store.statusLogs = [newLog, firstLog];
      });
      expect(container.querySelectorAll('[class*="logItemHighlight"]')).toHaveLength(1);

      // 2.2s 后高亮清除
      act(() => {
        jest.advanceTimersByTime(2300);
      });
      expect(container.querySelectorAll('[class*="logItemHighlight"]')).toHaveLength(0);
    } finally {
      jest.useRealTimers();
    }
  });

  it('用户滚离顶部时不强跳：scrollTop 保持，显示"有新记录"按钮', async () => {
    renderForm();
    const firstLog = {...LOG_BASE, id: 1, action: 'start', action_text: '升级启动'};
    await act(async () => {
      store.statusLogs = [firstLog];
      await flush();
    });
    // jsdom 无布局：为实例打桩 scrollTop
    const el = scrollEl();
    Object.defineProperty(el, 'scrollTop', {value: 100, writable: true, configurable: true});

    const newLog = {...LOG_BASE, id: 2, action: 'phase_done', phase: '备份',
      outcome: 'done'};
    await act(async () => {
      store.statusLogs = [newLog, firstLog];
      await flush();
    });
    expect(findButton('有新记录')).toBeDefined();
    expect(el.scrollTop).toBe(100);

    // 点击按钮回到顶部并清除提示
    await clickButton('有新记录');
    expect(el.scrollTop).toBe(0);
    expect(findButton('有新记录')).toBeUndefined();
  });

  it('用户在顶部时新日志不出现"有新记录"按钮', async () => {
    renderForm();
    const firstLog = {...LOG_BASE, id: 1, action: 'start', action_text: '升级启动'};
    await act(async () => {
      store.statusLogs = [firstLog];
      await flush();
    });
    const el = scrollEl();
    Object.defineProperty(el, 'scrollTop', {value: 0, writable: true, configurable: true});
    const newLog = {...LOG_BASE, id: 2, action: 'phase_done', phase: '备份',
      outcome: 'done'};
    await act(async () => {
      store.statusLogs = [newLog, firstLog];
      await flush();
    });
    expect(findButton('有新记录')).toBeUndefined();
  });

  it('删除日志导致顶部变化不误报为新增', async () => {
    renderForm();
    const logA = {...LOG_BASE, id: 1, action: 'start', action_text: '升级启动'};
    const logB = {...LOG_BASE, id: 2, action: 'pause', action_text: '已暂停'};
    await act(async () => {
      store.statusLogs = [logB, logA];
      await flush();
    });
    const el = scrollEl();
    Object.defineProperty(el, 'scrollTop', {value: 100, writable: true, configurable: true});
    await act(async () => {
      store.statusLogs = [logA];
      await flush();
    });
    expect(findButton('有新记录')).toBeUndefined();
  });
});

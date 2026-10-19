/**
 * 升级工作台状态时间线行为测试（2026-10-15 体验改造）。
 *
 * 真实渲染 WorkbenchForm（ReactDOM + jsdom），验证：
 * - 日志为两行主结构：第一行事件标题（phase_done → "备份阶段完成/完成 · 已失效/完成 · 已撤销"，
 *   回退目标/失败阶段融入标题），第二行操作人/时间；时间线内不再使用彩色 Tag；
 *   真实失败(test_fail)红色、暂停/回退橙色、撤销/失效灰色；
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

/** 在指定弹窗（默认最后一个 .ant-modal）内按文本点击按钮 */
async function clickModalButton(text, modalEl) {
  const modal = modalEl || Array.from(document.querySelectorAll('.ant-modal')).pop();
  const btn = Array.from(modal.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s/g, '') === text.replace(/\s/g, ''));
  if (!btn) throw new Error(`modal button not found: ${text}`);
  await act(async () => {
    btn.click();
    await flush();
    await flush();
  });
  return btn;
}

describe('日志条目两行主结构与事件标题', () => {
  it('phase_done 完成展示"备份阶段完成"，标题为普通文本（时间线内无彩色 Tag）', () => {
    store.statusLogs = [{...LOG_BASE, id: 1, action: 'phase_done', phase: '备份',
      outcome: 'done'}];
    renderForm();
    expect(container.textContent).toContain('备份阶段完成');
    expect(container.textContent).not.toContain('✓');
    const timeline = container.querySelector('[class*="timelineScroll"]');
    expect(timeline.querySelectorAll('.ant-tag')).toHaveLength(0);
    // 常规完成：蓝色圆点，标题不带特殊着色类
    expect(timeline.querySelector('.ant-timeline-item-head-blue')).not.toBeNull();
    expect(timeline.querySelector(
      '[class*="logTitleDanger"], [class*="logTitleWarn"], [class*="logTitleMuted"]')).toBeNull();
  });

  it('phase_done 失效展示"完成 · 已失效"灰色弱化，不显示"未通过"', () => {
    store.statusLogs = [
      {...LOG_BASE, id: 2, action: 'phase_done', phase: '备份', outcome: 'failed'},
      {...LOG_BASE, id: 1, action: 'phase_done', phase: '备份', outcome: 'done'},
    ];
    renderForm();
    expect(container.textContent).toContain('备份阶段完成 · 已失效');
    expect(container.textContent).not.toContain('未通过');
    const failedRow = Array.from(container.querySelectorAll('[class*="logRow"]'))
      .find(el => el.textContent.includes('已失效'));
    expect(failedRow.querySelector('[class*="logTitleMuted"]')).not.toBeNull();
    expect(failedRow.style.opacity).toBe('0.55');
    expect(failedRow.closest('.ant-timeline-item')
      .querySelector('.ant-timeline-item-head-gray')).not.toBeNull();
  });

  it('phase_done 撤销展示"完成 · 已撤销"并弱化', () => {
    store.statusLogs = [
      {...LOG_BASE, id: 3, action: 'phase_done', phase: '备份', outcome: 'revoked'},
      {...LOG_BASE, id: 1, action: 'phase_done', phase: '备份', outcome: 'done'},
    ];
    renderForm();
    expect(container.textContent).toContain('备份阶段完成 · 已撤销');
    const revokedRow = Array.from(container.querySelectorAll('[class*="logRow"]'))
      .find(el => el.textContent.includes('已撤销'));
    expect(revokedRow.style.opacity).toBe('0.55');
  });

  it('阶段名自带"阶段"后缀时不重复追加（无"阶段阶段"）', () => {
    store.statusLogs = [{...LOG_BASE, id: 4, action: 'phase_done', phase: '备份阶段',
      outcome: 'done'}];
    renderForm();
    expect(container.textContent).toContain('备份阶段完成');
    expect(container.textContent).not.toContain('阶段阶段');
  });

  it('rollback 标题融入回退目标"回退至「备份」"，状态变化保留为辅助行，橙色基调', () => {
    store.statusLogs = [{...LOG_BASE, id: 5, action: 'rollback', action_text: '回退',
      target_action_text: '备份', from_status: '处理中', to_status: '已回退'}];
    renderForm();
    expect(container.textContent).toContain('回退至「备份」');
    expect(container.textContent).not.toContain('回退到：');
    expect(container.textContent).toContain('处理中→已回退');
    const row = Array.from(container.querySelectorAll('[class*="logRow"]'))
      .find(el => el.textContent.includes('回退至'));
    expect(row.querySelector('[class*="logTitleWarn"]')).not.toBeNull();
    // 橙色圆点为自定义色：antd 以内联样式渲染（cssstyle 可能归一化为 rgb）
    const dot = row.closest('.ant-timeline-item').querySelector('.ant-timeline-item-head');
    expect(['rgb(250, 140, 22)', '#fa8c16']).toContain(dot.style.borderColor);
  });

  it('test_fail 明确显示失败并保留失败阶段信息（红色基调）', () => {
    store.statusLogs = [{...LOG_BASE, id: 6, action: 'test_fail', action_text: '升级测试失败',
      phase: '灰度发布', remark: '脚本执行报错'}];
    renderForm();
    expect(container.textContent).toContain('升级测试未通过（失败阶段：灰度发布）');
    const row = Array.from(container.querySelectorAll('[class*="logRow"]'))
      .find(el => el.textContent.includes('升级测试未通过'));
    expect(row.querySelector('[class*="logTitleDanger"]')).not.toBeNull();
    expect(row.closest('.ant-timeline-item')
      .querySelector('.ant-timeline-item-head-red')).not.toBeNull();
    expect(container.textContent).toContain('脚本执行报错');
  });

  it('操作人与时间为第二行次要信息，备注保持可读', () => {
    store.statusLogs = [{...LOG_BASE, id: 7, action: 'start', action_text: '升级启动',
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

  it('"阶段操作"菜单生成标记失败与重新执行项（暂停/继续已下线）', async () => {
    renderForm();
    await clickButton('阶段操作');
    const menu = Array.from(document.querySelectorAll('.ant-dropdown-menu'))
      .find(m => m.textContent.includes('当前阶段'));
    expect(menu).toBeDefined();
    expect(menu.textContent).toContain('标记【灰度发布】失败');
    expect(menu.textContent).toContain('从【备份】重新执行');
    expect(menu.textContent).not.toContain('暂停');
    expect(menu.textContent).not.toContain('继续');
  });

  it('完成节点不再直点回退；仅当前阶段节点保留"标记失败"交互', () => {
    renderForm();
    const clickable = Array.from(container.querySelectorAll('[class*="nodeClickable"]'));
    // 仅当前阶段（灰度发布）节点可点（标记失败菜单），已完成阶段（备份）不可点
    expect(clickable).toHaveLength(1);
    expect(clickable[0].textContent).toContain('灰度发布');
    expect(clickable[0].textContent).not.toContain('备份');
  });

  it('无编辑权限时无阶段操作菜单与节点交互', () => {
    hasPermission.mockImplementation((code) => code !== 'upgrade.upgrade.edit');
    renderForm();
    expect(findButton('阶段操作')).toBeUndefined();
    const node = Array.from(container.querySelectorAll('[class*="nodeClickable"]'));
    expect(node).toHaveLength(0);
  });
});

describe('从「某阶段」重新执行（RedoFromModal）', () => {
  const PREVIEW = {
    target_phase: '备份',
    phases: [
      {name: '备份', total: 1, to_reset: 1, pending: 0},
      {name: '灰度发布', total: 1, to_reset: 0, pending: 1},
    ],
    selected_count: 1,
    later_completed_phases: [],
    pending_failures: [],
  };

  function mockPreview(overrides = {}) {
    http.get.mockImplementation((url) => {
      if (url.includes('/redo-preview/')) {
        return Promise.resolve({...PREVIEW, ...overrides});
      }
      if (url.includes('/status-logs/')) return Promise.resolve([]);
      if (url.includes('/steps/')) {
        return Promise.resolve({steps: STEPS.map(s => ({...s})),
          stats: {total: 2, completed: 1, skipped: 0, pending: 1}});
      }
      if (url.includes('/failures/')) return Promise.resolve([]);
      if (url.includes('/records/1/')) return Promise.resolve(store.record);
      return Promise.resolve({});
    });
  }

  /** 打开"从【备份】重新执行"弹窗（预览 mock 可覆盖） */
  async function openRedoModal(overrides = {}) {
    mockPreview(overrides);
    renderForm();
    await clickButton('阶段操作');
    const item = Array.from(document.querySelectorAll('.ant-dropdown-menu-item'))
      .find(el => el.textContent.includes('从【备份】重新执行'));
    await act(async () => {
      item.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    return document.querySelector('.ant-modal');
  }

  it('菜单打开重新执行弹窗：预览来自后端接口，展示影响范围', async () => {
    const modal = await openRedoModal();
    expect(http.get).toHaveBeenCalledWith(expect.stringContaining('redo-preview'));
    expect(http.get).toHaveBeenCalledWith(expect.stringContaining('target_phase='));
    expect(modal.textContent).toContain('从「备份」重新执行');
    expect(modal.textContent).toContain('只重置工作清单');
    expect(modal.textContent).toContain('1');
  });

  it('确认后提交 redo-execute；取消不产生任何请求', async () => {
    let modal = await openRedoModal();
    // 取消：不发请求（测试环境 antd 默认 en locale，按钮为 Cancel）
    await clickModalButton('Cancel', modal);
    expect(http.post).not.toHaveBeenCalled();

    // 重新打开并确认
    modal = await openRedoModal();
    http.post.mockResolvedValue({id: 66});
    await clickModalButton('确认重新执行', modal);
    await flush();
    await flush();
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/redo-execute/',
      expect.objectContaining({target_phase: '备份', later_action: 'redo'}));
  });

  it('存在后续已完成阶段时选择"保留"：未填理由确认禁用', async () => {
    const modal = await openRedoModal({later_completed_phases: ['灰度发布']});
    expect(modal.textContent).toContain('后续已完成阶段');
    const keepRadio = Array.from(modal.querySelectorAll('.ant-radio-wrapper'))
      .find(r => r.textContent.includes('保留后续结果'));
    await act(async () => {
      keepRadio.querySelector('input').click();
      await flush();
    });
    const okBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s/g, '') === '确认重新执行');
    expect(okBtn.disabled).toBe(true);
  });

  it('保留后续结果填写理由后可提交，提交携带 keep 与理由', async () => {
    const modal = await openRedoModal({later_completed_phases: ['灰度发布']});
    const keepRadio = Array.from(modal.querySelectorAll('.ant-radio-wrapper'))
      .find(r => r.textContent.includes('保留后续结果'));
    await act(async () => {
      keepRadio.querySelector('input').click();
      await flush();
    });
    const reasonInput = modal.querySelector('textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(reasonInput, '后续结果经验证仍有效');
      reasonInput.dispatchEvent(new Event('input', {bubbles: true}));
      await flush();
    });
    const okBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s/g, '') === '确认重新执行');
    expect(okBtn.disabled).toBe(false);
    http.post.mockResolvedValue({id: 67});
    await act(async () => {
      okBtn.click();
      await flush();
      await flush();
    });
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/redo-execute/',
      expect.objectContaining({later_action: 'keep', later_reason: '后续结果经验证仍有效'}));
  });
});

describe('失败处理闭环（处理失败弹窗）', () => {
  const FAILURE = {
    id: 9, upgrade_id: 1, phase: '灰度发布', status: 'pending',
    status_display: '失败待处理', reason: '灰度指标异常',
    failed_by_name: '张三', failed_at: '2026-10-18 10:00:00',
    redo_selected_count: 0, redo_reset_count: 0,
  };

  function mockWithFailure(failureStatus = 'pending') {
    http.get.mockImplementation((url) => {
      if (url.includes('/status-logs/')) return Promise.resolve([]);
      if (url.includes('/steps/')) {
        return Promise.resolve({steps: STEPS.map(s => ({...s})),
          stats: {total: 2, completed: 1, skipped: 0, pending: 1}});
      }
      if (url.includes('/failures/')) {
        return Promise.resolve([{...FAILURE, status: failureStatus}]);
      }
      if (url.includes('/records/1/')) return Promise.resolve(store.record);
      return Promise.resolve({});
    });
  }

  it('失败待处理：当前阶段节点显示失败态，菜单出现"处理失败"', async () => {
    mockWithFailure();
    store.failures = [{...FAILURE}];
    renderForm();
    expect(container.textContent).toContain('（处理失败）');
    await clickButton('阶段操作');
    const menu = Array.from(document.querySelectorAll('.ant-dropdown-menu'))
      .find(m => m.textContent.includes('处理失败'));
    expect(menu.textContent).toContain('处理失败【灰度发布】');
  });

  it('失败待处理阶段步骤的完成按钮禁用', () => {
    mockWithFailure();
    store.failures = [{...FAILURE}];
    renderForm();
    // 灰度发布阶段的待执行步骤（执行数据库脚本）：完成按钮被禁用
    const stepRow = Array.from(container.querySelectorAll('[class*="stepRowTodo"]'))
      .find(el => el.textContent.includes('执行数据库脚本'));
    const btn = Array.from(stepRow.querySelectorAll('button'))
      .find(b => b.textContent.includes('完成'));
    expect(btn.disabled).toBe(true);
    // 备份阶段（已完成步骤）不受影响，无禁用的完成按钮
    const backupRow = Array.from(container.querySelectorAll('[class*="stepRowDone"]'))
      .find(el => el.textContent.includes('备份数据库'));
    expect(backupRow).toBeDefined();
  });

  it('打开处理失败弹窗：展示失败信息，选择步骤后提交开始重做', async () => {
    mockWithFailure();
    store.failures = [{...FAILURE}];
    renderForm();
    await clickButton('阶段操作');
    const item = Array.from(document.querySelectorAll('.ant-dropdown-menu-item'))
      .find(el => el.textContent.includes('处理失败【灰度发布】'));
    await act(async () => {
      item.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
      await flush();
    });
    const modal = document.querySelector('.ant-modal');
    expect(modal.textContent).toContain('灰度指标异常');
    expect(modal.textContent).toContain('张三');
    // 勾选待执行步骤并提交（整阶段重做路径）
    http.post.mockResolvedValue({failure_id: 9, selected_count: 1, reset_count: 0});
    const redoAll = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.includes('重做整个阶段'));
    await act(async () => {
      redoAll.click();
      await flush();
      await flush();
    });
    expect(http.post).toHaveBeenCalledWith(
      '/api/upgrade/records/1/failures/9/start-redo/',
      expect.objectContaining({all_steps: true}));
  });
});

describe('历史事件展示（追加式）', () => {
  it('时间线无删除入口（历史事件禁删改）', () => {
    store.statusLogs = [{...LOG_BASE, id: 1, action: 'start', action_text: '升级启动'}];
    renderForm();
    const timeline = container.querySelector('[class*="timelineScroll"]');
    expect(timeline.querySelectorAll('.anticon-delete')).toHaveLength(0);
    expect(timeline.textContent).not.toContain('确定删除此日志');
  });

  it('新事件标题：步骤完成/重置/开始重做/更正失败', () => {
    store.statusLogs = [
      {...LOG_BASE, id: 1, action: 'step_done', phase: '灰度发布',
        detail: {steps: [{id: 1, title: '执行数据库脚本', phase: '灰度发布',
          from_status: 'pending', to_status: 'completed'}]}},
      {...LOG_BASE, id: 2, action: 'step_reset', phase: '灰度发布',
        detail: {steps: [{id: 1, title: '执行数据库脚本', phase: '灰度发布',
          from_status: 'completed', to_status: 'pending'}]}},
      {...LOG_BASE, id: 3, action: 'redo_start', phase: '灰度发布',
        detail: {failure_id: 9, selected_count: 2, reset_count: 1, steps: []}},
      {...LOG_BASE, id: 4, action: 'failure_corrected', phase: '灰度发布',
        remark: '误报：指标恢复'},
    ];
    renderForm();
    expect(container.textContent).toContain('完成步骤「执行数据库脚本」');
    expect(container.textContent).toContain('重置步骤「执行数据库脚本」');
    expect(container.textContent).toContain('开始重做【灰度发布】阶段');
    expect(container.textContent).toContain('更正失败记录（灰度发布）');
  });

  it('批量重置与重新执行事件显示摘要，可展开查看受影响步骤', () => {
    store.statusLogs = [
      {...LOG_BASE, id: 1, action: 'step_reset', phase: '灰度发布',
        detail: {batch: true, reset_count: 2, steps: [
          {id: 1, title: '执行数据库脚本', phase: '灰度发布',
            from_status: 'completed', to_status: 'pending'},
          {id: 2, title: '灰度验证', phase: '灰度发布',
            from_status: 'skipped', to_status: 'pending'},
        ]}},
      {...LOG_BASE, id: 2, action: 'rollback', phase: '',
        target_action_text: '备份', from_status: '处理中', to_status: '已回退',
        detail: {target_phase: '备份', selected_count: 3, reset_count: 3,
          later_action: 'keep', later_reason: '后续结果仍有效',
          steps: [{id: 3, title: '备份数据库', phase: '备份',
            from_status: 'completed', to_status: 'pending'}],
          failures_resolved: []}},
    ];
    renderForm();
    expect(container.textContent).toContain('重置步骤（2 个）');
    expect(container.textContent).toContain('从「备份」重新执行');
    expect(container.textContent).toContain('选择 3 个步骤 · 实际重置 3 个');
    expect(container.textContent).toContain('后续结果已确认保留');
    expect(container.textContent).toContain('保留理由：后续结果仍有效');
    // 展开明细
    const toggle = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.includes('展开明细（1）'));
    expect(toggle).toBeDefined();
    return clickButton('展开明细（1）').then(() => {
      expect(container.textContent).toContain('【备份】备份数据库：已完成→待执行');
    });
  });

  it('旧 rollback 日志（无 detail）保留原始含义"回退至「X」"', () => {
    store.statusLogs = [{...LOG_BASE, id: 1, action: 'rollback',
      target_action_text: '备份', from_status: '处理中', to_status: '已回退'}];
    renderForm();
    expect(container.textContent).toContain('回退至「备份」');
    expect(container.textContent).not.toContain('从「备份」重新执行');
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

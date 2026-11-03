/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单页签 · 提交待发布核对固定快照交接（2026-11-03）行为测试：
 * - 编制状态映射：待发布人核对（不可重复提交）/已撤回/已退回（Tooltip 原因）/
 *   旧版提交记录（提示不可用于发布、需按新规则重新提交）/无需提交；
 * - 冻结文件禁用结构：不渲染开始修订/继续编辑/预览草稿/下载草稿/改名/上移/
 *   下移/移除/分工链接，行勾选禁用；改提供「预览待核对快照」「下载待核对
 *   快照」（submission/preview-url/、submission/download/），预览标题=
 *   「预览待核对快照：文件名（提交人 X，提交时间 Y）」；
 * - 提交入口仅 assignment.is_effective_owner（显式 false 时即使 is_mine 也
 *   不渲染，所有者不得代提交）；
 * - 撤回提交：确认后 store.withdrawSubmission(fileId)，真实成功才提示并刷新；
 * - 退回修改：原因必填（空原因警告且不请求），≤500，成功后 store.returnSubmission；
 * - 有效负责人展示：owner_assigned=false 后缀「（手册所有者，默认）」，
 *   effective_owner_id 为空才显示「未分配」。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

window.matchMedia = window.matchMedia || function () {
  return {matches: false, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}};
};

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn()},
  history: {push: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: false, permissions: []},
}));

jest.mock('antd', () => {
  const antd = jest.requireActual('antd');
  return {
    ...antd,
    message: Object.assign({}, antd.message, {
      success: jest.fn(), error: jest.fn(), warning: jest.fn(),
    }),
  };
});

jest.mock('../detail/FileHistoryModal', () =>
  function FileHistoryModal(props) {
    FileHistoryModal.lastProps = props;
    return null;
  });

jest.mock('../../../layout/InstitutionBadgeStore', () => ({
  __esModule: true,
  default: {fetch: jest.fn()},
}));

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', status: 'active',
      my_roles: ['view', 'edit', 'publish'],
      current_version: null};
    @observable files = [];
    @observable isFetchingFiles = false;
    @observable currentFiles = null;
    @observable isFetchingCurrentFiles = false;
    @observable currentFilesError = '';
    @observable draftStatus = null;
    @observable isFetchingDraftStatus = false;
    @observable draftStatusError = '';
    fetchFiles = jest.fn(() => Promise.resolve());
    fetchCurrentFiles = jest.fn(() => Promise.resolve());
    clearCurrentFiles = jest.fn(() => {});
    fetchDraftStatus = jest.fn(() => Promise.resolve());
    fetchDetail = jest.fn(() => Promise.resolve());
    startRevision = jest.fn(() => Promise.resolve({started: true}));
    batchAssignFiles = jest.fn(() => Promise.resolve({count: 0, files: []}));
    submitCompile = jest.fn(() => Promise.resolve({}));
    withdrawSubmission = jest.fn(() => Promise.resolve({}));
    returnSubmission = jest.fn(() => Promise.resolve({}));
    fetchSubmissionPreviewUrl = jest.fn(() => Promise.resolve({
      preview_url: 'http://snapshot',
      file_name: '甲_提交快照.docx',
      submitted_by_name: '张三',
      submitted_at: '2026-03-05T09:00:00',
    }));
  }
  return new DetailStore();
});

import { http } from 'libs';
import { message } from 'antd';
import FileListTab from '../detail/FileListTab';
import store from '../detail/store';

const PENDING_SUBMISSION = {
  status: 'pending', state: 'submitted', frozen: true,
  can_withdraw: true, can_return: false,
  submitted_by_name: '张三', submitted_at: '2026-03-05T09:00:00',
  submission_revision: 5, draft_revision: 5,
  snapshot: {file_name: '甲_提交快照.docx'},
};

const FROZEN_FILE = {
  id: 21, manual_id: 7, name: '甲.docx', sort_order: 0, is_removed: false,
  revision_open: false,
  draft: {revision: 5, file_name: '甲.docx',
    last_saved_at: '2026-03-01T10:00:00', last_saved_by_name: '我'},
  active_session: null,
  assignment: {owner_id: 9, owner_name: '我', note: '',
    is_mine: true, is_effective_owner: true, effective_owner_id: 9,
    effective_owner_name: '我', owner_assigned: true},
  submission: PENDING_SUBMISSION,
};

function renderTab() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<FileListTab/>, container);
  });
  return container;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function findButton(root, text) {
  const needle = String(text).replace(/\s+/g, '');
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(needle));
}

function switchView(root, label) {
  const item = Array.from(root.querySelectorAll('.ant-segmented-item'))
    .find(el => el.textContent.includes(label));
  if (!item) throw new Error('未找到视图切换项: ' + label);
  act(() => {
    item.querySelector('input').click();
  });
}

function confirmPrimary() {
  const modal = document.querySelector('.ant-modal-confirm');
  if (!modal) throw new Error('未找到确认弹窗');
  return modal.querySelector('.ant-btn-primary');
}

// okType='danger' 的确认按钮带 ant-btn-dangerous 而非 ant-btn-primary
function confirmDanger() {
  const modal = document.querySelector('.ant-modal-confirm');
  if (!modal) throw new Error('未找到确认弹窗');
  return Array.from(modal.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes('确认退回'));
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  const {hasPermission} = require('libs');
  hasPermission.mockImplementation(() => true);
  // 发布人视角（非该文件有效负责人，但有发布权）
  store.manual = {id: 7, name: '科室操作手册', status: 'active',
    my_roles: ['view', 'publish'], is_owner: false, is_admin: false,
    current_version: null};
  store.files = [];
  store.draftStatus = null;
  store.draftStatusError = '';
  store.currentFiles = null;
  window.URL.createObjectURL = jest.fn(() => 'blob:x');
  window.URL.revokeObjectURL = jest.fn();
  http.get.mockImplementation(() => Promise.resolve({data: new Blob()}));
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    container = null;
  }
  document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-confirm')
    .forEach(el => el.remove());
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('FileListTab（编制状态：提交待发布核对固定快照）', () => {
  it('有效快照 → 待发布人核对，冻结 Tag 可见，说明文案不再提"无副本"', () => {
    store.files = [FROZEN_FILE];
    container = renderTab();
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('待发布人核对');
    expect(text).toContain('已冻结');
    expect(text).toContain('固定不可变内容快照');
    expect(text).toContain('旧版提交记录不可用于发布');
    expect(text).not.toContain('系统不保存提交时刻的文件副本');
  });

  it('已撤回/已退回：显示新状态标签（退回原因见共享状态 Tooltip 套件）', () => {
    store.files = [
      {...FROZEN_FILE, submission: {status: 'withdrawn', frozen: false,
        withdrawn_by_name: '我', withdrawn_at: '2026-03-06T10:00:00'}},
      {...FROZEN_FILE, id: 22, name: '乙.docx',
        submission: {status: 'returned', frozen: false,
          returned_by_name: '王五', returned_at: '2026-03-06T11:00:00',
          return_reason: '缺少审批依据'}},
    ];
    container = renderTab();
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('已撤回（可重新提交）');
    expect(text).toContain('已退回');
  });

  it('旧版提交记录（legacy_submitted）：显示旧版 Tag 并提示必须重新提交', () => {
    store.files = [{
      ...FROZEN_FILE, revision_open: true,
      submission: {status: 'none', legacy_submitted: true, frozen: false},
    }];
    container = renderTab();
    switchView(container, '修订草稿');
    expect(container.textContent).toContain('旧版提交记录');
    // JSX 多行文案会折叠成空格，断言前缀一致即可
    const normalized = container.textContent.replace(/\s+/g, '');
    expect(normalized).toContain(
      '旧版提交记录不可用于发布，需按新规则重新提交待发布核对');
  });
});

describe('FileListTab（冻结文件：禁用结构与快照动作）', () => {
  it('冻结行不渲染编辑/改名/排序/移除/分工入口，行勾选禁用', () => {
    store.files = [FROZEN_FILE];
    store.manual = {...store.manual, is_owner: true};
    container = renderTab();
    switchView(container, '修订草稿');
    expect(findButton(container, '开始修订')).toBeUndefined();
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '预览草稿')).toBeUndefined();
    expect(findButton(container, '下载草稿')).toBeUndefined();
    // 结构写入口不得以可点击形态出现（不渲染，或渲染必禁用）
    ['改名', '移除'].forEach(label => {
      const btn = Array.from(container.querySelectorAll('button'))
        .find(b => b.textContent.replace(/\s+/g, '') === label);
      if (btn) expect(btn.disabled).toBe(true);
    });
    // 冻结文件不可改派负责人：负责人单元格不渲染分工链接
    const ownerLinks = Array.from(container.querySelectorAll('a'))
      .filter(a => a.textContent.includes('我'));
    expect(ownerLinks.length).toBe(0);
    // 批量分工勾选禁用
    const checkbox = container.querySelector(
      '.ant-table-tbody input[type="checkbox"]');
    expect(checkbox.disabled).toBe(true);
  });

  it('预览待核对快照：走 submission/preview-url/，标题含提交人与提交时间', async () => {
    store.files = [FROZEN_FILE];
    container = renderTab();
    switchView(container, '修订草稿');
    act(() => {
      findButton(container, '预览待核对快照')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchSubmissionPreviewUrl).toHaveBeenCalledWith(21);
    // 绝不回落到当前草稿预览端点
    expect(http.get).not.toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/21/draft/preview-url/');
    const title = document.querySelector('.ant-modal-title');
    expect(title.textContent).toBe('预览待核对快照：甲_提交快照.docx（提交人 张三，' +
      '提交时间 2026-03-05 09:00:00）');
  });

  it('下载待核对快照：走 submission/download/ 端点', async () => {
    store.files = [FROZEN_FILE];
    container = renderTab();
    switchView(container, '修订草稿');
    act(() => {
      findButton(container, '下载待核对快照')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/21/submission/download/',
      {responseType: 'blob'});
  });
});

describe('FileListTab（提交入口权限与撤回/退回）', () => {
  it('显式 is_effective_owner=false：即使 is_mine 也不渲染提交入口（不得代提交）', () => {
    store.files = [{
      ...FROZEN_FILE,
      submission: null,
      assignment: {...FROZEN_FILE.assignment,
        is_mine: true, is_effective_owner: false,
        effective_owner_id: 5, effective_owner_name: '李四',
        owner_assigned: true},
    }];
    store.manual = {...store.manual, is_owner: true};
    container = renderTab();
    switchView(container, '修订草稿');
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
    expect(findButton(container, '重新提交')).toBeUndefined();
  });

  it('撤回提交：确认后 store.withdrawSubmission，真实成功才提示并刷新清单', async () => {
    store.files = [{...FROZEN_FILE,
      assignment: {...FROZEN_FILE.assignment, is_effective_owner: true}}];
    store.manual = {...store.manual, is_owner: false, my_roles: ['view', 'edit']};
    container = renderTab();
    switchView(container, '修订草稿');
    act(() => {
      findButton(container, '撤回提交')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.withdrawSubmission).not.toHaveBeenCalled();
    expect(document.querySelector('.ant-modal-confirm').textContent)
      .toContain('固定快照作废、内容解冻');
    await act(async () => {
      confirmPrimary().click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.withdrawSubmission).toHaveBeenCalledWith(21);
    expect(message.success).toHaveBeenCalledWith('已撤回提交，可继续修改该文件');
    expect(store.fetchFiles).toHaveBeenCalledWith(7);
  });

  it('退回修改：原因必填（空原因阻止请求），填写后经 store.returnSubmission 提交', async () => {
    store.files = [{
      ...FROZEN_FILE,
      assignment: {owner_id: 5, owner_name: '李四', note: '', is_mine: false,
        is_effective_owner: false, effective_owner_id: 5,
        effective_owner_name: '李四', owner_assigned: true},
      submission: {...PENDING_SUBMISSION, can_withdraw: false,
        can_return: true},
    }];
    container = renderTab();
    switchView(container, '修订草稿');
    act(() => {
      findButton(container, '退回修改')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    // Modal.confirm 经 setTimeout 异步渲染，需多轮宏任务
    await flush();
    await flush();
    // 空原因：警告且不请求（弹窗保持打开）
    await act(async () => {
      confirmDanger().click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    expect(store.returnSubmission).not.toHaveBeenCalled();
    expect(message.warning).toHaveBeenCalledWith('请填写退回原因');
    // 填写原因后提交
    const textarea = document.querySelector('#institution-return-reason');
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, '缺少审批依据，请补充');
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
    await act(async () => {
      confirmDanger().click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.returnSubmission).toHaveBeenCalledWith(21, '缺少审批依据，请补充');
    expect(message.success)
      .toHaveBeenCalledWith('已退回修改，等待负责人重新提交待发布核对');
  });
});

describe('FileListTab（有效负责人展示）', () => {
  it('owner_assigned=false：显示手册所有者并后缀「（手册所有者，默认）」', () => {
    store.files = [{
      ...FROZEN_FILE, submission: null,
      assignment: {owner_id: null, owner_name: '', note: '', is_mine: false,
        is_effective_owner: false, effective_owner_id: 3,
        effective_owner_name: '王五', owner_assigned: false},
    }];
    container = renderTab();
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('王五');
    expect(text).toContain('（手册所有者，默认）');
    expect(text).not.toContain('未分配');
  });

  it('effective_owner_id 为空才显示「未分配」（不按 owner_id 推断）', () => {
    store.files = [{
      ...FROZEN_FILE, submission: null,
      assignment: {owner_id: null, owner_name: '', note: '', is_mine: false,
        is_effective_owner: false, effective_owner_id: null,
        effective_owner_name: '', owner_assigned: false},
    }];
    container = renderTab();
    switchView(container, '修订草稿');
    expect(container.textContent).toContain('未分配');
  });
});

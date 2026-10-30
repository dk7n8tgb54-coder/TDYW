/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单页签行为测试（2026-10-30 修订状态交互优化版）：
 * - 日常清单保留 顺序/文件名/大小/负责人/状态/编制提交/操作；修订号、
 *   工作副本来源与"草稿 vs 生效版本"等细节不再作为主列（放草稿工作台
 *   与变更记录），旧主列文案不出现；
 * - 状态列由服务端 内容关系（draft-status）+ 修订进行中（revision_open）
 *   合并：修订中·有未发布修改 / 修订进行中 / 新增待发布 / 已生效 /
 *   「某人」编辑中 / 草稿未就绪；未加载显示占位「—」；
 * - 行操作按修订状态显示「开始修订」（真实状态动作，经 store.startRevision）
 *   或「继续编辑」；needs_repair 时明确提示修复途径并经确认重试；
 * - 负责人列点击直接打开分工弹窗（操作列不再有「文件分工」链接）；
 *   勾选多份文件出现批量分工栏，提交后清空勾选；
 * - 新增（未进入生效版本）与已移除文件同样呈现；已清理快照只显示元数据；
 * - 权限：仅查看角色行=生效快照，无草稿列与编辑入口，不请求 draft-status；
 *   废止动作仅发布角色可见。
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

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', status: 'active',
      my_roles: ['view', 'edit', 'publish'], editor_can_view_published: true,
      current_version: {id: 9, version_no: 3}};
    @observable files = [];
    @observable isFetchingFiles = false;
    @observable currentFiles = null;
    @observable isFetchingCurrentFiles = false;
    @observable currentFilesError = '';
    @observable draftStatus = null;
    @observable isFetchingDraftStatus = false;
    @observable draftStatusError = '';
    fetchFiles = jest.fn(function () { return Promise.resolve(); });
    fetchCurrentFiles = jest.fn(function () { return Promise.resolve(); });
    clearCurrentFiles = jest.fn(function () {});
    fetchDraftStatus = jest.fn(function () { return Promise.resolve(); });
    fetchDetail = jest.fn(function () {
      this.manual = Object.assign({id: 7, name: '科室操作手册',
        status: 'active', my_roles: ['view', 'edit', 'publish'],
        editor_can_view_published: true,
        current_version: {id: 9, version_no: 3}});
      return Promise.resolve();
    });
    startRevision = jest.fn(function (fileId, confirmRepair) {
      return Promise.resolve({resumed: false, started: true,
        needs_repair: false});
    });
    batchAssignFiles = jest.fn(function (fileIds, ownerId, note) {
      return Promise.resolve({count: fileIds.length, files: []});
    });
  }
  return new DetailStore();
});

import {history} from 'libs';
import {http} from 'libs';
import FileListTab from '../detail/FileListTab';
import store from '../detail/store';

const SNAP_MODIFIED = {id: 101, manual_file_id: 11, file_name: '甲.docx',
  sort_order: 0, file_size: 2048, file_hash: 'aaaa1111', change_type: 'modified'};
const SNAP_UNCHANGED = {id: 102, manual_file_id: 12, file_name: '乙.docx',
  sort_order: 1, file_size: 1024, file_hash: 'bbbb2222', change_type: 'unchanged'};
const SNAP_REMOVED_FILE = {id: 103, manual_file_id: 13, file_name: '丙.docx',
  sort_order: 2, file_size: 512, file_hash: 'cccc3333', change_type: 'unchanged'};

const CURRENT_FILES = {
  version_id: 9, version_no: 3, change_note: 'v3 发布',
  previous_version_no: 2,
  items: [SNAP_MODIFIED, SNAP_UNCHANGED, SNAP_REMOVED_FILE],
  removed_items: [],
};

const FILES = [
  {id: 11, manual_id: 7, name: '甲.docx', sort_order: 0, is_removed: false,
    revision_open: true, originals_count: 1,
    draft: {revision: 5, last_saved_by_name: '张三',
      last_saved_at: '2026-01-02T10:00:00'},
    active_session: null},
  {id: 12, manual_id: 7, name: '乙.docx', sort_order: 1, is_removed: false,
    revision_open: false, originals_count: 1,
    draft: {revision: 2, last_saved_by_name: '李四',
      last_saved_at: '2026-01-03T09:00:00'},
    active_session: {is_mine: false, user_name: '李四', expires_at: ''}},
  // 新增文件：待发布集合中但未进入生效版本
  {id: 14, manual_id: 7, name: '新增文件.docx', sort_order: 2,
    is_removed: false, revision_open: true, originals_count: 1,
    draft: {revision: 1, last_saved_by_name: '张三',
      last_saved_at: '2026-01-04T09:00:00'},
    active_session: null},
];

const DRAFT_STATUS = {
  has_current_version: true, current_version_no: 3,
  items: [
    {file_id: 11, name: '甲.docx', status: 'modified', has_draft: true,
      draft_revision: 5, revision_open: true, renamed: true,
      current_name: '旧甲名.docx',
      unconfirmed_reason: null, unconfirmed_message: null, session: null},
    {file_id: 12, name: '乙.docx', status: 'unconfirmed', has_draft: true,
      draft_revision: 2, revision_open: false, renamed: false,
      current_name: null,
      unconfirmed_reason: 'session_busy',
      unconfirmed_message: '该文件仍有进行中的编辑会话（含未完成的同步）',
      session: {is_mine: false, user_name: '李四'}},
    {file_id: 14, name: '新增文件.docx', status: 'added', has_draft: true,
      draft_revision: 1, revision_open: true, renamed: false,
      current_name: null,
      unconfirmed_reason: null, unconfirmed_message: null, session: null},
  ],
  removed_items: [
    {file_id: 13, name: '丙.docx', sort_order: 2, file_size: 512,
      file_hash: 'cccc3333', from_version_no: 3},
  ],
  summary: {total_files: 3, modified: 1, added: 1, unconfirmed: 1,
    removed: 1, renamed: 1, reordered: false, revising: 2,
    has_current_version: true, has_pending_changes: true,
    determinable: false, consistent: false},
};

function renderTab(props = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<FileListTab {...props}/>, container);
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
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(text));
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  // clearAllMocks 不恢复 mockImplementation：显式复位默认放行，
  // 防止收窄权限的用例泄漏到后续用例
  const {hasPermission} = require('libs');
  hasPermission.mockImplementation(() => true);
  store.manual = {id: 7, name: '科室操作手册', status: 'active',
    my_roles: ['view', 'edit', 'publish'], editor_can_view_published: true,
    current_version: {id: 9, version_no: 3}};
  store.files = FILES;
  store.isFetchingFiles = false;
  store.currentFiles = CURRENT_FILES;
  store.currentFilesError = '';
  store.draftStatus = DRAFT_STATUS;
  store.draftStatusError = '';
  store.startRevision.mockImplementation(
    function () {
      return Promise.resolve({resumed: false, started: true,
        needs_repair: false});
    });
  http.get.mockResolvedValue({preview_url: 'http://x', file_name: 'f.docx'});
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    container = null;
  }
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('FileListTab（统一文件清单：修订状态版）', () => {
  it('挂载即拉取 待发布清单/草稿状态/当前生效快照', () => {
    container = renderTab();
    expect(store.fetchFiles).toHaveBeenCalledWith(store.id);
    expect(store.fetchDraftStatus).toHaveBeenCalledWith(store.id);
    expect(store.fetchCurrentFiles).toHaveBeenCalledWith(store.id, 9);
  });

  it('状态列按 服务端关系+修订状态 合并呈现；旧主列（修订号/基于版本/关系原文）不再出现', () => {
    container = renderTab();
    const text = container.textContent;
    expect(text).toContain('甲.docx');
    expect(text).toContain('修订中 · 有未发布修改');
    expect(text).toContain('已改名');
    expect(text).toContain('乙.docx');
    expect(text).toContain('李四 编辑中');
    expect(text).toContain('新增待发布');
    // 日常清单不再展示 修订号/关系原文/基于版本/生效版本 主列
    expect(text).not.toContain('r5');
    expect(text).not.toContain('已修改未发布');
    expect(text).not.toContain('与生效版本一致');
    expect(text).not.toContain('基于版本');
    expect(text).not.toContain('草稿 vs 生效版本');
    expect(text).not.toContain('沿用旧内容');
  });

  it('行操作按修订状态显示「继续编辑」或「开始修订」，深链直达对应文件', async () => {
    container = renderTab();
    const continueBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '继续编辑');
    const startBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '开始修订');
    expect(continueBtn).not.toBeUndefined();
    expect(startBtn).not.toBeUndefined();
    // 修订进行中的甲 → 继续编辑（直接深链，不调 startRevision）
    act(() => {
      continueBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(store.startRevision).not.toHaveBeenCalled();
    expect(history.push).toHaveBeenCalledWith('/institution/manuals/7/draft?file=11');
    // 已结束修订的乙 → 开始修订（真实状态动作：先调 startRevision 再深链）
    act(() => {
      startBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.startRevision).toHaveBeenCalledWith(12);
    expect(history.push).toHaveBeenCalledWith('/institution/manuals/7/draft?file=12');
  });

  it('开始修订发现工作副本异常：明确提示修复途径，确认后携带 confirm_repair 重试', async () => {
    store.startRevision.mockImplementationOnce(function () {
      return Promise.resolve({resumed: false, started: false,
        needs_repair: true, reason: 'draft_corrupt',
        message: '该文件的工作副本文件缺失，将从当前生效版本 v3 的快照恢复',
        draft_recovery: {source: 'current_version', version_no: 3}});
    });
    container = renderTab();
    const startBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '开始修订');
    act(() => {
      startBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    // 明确提示：不静默修复、不静默改用初始来源
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).not.toBeNull();
    expect(confirm.textContent).toContain('从当前生效版本 v3');
    expect(confirm.textContent).toContain('快照');
    store.startRevision.mockClear();
    store.startRevision.mockImplementation(
      function () {
        return Promise.resolve({resumed: false, started: true, repaired: true,
          needs_repair: false});
      });
    await act(async () => {
      confirm.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.startRevision).toHaveBeenCalledWith(12, true);
    expect(history.push).toHaveBeenCalledWith('/institution/manuals/7/draft?file=12');
  });

  it('已清理快照只显示元数据，不渲染会失败的预览/下载', () => {
    store.currentFiles = {
      ...CURRENT_FILES,
      items: [{...SNAP_MODIFIED, is_cleaned: true}, SNAP_UNCHANGED],
    };
    container = renderTab();
    const text = container.textContent;
    expect(text).toContain('已清理');
    expect(text.includes('甲.docx')).toBe(true);
    // 甲行无预览/下载按钮（行级断言：预览按钮总数只来自未清理行）
    const previewButtons = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent === '预览' || b.textContent === '预 览');
    expect(previewButtons.length).toBe(1); // 仅乙行
  });
});

describe('FileListTab（变更记录入口与已移除分区）', () => {
  it('变更记录设置预选并回调父级', () => {
    const onOpenFileHistory = jest.fn();
    container = renderTab({onOpenFileHistory});
    const historyBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '变更记录');
    act(() => {
      historyBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(store.fileChangeTarget).toBe(11);
    expect(onOpenFileHistory).toHaveBeenCalled();
  });

  it('已移除文件单独分区呈现（仍生效、发布后将不再包含），可预览下载，无编辑入口', () => {
    container = renderTab();
    const text = container.textContent;
    expect(text).toContain('已移除 1 份文件');
    expect(text).toContain('丙.docx');
    const editButtons = Array.from(container.querySelectorAll('button'))
      .filter(b => ['继续编辑', '开始修订'].includes(
        b.textContent.replace(/\s+/g, '')));
    expect(editButtons.length).toBe(3); // 甲/乙/新增文件 三行，无丙
  });
});

describe('FileListTab（错误态与占位）', () => {
  it('草稿状态未加载：状态列显示占位，不出现"一致/无变化/已生效"语义', () => {
    store.draftStatus = null;
    container = renderTab();
    const text = container.textContent;
    expect(text).not.toContain('已生效');
    expect(text).not.toContain('已修改未发布');
    expect(text).not.toContain('修订中');
  });

  it('草稿状态加载失败：页签内给出重试入口，不冒充无变化', () => {
    store.draftStatusError = '草稿状态加载失败，请重试';
    container = renderTab();
    expect(container.textContent).toContain('加载失败');
    const retry = findButton(container, '重试');
    expect(retry).toBeTruthy();
    act(() => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(store.fetchDraftStatus).toHaveBeenCalledWith(store.id);
  });

  it('生效快照加载失败：错误+重试，不以空清单冒充成功', () => {
    store.currentFiles = null;
    store.currentFilesError = '当前生效文件加载失败，请重试';
    container = renderTab();
    expect(container.textContent).toContain('当前生效文件加载失败');
    const retry = findButton(container, '重试');
    act(() => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(store.fetchCurrentFiles).toHaveBeenCalledWith(store.id, 9);
  });
});

describe('FileListTab（批量分工）', () => {
  function checkRow(container, rowIndex) {
    const checkboxes = Array.from(
      container.querySelectorAll('.ant-table-tbody input[type="checkbox"]'));
    act(() => {
      checkboxes[rowIndex].dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
  }

  it('勾选多份文件出现批量分工栏（含已选数量），提交后经 store.batchAssignFiles', async () => {
    container = renderTab();
    expect(container.textContent).not.toContain('批量指定负责人');
    checkRow(container, 0);
    checkRow(container, 1);
    expect(container.textContent).toContain('已选 2 份文件');
    const assignBtn = findButton(container, '批量指定负责人');
    act(() => {
      assignBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('批量文件分工（2 份文件）');
    // 批量弹窗明确作用范围（列出所选文件名）
    expect(modal.textContent).toContain('甲.docx');
    expect(modal.textContent).toContain('乙.docx');
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.batchAssignFiles).toHaveBeenCalledWith(
      [11, 12], null, '');
    // 成功后清空勾选
    expect(container.textContent).not.toContain('已选 2 份文件');
  });

  it('清空负责人入口：确认后整批置为未分配', async () => {
    container = renderTab();
    checkRow(container, 0);
    const clearBtn = findButton(container, '清空负责人');
    act(() => {
      clearBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm.textContent).toContain('未分配');
    await act(async () => {
      confirm.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.batchAssignFiles).toHaveBeenCalledWith([11], null, '');
  });

  it('「只看我负责的文件」筛选切换清空勾选，不对筛选后不可见文件误操作', async () => {
    store.files = [
      {...FILES[0], assignment: {owner_id: 9, owner_name: '乙', note: '',
        is_mine: true}},
      FILES[1],
    ];
    container = renderTab();
    checkRow(container, 1); // 勾选乙（非我负责）
    expect(container.textContent).toContain('已选 1 份文件');
    const checkboxes = Array.from(
      container.querySelectorAll('input[type="checkbox"]'));
    // 页签顶部的「只看我负责的文件」是清单外第一个 checkbox
    const onlyMine = checkboxes.find(
      c => c.closest('label') &&
        c.closest('label').textContent.includes('只看我负责的文件'));
    act(() => {
      onlyMine.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(container.textContent).not.toContain('已选 1 份文件');
  });
});

describe('FileListTab（仅查看口径与废止动作）', () => {
  it('仅查看角色：行=生效快照、无草稿列与编辑入口，不请求 draft-status', () => {
    // 同时收窄模块权限（edit/config 权限也算工作区可见），模拟纯手册查看角色
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.download');
    store.manual = Object.assign({}, store.manual, {my_roles: ['view']});
    container = renderTab();
    expect(store.fetchDraftStatus).not.toHaveBeenCalled();
    const text = container.textContent;
    // 行来自生效快照（含被移除的丙——生效版本完整清单）
    expect(text).toContain('甲.docx');
    expect(text).toContain('丙.docx');
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '开始修订')).toBeUndefined();
    expect(text).not.toContain('状态');
  });

  it('废止按钮仅发布角色可见，确认后 POST deprecate 并刷新', async () => {
    container = renderTab();
    expect(findButton(container, '废止')).not.toBeUndefined();
    http.post.mockResolvedValue({});
    act(() => {
      findButton(container, '废止')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    // Modal.confirm 异步渲染后点击确认
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 0));
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    const okButton = document.querySelector('.ant-modal-confirm .ant-btn-primary');
    expect(okButton).not.toBeNull();
    await act(async () => {
      okButton.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    expect(http.post).toHaveBeenCalledWith('/api/institution/manuals/7/deprecate/');
    // 刷新链：详情 -> 文件清单/草稿状态/生效快照
    expect(store.fetchDetail).toHaveBeenCalledWith(store.id);
    // 仅编制角色（无发布角色）不渲染废止
    ReactDOM.unmountComponentAtNode(container);
    document.querySelectorAll('.ant-modal').forEach(el => el.remove());
    document.querySelectorAll('.ant-modal-wrap').forEach(el => el.remove());
    container = document.createElement('div');
    document.body.appendChild(container);
    store.manual = Object.assign({}, store.manual, {my_roles: ['edit']});
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    expect(findButton(container, '废止')).toBeUndefined();
  });
});

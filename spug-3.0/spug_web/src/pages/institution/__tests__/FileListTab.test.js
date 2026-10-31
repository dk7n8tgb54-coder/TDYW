/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单页签行为测试（2026-10-30 双视图版）：
 * - 页签内两个内容视图：「当前生效版本 vN」（不可变发布快照；预览/下载
 *   始终打开发布快照并注明版本来源）与「修订草稿」（待发布工作内容；
 *   草稿修订号/负责人/状态/编制提交；预览/下载明确打开待发布草稿）；
 * - 默认视图：有生效版本 → 当前生效版本；首次发布前 → 修订草稿；
 *   切换视图保留「只看我负责的文件」筛选并清空行勾选；
 * - 「编制提交」是交接状态：已提交（有效）/提交已失效/未提交，绝不冒充
 *   已发布；负责人列是责任归属（2026-10-31 授权模型：负责人独占编辑=
 *   编制授权 + assignment.is_mine，非负责人行无编辑入口并显示占位提示）；
 * - 行操作按视图分叉：生效视图=快照预览/下载/变更记录；草稿视图=
 *   继续编辑/开始修订/提交编制/草稿预览下载（负责人行）/变更记录；
 * - 权限：仅查看角色只有生效视图（无切换、不请求 draft-status）；
 *   仅发布角色（无编制角色）在草稿视图看不到编辑/草稿预览下载入口；
 *   批量分工与负责人列编辑=draft_edit 页面码 + 手册所有者/制度管理员；
 * - 错误态可重试、空数据有引导，绝不以空清单或"无变化"冒充。
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
        editor_can_view_published: true, is_owner: true, is_admin: false,
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
    draft: {revision: 5, file_name: '甲.docx', last_saved_by_name: '张三',
      last_saved_at: '2026-01-02T10:00:00'},
    active_session: null,
    // 2026-10-31 负责人独占：默认当前账号是负责人（行编辑入口可见）
    assignment: {owner_id: 9, owner_name: '我', note: '', is_mine: true}},
  {id: 12, manual_id: 7, name: '乙.docx', sort_order: 1, is_removed: false,
    revision_open: false, originals_count: 1,
    draft: {revision: 2, file_name: '乙.docx', last_saved_by_name: '李四',
      last_saved_at: '2026-01-03T09:00:00'},
    active_session: {is_mine: false, user_name: '李四', expires_at: ''},
    assignment: {owner_id: 9, owner_name: '我', note: '', is_mine: true}},
  // 新增文件：待发布集合中但未进入生效版本
  {id: 14, manual_id: 7, name: '新增文件.docx', sort_order: 2,
    is_removed: false, revision_open: true, originals_count: 1,
    draft: {revision: 1, file_name: '新增文件.docx', last_saved_by_name: '张三',
      last_saved_at: '2026-01-04T09:00:00'},
    active_session: null,
    assignment: {owner_id: null, owner_name: '', note: '', is_mine: false}},
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
  const needle = String(text).replace(/\s+/g, '');
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(needle));
}

/** 表头文本集合（断言某列是否存在用，避免与说明文案误匹配） */
function columnHeaderTexts(root) {
  return Array.from(root.querySelectorAll('th'))
    .map(th => th.textContent.replace(/\s+/g, ''));
}

/** 点击 Segmented 视图切换 */
function switchView(root, label) {
  const items = Array.from(root.querySelectorAll('.ant-segmented-item'));
  const item = items.find(el => el.textContent.includes(label));
  if (!item) throw new Error('未找到视图切换项: ' + label);
  const input = item.querySelector('input');
  act(() => {
    input.click();
  });
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
    // 2026-10-31 授权模型：批量分工业务门=所有者/制度管理员
    is_owner: true, is_admin: false,
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

describe('FileListTab（双视图默认与切换）', () => {
  it('挂载即拉取 待发布清单/草稿状态/当前生效快照', () => {
    container = renderTab();
    expect(store.fetchFiles).toHaveBeenCalledWith(store.id);
    expect(store.fetchDraftStatus).toHaveBeenCalledWith(store.id);
    expect(store.fetchCurrentFiles).toHaveBeenCalledWith(store.id, 9);
  });

  it('有生效版本：默认显示「当前生效版本 v3」视图（不可变快照清单）', () => {
    container = renderTab();
    const text = container.textContent;
    // 生效视图行=快照（含已从待发布移除的丙）
    expect(text).toContain('当前生效版本 v3');
    expect(text).toContain('甲.docx');
    expect(text).toContain('丙.docx');
    // 快照视图没有草稿域内容（按列头断言，避免与说明文案误匹配）
    expect(text).not.toContain('修订中 · 有未发布修改');
    expect(columnHeaderTexts(container)).not.toContain('编制提交');
    expect(columnHeaderTexts(container)).not.toContain('草稿修订');
    expect(columnHeaderTexts(container)).not.toContain('状态');
    // 2026-10-31 起：工作区用户的生效视图也不渲染负责人列（负责人属
    // 修订分工，只在修订草稿视图展示）；页签说明文案会提到"负责人"一词，
    // 必须以 th 文本判定而不是整页 textContent
    expect(columnHeaderTexts(container)).not.toContain('负责人');
    // 预览按钮文案明确版本来源
    const previewBtn = findButton(container, '预览当前生效版');
    expect(previewBtn).not.toBeUndefined();
  });

  it('首次发布前（无生效版本）：默认显示「修订草稿」视图', () => {
    store.manual = Object.assign({}, store.manual, {current_version: null});
    container = renderTab();
    const text = container.textContent;
    expect(text).toContain('修订草稿');
    expect(text).toContain('甲.docx');
    expect(text).toContain('草稿修订');
    expect(text).toContain('r5');
    expect(text).toContain('编制提交');
    expect(text).toContain('修订中 · 有未发布修改');
  });

  it('切换视图：保留「只看我负责的文件」筛选并清空行勾选', async () => {
    container = renderTab();
    // 草稿视图勾选两行出现批量栏
    switchView(container, '修订草稿');
    const checkboxes = Array.from(
      container.querySelectorAll('.ant-table-tbody input[type="checkbox"]'));
    act(() => {
      checkboxes[0].click();
    });
    expect(container.textContent).toContain('已选 1 份文件');
    // 切回生效视图：勾选清空，批量栏消失
    switchView(container, '当前生效版本');
    expect(container.textContent).not.toContain('已选 1 份文件');
    // 「只看我负责的文件」筛选在切换后仍保留
    const onlyMine = Array.from(container.querySelectorAll('input[type="checkbox"]'))
      .find(c => c.closest('label') &&
        c.closest('label').textContent.includes('只看我负责的文件'));
    expect(onlyMine).not.toBeUndefined();
    act(() => {
      onlyMine.click();
    });
    switchView(container, '修订草稿');
    const onlyMineAfter = Array.from(container.querySelectorAll('input[type="checkbox"]'))
      .find(c => c.closest('label') &&
        c.closest('label').textContent.includes('只看我负责的文件'));
    expect(onlyMineAfter.checked).toBe(true);
  });
});

describe('FileListTab（生效视图：不可变快照与版本来源）', () => {
  it('预览当前生效版：走版本快照端点，预览标题注明版本来源', async () => {
    container = renderTab();
    const previewBtn = findButton(container, '预览当前生效版');
    act(() => {
      previewBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/versions/9/files/101/preview-url/');
    const title = document.querySelector('.ant-modal-title');
    expect(title).not.toBeNull();
    expect(title.textContent).toContain('预览当前生效版 v3');
    expect(title.textContent).toContain('甲.docx');
  });

  it('已清理快照只显示元数据（已清理 Tag），不渲染会失败的预览/下载', () => {
    store.currentFiles = {
      ...CURRENT_FILES,
      items: [{...SNAP_MODIFIED, is_cleaned: true}, SNAP_UNCHANGED],
    };
    container = renderTab();
    const text = container.textContent;
    expect(text).toContain('已清理');
    const previewButtons = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent.replace(/\s+/g, '') === '预览当前生效版');
    expect(previewButtons.length).toBe(1); // 仅乙行
  });

  it('工作区可见者：生效视图中标注已从待发布移除的文件（发布后将不再包含）', () => {
    container = renderTab();
    expect(container.textContent).toContain('已从待发布移除');
    expect(container.textContent).toContain('丙.docx');
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

  it('废止按钮仅发布角色可见，确认后 POST deprecate 并刷新', async () => {
    container = renderTab();
    expect(findButton(container, '废止')).not.toBeUndefined();
    http.post.mockResolvedValue({});
    act(() => {
      findButton(container, '废止')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
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

describe('FileListTab（草稿视图：待发布工作内容）', () => {
  beforeEach(() => {
    container = renderTab();
    switchView(container, '修订草稿');
  });

  it('草稿视图呈现 草稿修订/状态（服务端关系+修订状态合并）/编制提交', () => {
    const text = container.textContent;
    expect(text).toContain('甲.docx');
    expect(text).toContain('修订中 · 有未发布修改');
    expect(text).toContain('已改名');
    expect(text).toContain('李四 编辑中');
    expect(text).toContain('新增待发布');
    expect(text).toContain('r5');
    expect(text).toContain('编制提交');
    // 说明文案明确 待发布草稿/负责人/提交 三件事
    expect(text).toContain('尚未生效');
    expect(text).toContain('不保存提交时刻的文件副本');
  });

  it('预览待发布草稿：走草稿端点，预览标题注明草稿修订号', async () => {
    const previewBtn = findButton(container, '预览草稿 r5');
    expect(previewBtn).not.toBeUndefined();
    act(() => {
      previewBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/draft/preview-url/');
    const title = document.querySelector('.ant-modal-title');
    expect(title.textContent).toContain('预览待发布草稿 r5');
    expect(title.textContent).toContain('甲.docx');
  });

  it('行操作按修订状态显示「继续编辑」或「开始修订」，深链直达对应文件', async () => {
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
    const startBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '开始修订');
    act(() => {
      startBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
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

  it('编制提交三态呈现：已提交/提交已失效/未提交（失效不冒充已提交）', () => {
    store.files = [
      {...FILES[0], submission: {state: 'submitted',
        submitted_at: '2026-01-05T09:00:00', submitted_by_name: '张三',
        submission_revision: 5, draft_revision: 5}},
      {...FILES[1], submission: {state: 'stale',
        submitted_at: '2026-01-04T09:00:00', submitted_by_name: '李四',
        submission_revision: 1, draft_revision: 2}},
    ];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('已提交');
    expect(text).toContain('提交已失效');
    // 说明文案明确限制：无提交时历史副本，不冒充"已提交版本"
    expect(text).toContain('不保存提交时刻的文件副本');
  });
});

describe('FileListTab（草稿视图：入口权限与状态异常）', () => {
  beforeEach(() => {
    container = renderTab();
    switchView(container, '修订草稿');
  });

  /** 全部行改为非我负责（负责人独占收窄用例的夹具） */
  function unassignAll() {
    store.files = FILES.map(f => ({
      ...f, assignment: {...f.assignment, is_mine: false,
        owner_name: f.assignment.owner_id ? '别人' : ''},
    }));
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
  }

  it('负责人行（is_mine）渲染编辑入口与提交编制；非负责人行不渲染', () => {
    // 默认夹具：甲/乙由我负责，提交编制可见
    expect(findButton(container, '提交编制')).not.toBeUndefined();
    // 非负责人：提交编制消失（且编辑入口被收窄，见下一用例）
    unassignAll();
    expect(findButton(container, '提交编制')).toBeUndefined();
  });

  it('非负责人的编制授权账号：无开始修订/继续编辑/草稿预览下载，显示「编辑限负责人」占位提示', () => {
    unassignAll();
    expect(findButton(container, '开始修订')).toBeUndefined();
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '预览草稿 r5')).toBeUndefined();
    expect(container.textContent).toContain('编辑限负责人');
    expect(container.textContent).toContain('编辑仅限文件负责人');
  });

  it('仅发布角色（无编制角色）：无编辑/草稿预览下载入口，负责人只读', () => {
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => ['institution.manual.view', 'institution.manual.download',
        'institution.manual.publish'].includes(code));
    store.manual = Object.assign({}, store.manual, {my_roles: ['publish']});
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    // 无生效查看权（editor_can_view_published 仅对 edit 角色生效）→ 只有草稿视图
    const text = container.textContent;
    expect(text).toContain('甲.docx');
    expect(findButton(container, '预览草稿 r5')).toBeUndefined();
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '开始修订')).toBeUndefined();
    // 负责人只读（无分工入口链接）
    const ownerLinks = Array.from(container.querySelectorAll('a'))
      .filter(a => a.textContent.includes('未分配'));
    expect(ownerLinks.length).toBe(0);
  });

  it('变更记录设置预选并回调父级（草稿视图行）', () => {
    const onOpenFileHistory = jest.fn();
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab onOpenFileHistory={onOpenFileHistory}/>, container);
    });
    switchView(container, '修订草稿');
    const historyBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '变更记录');
    act(() => {
      historyBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(store.fileChangeTarget).toBe(11);
    expect(onOpenFileHistory).toHaveBeenCalled();
  });

  it('草稿状态未加载：状态列显示占位，不出现"一致/无变化/已生效"语义', () => {
    store.draftStatus = null;
    const text = container.textContent;
    expect(text).not.toContain('已生效');
    expect(text).not.toContain('已修改未发布');
    expect(text).not.toContain('修订中');
  });

  it('草稿状态加载失败：重试入口，不冒充无变化', () => {
    store.draftStatusError = '草稿状态加载失败，请重试';
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    expect(container.textContent).toContain('加载失败');
    const retry = findButton(container, '重试');
    act(() => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(store.fetchDraftStatus).toHaveBeenCalledWith(store.id);
  });

  it('空待发布清单：渲染上传引导，不以空清单冒充成功', () => {
    store.files = [];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    expect(container.textContent).toContain('该制度还没有待发布文件');
  });
});

describe('FileListTab（草稿视图批量分工）', () => {
  function checkRow(index) {
    const checkboxes = Array.from(
      container.querySelectorAll('.ant-table-tbody input[type="checkbox"]'));
    act(() => {
      checkboxes[index].dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
  }

  beforeEach(() => {
    container = renderTab();
    switchView(container, '修订草稿');
  });

  it('勾选多份文件出现批量分工栏（含已选数量），提交后经 store.batchAssignFiles', async () => {
    expect(container.textContent).not.toContain('批量指定负责人');
    checkRow(0);
    checkRow(1);
    expect(container.textContent).toContain('已选 2 份文件');
    const assignBtn = findButton(container, '批量指定负责人');
    act(() => {
      assignBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('批量文件分工（2 份文件）');
    expect(modal.textContent).toContain('甲.docx');
    expect(modal.textContent).toContain('乙.docx');
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.batchAssignFiles).toHaveBeenCalledWith([11, 12], null, '');
    expect(container.textContent).not.toContain('已选 2 份文件');
  });

  it('清空负责人入口：确认后整批置为未分配', async () => {
    checkRow(0);
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
      FILES[0],
      {...FILES[1], assignment: {...FILES[1].assignment, is_mine: false,
        owner_name: '别人'}},
    ];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    checkRow(1); // 勾选乙（非我负责）
    expect(container.textContent).toContain('已选 1 份文件');
    const onlyMine = Array.from(container.querySelectorAll('input[type="checkbox"]'))
      .find(c => c.closest('label') &&
        c.closest('label').textContent.includes('只看我负责的文件'));
    act(() => {
      onlyMine.click();
    });
    await flush();
    expect(container.textContent).not.toContain('已选 1 份文件');
  });
});

describe('FileListTab（仅查看口径）', () => {
  it('仅查看角色：只有生效视图（无切换），行=快照，不请求 draft-status', () => {
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.download');
    store.manual = Object.assign({}, store.manual, {my_roles: ['view'],
      is_owner: false, is_admin: false});
    container = renderTab();
    expect(store.fetchDraftStatus).not.toHaveBeenCalled();
    const text = container.textContent;
    // 行来自生效快照（含被移除的丙——生效版本完整清单）
    expect(text).toContain('甲.docx');
    expect(text).toContain('丙.docx');
    // 无视图切换（单一可见视图）、无草稿域内容与编辑入口
    expect(container.querySelector('.ant-segmented')).toBeNull();
    expect(text).not.toContain('编制提交');
    expect(text).not.toContain('草稿修订');
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '开始修订')).toBeUndefined();
    // 仍有明确版本来源的快照预览
    expect(findButton(container, '预览当前生效版')).not.toBeUndefined();
  });

  it('仅查看角色的生效视图不渲染负责人列（修订分工属修订草稿视图）', () => {
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.download');
    store.manual = Object.assign({}, store.manual, {my_roles: ['view'],
      is_owner: false, is_admin: false});
    container = renderTab();
    // 生效视图不渲染负责人列（2026-10-31 起：负责人属修订分工，只在
    // 修订草稿视图展示与维护）；页签说明文案可能提到"负责人"一词，
    // 以 th 文本判定而不是整页 textContent not-contain
    expect(columnHeaderTexts(container)).not.toContain('负责人');
    // 无任何分工编辑入口（无「未分配」点击链接）
    const ownerLinks = Array.from(container.querySelectorAll('a'))
      .filter(a => a.textContent.includes('未分配'));
    expect(ownerLinks.length).toBe(0);
  });
});

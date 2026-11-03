/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单页签行为测试（2026-10-30 双视图版；2026-11-03 固定快照交接）：
 * - 页签内两个内容视图：「当前生效版本 vN」（不可变发布快照；预览/下载
 *   始终打开发布快照并注明版本来源）与「修订草稿」（待发布工作内容；
 *   列=顺序/文件名/大小/负责人/状态/编制状态/操作；未冻结文件的预览/下载
 *   明确打开当前待发布草稿，rN 只出现在 Tooltip 内部）；
 * - 默认视图：有生效版本 → 当前生效版本；首次发布前 → 修订草稿；
 *   切换视图保留「只看我负责的文件」筛选并清空行勾选；
 * - 「编制状态」列=提交待发布核对固定快照状态（2026-11-03）：待发布人核对/
 *   可直接纳入整套发布/待提交待发布核对/待负责人提交待发布核对/已撤回/
 *   已退回/提交已失效/旧版提交记录/编制中/无需提交，唯一渲染依据=
 *   ../compilationStatusShared.buildCompilationState；草稿修订 rN 不再作为
 *   列值；冻结文件（有效提交快照）的预览/下载改读 submission 快照端点，
 *   标题=「预览待核对快照：文件名（提交人 X，提交时间 Y）」。提交入口
 *   只对文件有效负责人（assignment.is_effective_owner，旧 payload 回退
 *   is_mine）渲染，pending 显示不可点击「待发布人核对」+「撤回提交」，
 *   持发布权且非有效负责人可「退回修改」（原因必填）；失效后「重新提交」，
 *   编辑会话进行中禁用；手册所有者非文件有效负责人不得代提交；
 * - 负责人列是责任归属（2026-10-31 授权模型：负责人独占编辑=
 *   编制授权 + assignment.is_mine，非负责人行无编辑入口并显示占位提示）；
 * - 行操作按视图分叉：生效视图=快照预览/下载/文件历史；草稿视图=
 *   继续编辑/开始修订/提交或重新提交编制/草稿预览下载（负责人行）/
 *   文件历史（2026-11-01 简化：行内直接打开 FileHistoryModal，不再切
 *   顶层页签；历史来源/高级恢复入口已取消）；
 * - 新增制度文件：选择文件后先弹分工弹窗（负责人默认手册所有者，可改选/
 *   清空），确认后逐份 files/create 并显式携带 owner_id/note；
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

jest.mock('../detail/FileHistoryModal', () =>
  function FileHistoryModal(props) {
    FileHistoryModal.lastProps = props;
    return null;
  });

// 提交编制成功后的菜单红点刷新钩子单独 mock：本套件聚焦清单/编制状态，
// 红点 store 契约钉死在 layout/__tests__
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
        is_owner: true, is_admin: false,
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
    submitCompile = jest.fn(function (fileId) {
      const idx = this.files.findIndex(f => f.id === fileId);
      return Promise.resolve(idx >= 0 ? this.files[idx] : null);
    });
    // 2026-11-03 固定快照交接：撤回/退回/快照预览（真实成功后由 store
    // 刷新清单与菜单红点；组件只负责确认与成功提示）
    withdrawSubmission = jest.fn(function () { return Promise.resolve({}); });
    returnSubmission = jest.fn(function () { return Promise.resolve({}); });
    fetchSubmissionPreviewUrl = jest.fn(function () {
      return Promise.resolve({
        preview_url: 'http://snapshot', file_name: '甲快照.docx',
        submitted_by_name: '张三', submitted_at: '2026-01-05T09:00:00'});
    });
  }
  return new DetailStore();
});

import {history} from 'libs';
import {http} from 'libs';
import FileListTab from '../detail/FileListTab';
import FileHistoryModal from '../detail/FileHistoryModal';
import store from '../detail/store';
import institutionBadge from '../../../layout/InstitutionBadgeStore';

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
    revision_open: true,
    draft: {revision: 5, file_name: '甲.docx', last_saved_by_name: '张三',
      last_saved_at: '2026-01-02T10:00:00'},
    active_session: null,
    // 2026-10-31 负责人独占：默认当前账号是负责人（行编辑入口可见）
    assignment: {owner_id: 9, owner_name: '我', note: '', is_mine: true}},
  {id: 12, manual_id: 7, name: '乙.docx', sort_order: 1, is_removed: false,
    revision_open: false,
    draft: {revision: 2, file_name: '乙.docx', last_saved_by_name: '李四',
      last_saved_at: '2026-01-03T09:00:00'},
    active_session: {is_mine: false, user_name: '李四', expires_at: ''},
    assignment: {owner_id: 9, owner_name: '我', note: '', is_mine: true}},
  // 新增文件：待发布集合中但未进入生效版本
  {id: 14, manual_id: 7, name: '新增文件.docx', sort_order: 2,
    is_removed: false, revision_open: true,
    draft: {revision: 1, file_name: '新增文件.docx', last_saved_by_name: '张三',
      last_saved_at: null},
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
    my_roles: ['view', 'edit', 'publish'],
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
    expect(columnHeaderTexts(container)).not.toContain('编制状态');
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

  it('首次发布前（无生效版本）：默认显示「修订草稿」视图，编制状态列取代草稿修订/编制提交列', () => {
    store.manual = Object.assign({}, store.manual, {current_version: null});
    container = renderTab();
    const headers = columnHeaderTexts(container);
    expect(headers).toContain('编制状态');
    expect(headers).not.toContain('草稿修订');
    expect(headers).not.toContain('编制提交');
    const text = container.textContent;
    expect(text).toContain('甲.docx');
    expect(text).toContain('修订中 · 有未发布修改');
    // 负责人兼发布权且草稿待发布 → 可直接纳入整套发布；非我负责的新增文件
    // → 待负责人提交待发布核对；乙有进行中的编辑会话（draft-status
    // unconfirmed）→ 编制中，绝不显示「无需提交」
    expect(text).toContain('可直接纳入整套发布');
    expect(text).toContain('待负责人提交待发布核对');
    expect(text).toContain('编制中');
    // 「最后保存」为编制状态列的次要信息（rN 不再作为列值）
    expect(text).toContain('最后保存 2026-01-02 10:00:00');
    expect(text).not.toContain('r5');
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

  it('草稿视图呈现 状态（服务端关系+修订状态合并）/编制状态/最后保存', () => {
    const text = container.textContent;
    expect(columnHeaderTexts(container)).toContain('编制状态');
    expect(columnHeaderTexts(container)).not.toContain('草稿修订');
    expect(columnHeaderTexts(container)).not.toContain('编制提交');
    expect(text).toContain('甲.docx');
    expect(text).toContain('修订中 · 有未发布修改');
    expect(text).toContain('已改名');
    expect(text).toContain('李四 编辑中');
    expect(text).toContain('新增待发布');
    // 编制状态：甲（有效负责人兼发布权，待发布草稿）→ 可直接纳入整套发布；
    // 乙（draft-status unconfirmed：编辑会话占用）→ 编制中；新增文件
    // （非我有效负责）→ 待负责人提交待发布核对；已发布无变化才显示「无需提交」
    expect(text).toContain('可直接纳入整套发布');
    expect(text).toContain('待负责人提交待发布核对');
    expect(text).toContain('编制中');
    // 最后保存时间为编制状态的次要信息（服务端草稿 last_saved_at）
    expect(text).toContain('最后保存 2026-01-02 10:00:00');
    expect(text).toContain('尚无保存记录');
    // 说明文案明确：提交会创建固定不可变快照并冻结内容（不再有"无副本"口径）
    expect(text).toContain('尚未生效');
    expect(text).toContain('固定不可变内容快照');
    expect(text).toContain('旧版提交记录不可用于发布');
    expect(text).not.toContain('系统不保存提交时刻的文件副本');
    expect(text).toContain('编辑仅限文件负责人');
    // 待发布清单语义：每份上传文件单独加入待发布清单；移除仅退出待发布
    // 清单，发布后才影响新版本（历史发布版本不受影响）
    expect(text).toContain('上传内容直接作为该文件草稿');
    expect(text).toContain('单独加入待发布清单');
    expect(text).toContain('移除文件只让该文件退出待发布清单');
    expect(text).toContain('发布后才影响新版本');
    expect(text).toContain('历史版本不受影响');
  });

  it('已发布无待发布变化且我是负责人：状态=无需提交且不渲染「提交待发布核对」入口', () => {
    // 已发布且 revision_open=false 的文件没有需要交接的草稿：入口与
    // 「无需提交」Tag 必须同时收敛（不能出现可点击但无意义的提交入口）
    store.draftStatus = {
      ...DRAFT_STATUS,
      items: [{file_id: 12, name: '乙.docx', status: 'unchanged',
        has_draft: true, draft_revision: 2, revision_open: false,
        renamed: false, current_name: null, unconfirmed_reason: null,
        unconfirmed_message: null, session: null}],
    };
    store.files = [{...FILES[1], revision_open: false, active_session: null,
      submission: null}];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('无需提交');
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
    expect(findButton(container, '重新提交')).toBeUndefined();
  });

  it('预览待发布草稿：走草稿端点，预览标题=预览待发布草稿：文件名（不带 rN）', async () => {
    const previewBtn = findButton(container, '预览草稿');
    expect(previewBtn).not.toBeUndefined();
    expect(previewBtn.textContent.replace(/\s+/g, '')).toBe('预览草稿');
    act(() => {
      previewBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/draft/preview-url/');
    const title = document.querySelector('.ant-modal-title');
    expect(title.textContent).toBe('预览待发布草稿：甲.docx');
    expect(title.textContent).not.toContain('r5');
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

  it('编制状态：待发布人核对（不可重复提交）/提交已失效（可重新提交）/快照不冒充草稿', () => {
    // 收窄为"纯负责人"（无发布权）：stale 行才会落到「提交已失效」而不是
    // 「可直接纳入整套发布」（后者仅对兼发布权的有效负责人成立）
    store.manual = {...store.manual, is_owner: false, my_roles: ['view', 'edit']};
    store.files = [
      // 有效提交固定快照（frozen）：pending 不可重复提交，可撤回
      {...FILES[0], submission: {status: 'pending', state: 'submitted',
        frozen: true, submitted_at: '2026-01-05T09:00:00',
        submitted_by_name: '张三', submission_revision: 5, draft_revision: 5,
        snapshot: {file_name: '甲快照.docx'}}},
      // 提交失效且仍有待发布轮次（revision_open）→ 提交已失效/需重新提交
      {...FILES[1], revision_open: true, active_session: null,
        submission: {status: 'pending', state: 'stale',
          submitted_at: '2026-01-04T09:00:00', submitted_by_name: '李四',
          submission_revision: 1, draft_revision: 3}},
    ];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    const text = container.textContent;
    expect(text).toContain('待发布人核对');
    expect(text).toContain('提交已失效（需重新提交）');
    // 有效快照：不渲染可重复提交入口，改为不可点击「待发布人核对」；
    // 有效负责人可「撤回提交」
    const pendingBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '待发布人核对');
    expect(pendingBtn).not.toBeUndefined();
    expect(pendingBtn.disabled).toBe(true);
    expect(findButton(container, '撤回提交')).not.toBeUndefined();
    // 失效行渲染「重新提交」入口
    expect(findButton(container, '重新提交')).not.toBeUndefined();
    // 旧"无副本"口径必须消失（改为固定快照语义）
    expect(text).not.toContain('系统不保存提交时刻的文件副本');
  });

  it('固定快照冻结文件：预览/下载改读 submission 快照端点，标题含提交人与提交时间', async () => {
    store.manual = {...store.manual, is_owner: false, my_roles: ['view', 'edit']};
    store.files = [
      {...FILES[0], revision_open: false, active_session: null,
        submission: {status: 'pending', frozen: true,
          submitted_at: '2026-01-05T09:00:00', submitted_by_name: '张三',
          submission_revision: 5, draft_revision: 5,
          snapshot: {file_name: '甲快照.docx'}}},
    ];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    const text = container.textContent;
    // 冻结行不渲染编辑/草稿预览下载入口，改提供待核对快照动作
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '预览草稿')).toBeUndefined();
    expect(findButton(container, '预览待核对快照')).not.toBeUndefined();
    expect(findButton(container, '下载待核对快照')).not.toBeUndefined();
    expect(text).toContain('已冻结');
    act(() => {
      findButton(container, '预览待核对快照')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchSubmissionPreviewUrl).toHaveBeenCalledWith(11);
    // 快照预览不得调用草稿预览端点
    expect(http.get).not.toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/draft/preview-url/');
    const title = document.querySelector('.ant-modal-title');
    expect(title.textContent).toBe(
      '预览待核对快照：甲快照.docx（提交人 张三，提交时间 2026-01-05 09:00:00）');
  });

  it('重新提交确认后经 store.submitCompile 提交，成功后刷新清单与菜单红点', async () => {
    store.manual = {...store.manual, is_owner: false, my_roles: ['view', 'edit']};
    store.files = [
      {...FILES[1], revision_open: true, active_session: null,
        submission: {state: 'stale', submitted_at: '2026-01-04T09:00:00',
          submitted_by_name: '李四', submission_revision: 1, draft_revision: 3}},
    ];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    const resubmitBtn = findButton(container, '重新提交');
    expect(resubmitBtn).not.toBeUndefined();
    act(() => {
      resubmitBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    // 确认窗标题=重新提交，提示记录当前草稿修订号；不发请求
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).not.toBeNull();
    expect(confirm.textContent).toContain('重新提交：乙.docx');
    expect(confirm.textContent).toContain('当前草稿修订号 r2');
    expect(store.submitCompile).not.toHaveBeenCalled();
    await act(async () => {
      confirm.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.submitCompile).toHaveBeenCalledWith(12);
    expect(require('antd').message.success).toHaveBeenCalled();
    // 真实成功后刷新清单（服务端权威数据）与菜单红点，不做乐观更新
    expect(store.fetchFiles).toHaveBeenCalledWith(7);
    expect(institutionBadge.fetch).toHaveBeenCalled();
  });

  it('负责人编辑会话进行中：提交/重新提交按钮禁用并提示先保存并结束编辑', () => {
    store.files = [
      {...FILES[0], revision_open: true,
        active_session: {is_mine: true, user_name: '我', expires_at: ''}},
    ];
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    const submitBtn = findButton(container, '提交待发布核对');
    expect(submitBtn).not.toBeUndefined();
    expect(submitBtn.disabled).toBe(true);
  });
});

describe('FileListTab（草稿视图：入口权限与状态异常）', () => {
  beforeEach(() => {
    container = renderTab();
    switchView(container, '修订草稿');
  });

  /** 全部行改为非我负责（负责人独占收窄用例的夹具）。
   *  同时收窄 is_owner=false：二轮权限模型起所有者对任意文件有编辑/
   *  提交入口，负责人独占语义只对非所有者成立 */
  function unassignAll() {
    store.manual = {...store.manual, is_owner: false};
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

  it('有效负责人行（is_effective_owner）渲染提交待发布核对接入；非负责人行不渲染', () => {
    // 默认夹具：甲/乙由我有效负责，提交待发布核对可见
    expect(findButton(container, '提交待发布核对')).not.toBeUndefined();
    // 非有效负责人：提交入口消失（且编辑入口被收窄，见下一用例）
    unassignAll();
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
    expect(findButton(container, '重新提交')).toBeUndefined();
  });

  it('手册所有者非文件有效负责人：不渲染提交入口（不得代提交，后端同口径）', () => {
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
    // store.manual.is_owner=true（所有者可编辑任意文件），但提交入口仍以
    // 文件负责人身份为唯一依据
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
    expect(findButton(container, '重新提交')).toBeUndefined();
    expect(findButton(container, '继续编辑')).not.toBeUndefined();
  });

  it('非负责人的编制授权账号：无开始修订/继续编辑/草稿预览下载，显示「编辑限负责人」占位提示', () => {
    unassignAll();
    expect(findButton(container, '开始修订')).toBeUndefined();
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '预览草稿')).toBeUndefined();
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
    // 仅 view 授权（无 can_view 授权位时不可见发布版，开关已退役）→ 只有草稿视图
    const text = container.textContent;
    expect(text).toContain('甲.docx');
    expect(findButton(container, '预览草稿')).toBeUndefined();
    expect(findButton(container, '继续编辑')).toBeUndefined();
    expect(findButton(container, '开始修订')).toBeUndefined();
    // 负责人只读（无分工入口链接）
    const ownerLinks = Array.from(container.querySelectorAll('a'))
      .filter(a => a.textContent.includes('未分配'));
    expect(ownerLinks.length).toBe(0);
  });

  it('文件历史按 file_id 直接打开弹窗（草稿视图行，不切顶层页签）', () => {
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    act(() => {
      ReactDOM.render(<FileListTab/>, container);
    });
    switchView(container, '修订草稿');
    const historyBtn = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '文件历史');
    act(() => {
      historyBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(FileHistoryModal.lastProps.visible).toBe(true);
    expect(FileHistoryModal.lastProps.fileId).toBe(11);
    expect(FileHistoryModal.lastProps.fileName).toBe('甲.docx');
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
    expect(columnHeaderTexts(container)).not.toContain('编制状态');
    expect(columnHeaderTexts(container)).not.toContain('编制提交');
    expect(columnHeaderTexts(container)).not.toContain('草稿修订');
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

/** 表体行：按文件名包含匹配（行操作按钮定位用） */
function rowOf(root, name) {
  return Array.from(root.querySelectorAll('.ant-table-row'))
    .find(el => el.textContent.includes(name));
}

/** 行内按钮：按归一化后的文本精确匹配（antd 两字中文按钮可能插空格） */
function rowAction(root, name, text) {
  const row = rowOf(root, name);
  if (!row) return undefined;
  const needle = text.replace(/\s+/g, '');
  return Array.from(row.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === needle);
}

/** 选择文件并触发 change（隐藏 input 的有效性由用例单独断言） */
async function pickFiles(input, files) {
  await act(async () => {
    Object.defineProperty(input, 'files', {value: files, configurable: true});
    input.dispatchEvent(new Event('change', {bubbles: true}));
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

describe('FileListTab（新增制度文件批量上传）', () => {
  it('选择文件先弹分工弹窗（默认负责人=手册所有者），确认后才逐份 files/create 并携带 owner_id/note', async () => {
    const {message} = require('antd');
    message.warning.mockClear();
    message.success.mockClear();
    store.manual = Object.assign({}, store.manual, {owner_id: 9});
    http.get.mockResolvedValue([{id: 9, name: '我'}, {id: 10, name: '同事'}]);
    container = renderTab();
    // 默认生效视图：新增入口位于「修订草稿」视图顶部
    expect(findButton(container, '新增待发布文件')).toBeUndefined();
    switchView(container, '修订草稿');
    const uploadBtn = findButton(container, '新增待发布文件');
    expect(uploadBtn).not.toBeUndefined();
    // 隐藏 input 由 ref 程序触发：全页仅一个，且不嵌套在按钮/标签内
    const inputs = container.querySelectorAll('input[type="file"]');
    expect(inputs.length).toBe(1);
    expect(inputs[0].hasAttribute('multiple')).toBe(true);
    expect([inputs[0].closest('button'), inputs[0].closest('label')])
      .toEqual([null, null]);
    const clickSpy = jest.spyOn(inputs[0], 'click').mockImplementation(() => {});
    uploadBtn.click();
    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
    // 选择 2 份文件：只暂存，不立即创建，先弹分工弹窗
    await pickFiles(inputs[0], [
      new File(['a'], 'A.docx', {type: 'application/octet-stream'}),
      new File(['b'], 'B.docx', {type: 'application/octet-stream'}),
    ]);
    await flush();
    expect(http.post).not.toHaveBeenCalled();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('新增待发布文件分工（2 份）');
    expect(modal.textContent).toContain('A.docx');
    expect(modal.textContent).toContain('B.docx');
    // 新增文件语义：逐份进入待发布清单（不是批量分工整体生效）
    expect(modal.textContent).toContain('上传文件作为待发布文件的当前草稿');
    // 负责人候选走制度模块专用接口 assignment-owners（不是账号管理列表）
    const ownerUrls = http.get.mock.calls.map(c => c[0]);
    expect(ownerUrls).toContain(
      '/api/institution/manuals/7/assignment-owners/');
    expect(ownerUrls).not.toContain('/api/account/user/');
    // 确认后逐份创建：每个上传文件各建一个独立制度文件与当前草稿
    http.post.mockResolvedValueOnce({id: 21, name: 'A.docx',
      draft: {revision: 1, file_name: 'A.docx'}});
    http.post.mockResolvedValueOnce({id: 22, name: 'B.docx',
      draft: {revision: 1, file_name: 'B.docx'}});
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).toHaveBeenCalledTimes(2);
    const urls = http.post.mock.calls.map(c => c[0]);
    expect(urls).toEqual([
      '/api/institution/manuals/7/files/create/',
      '/api/institution/manuals/7/files/create/',
    ]);
    const bodies = http.post.mock.calls.map(c => c[1]);
    expect(bodies.every(b => b instanceof FormData)).toBe(true);
    // 每份文件各自一条独立请求（各自独立条目+草稿，绝不追加到同一项）
    expect(bodies[0].get('file')).toBeInstanceOf(File);
    expect(bodies[1].get('file')).toBeInstanceOf(File);
    expect(bodies[0].get('file').name).toBe('A.docx');
    expect(bodies[1].get('file').name).toBe('B.docx');
    // 负责人显式携带（默认手册所有者），不省略字段
    expect(bodies[0].get('owner_id')).toBe('9');
    expect(bodies[1].get('owner_id')).toBe('9');
    // 未填写分工说明时不携带该字段
    expect(bodies[0].get('note')).toBeNull();
    // 不再有 draft_error 类警示：成功提示只等真实响应后给出
    expect(message.warning).not.toHaveBeenCalled();
    // 成功后刷新清单（fetchDetail → 详情/清单/草稿状态重新加载）
    expect(store.fetchDetail).toHaveBeenCalledWith(7);
    expect(message.success).toHaveBeenCalledWith(
      expect.stringContaining('已新增 2 份待发布文件'));
  });

  it('单个文件创建失败：由拦截器提示一次，无 draft_error 警示，其余文件继续创建', async () => {
    const {message} = require('antd');
    message.warning.mockClear();
    message.success.mockClear();
    store.manual = Object.assign({}, store.manual, {owner_id: 9});
    http.get.mockResolvedValue([{id: 9, name: '我'}]);
    container = renderTab();
    switchView(container, '修订草稿');
    const inputs = container.querySelectorAll('input[type="file"]');
    await pickFiles(inputs[0], [
      new File(['a'], 'A.docx', {type: 'application/octet-stream'}),
      new File(['b'], 'B.doc', {type: 'application/octet-stream'}),
    ]);
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    http.post.mockResolvedValueOnce({id: 21, name: 'A.docx',
      draft: {revision: 1, file_name: 'A.docx'}});
    http.post.mockRejectedValueOnce(
      '文件「B.doc」.doc 转换为 .docx 失败，未创建制度文件，请改用 .docx 上传或联系管理员');
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    // 失败的那份不中断其余文件：仍请求了 2 次（各自独立条目）
    expect(http.post).toHaveBeenCalledTimes(2);
    // 拦截器已提示单个失败：业务代码不重复弹错、也不弹 draft_error 警示
    expect(message.error).not.toHaveBeenCalled();
    expect(message.warning).not.toHaveBeenCalled();
    // 仅真实成功的文件计入成功提示（失败那份不冒充成功）
    expect(message.success).toHaveBeenCalledWith(
      expect.stringContaining('已新增 1 份待发布文件'));
  });

  it('未预填负责人（手册所有者未知）时不选择：显式提交空串 owner_id=未分配', async () => {
    store.manual = Object.assign({}, store.manual, {owner_id: null});
    http.get.mockResolvedValue([]);
    container = renderTab();
    switchView(container, '修订草稿');
    const inputs = container.querySelectorAll('input[type="file"]');
    const file = new File(['a'], 'A.docx', {type: 'application/octet-stream'});
    await pickFiles(inputs[0], [file]);
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    http.post.mockResolvedValueOnce({id: 21, name: 'A.docx',
      draft: {revision: 1, file_name: 'A.docx'}});
    await act(async () => {
      modal.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).toHaveBeenCalledTimes(1);
    expect(http.post.mock.calls[0][1].get('owner_id')).toBe('');
  });

  it('分工弹窗取消：不创建任何文件', async () => {
    http.get.mockResolvedValue([]);
    container = renderTab();
    switchView(container, '修订草稿');
    const inputs = container.querySelectorAll('input[type="file"]');
    await pickFiles(inputs[0],
      [new File(['a'], 'A.docx', {type: 'application/octet-stream'})]);
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    // 取消按钮=footer 内非主按钮（antd 默认文案随 locale 变化，不按文本断言）
    const cancelBtn = modal.querySelector(
      '.ant-modal-footer .ant-btn:not(.ant-btn-primary)');
    expect(cancelBtn).not.toBeNull();
    await act(async () => {
      cancelBtn.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).not.toHaveBeenCalled();
  });

  it('0 文件（默认修订草稿视图）：新增制度文件入口仍可见，串联提示上传直接生成草稿', () => {
    store.files = [];
    store.manual = Object.assign({}, store.manual, {current_version: null});
    container = renderTab();
    // 首次发布前默认视图=修订草稿
    expect(findButton(container, '新增待发布文件')).not.toBeUndefined();
    expect(container.textContent).toContain('该制度还没有待发布文件');
    expect(container.textContent).toContain('上传文件作为待发布文件的当前草稿');
  });

  it('新增入口文案：按钮不再并列描述条目与草稿，说明以待发布清单口径开头', () => {
    store.manual = Object.assign({}, store.manual, {owner_id: 9});
    container = renderTab();
    switchView(container, '修订草稿');
    const uploadBtn = findButton(container, '新增待发布文件');
    expect(uploadBtn).not.toBeUndefined();
    // 按钮文案=名称+格式与多选提示，不再包含「条目+草稿」并列描述
    expect(uploadBtn.textContent.replace(/\s+/g, ''))
      .toBe('新增待发布文件（.doc/.docx，可多选）');
    const text = container.textContent.replace(/\s+/g, '');
    expect(text).toContain(
      '本视图是待发布的工作内容（尚未生效）：每份上传文件单独加入待发布清单，'
      + '上传内容直接作为该文件草稿');
    // 冻结文件（已提交待发布核对）不再打开当前草稿，改打开固定快照
    expect(text).toContain('未冻结文件的预览与下载打开当前草稿');
    expect(text).toContain('改为预览/下载待核对固定快照');
    // 整套发布/移除文件/负责人/编制状态/文件历史说明保留
    expect(text).toContain('整套发布后才会成为新的生效版本');
    expect(text).toContain('移除文件只让该文件退出待发布清单');
    expect(text).toContain('负责人是当前责任归属');
    expect(text).toContain('「编制状态」是提交待发布核对的固定快照状态');
    expect(text).toContain('「文件历史」查阅');
    expect(text).toContain('新增文件请使用上方按钮，并先指定负责人');
    // 后台术语不再出现在用户可见说明中
    expect(text).not.toContain('每个文件各建一个独立制度文件');
    expect(text).not.toContain('独立制度文件与当前草稿');
  });

  it('非手册所有者/制度管理员：不渲染新增入口，只给只读说明', () => {
    store.manual = Object.assign({}, store.manual, {is_owner: false,
      is_admin: false});
    container = renderTab();
    switchView(container, '修订草稿');
    expect(findButton(container, '新增待发布文件')).toBeUndefined();
    expect(container.querySelectorAll('input[type="file"]').length).toBe(0);
    expect(container.textContent).toContain('仅限手册所有者或制度管理员');
  });
});

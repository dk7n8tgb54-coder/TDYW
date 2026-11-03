/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单「文件历史」行入口行为测试（jsdom + ReactDOM，2026-11-01 简化版）：
 * - 「文件历史」是两个清单视图（当前生效版本/修订草稿）共用的唯一历史
 *   入口：行内点击按 file_id + 文件名直接打开 FileHistoryModal（弹窗，
 *   不切顶层页签、不设置任何全局预选）；仅查看角色同样可用；
 *   两个视图都不提供「更换来源」入口。
 * - 原稿历史与「从历史原稿重建草稿」已不在界面展示：两个视图（任何
 *   权限/负责人状态）都不渲染「高级恢复」入口，原 AdvancedRecoveryModal
 *   已删除。
 * - 弹窗关闭后清单视图、滚动位置与行勾选保持不变（模拟 onClose 回调
 *   验证 FileListTab 不重置任何清单状态）。
 * FileListTab.test.js 超过 800 行门禁后本套件拆分自该文件，夹具与 mock
 * 口径与其一致。
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
    startRevision = jest.fn(function () {
      return Promise.resolve({resumed: false, started: true,
        needs_repair: false});
    });
    batchAssignFiles = jest.fn(function (fileIds) {
      return Promise.resolve({count: fileIds.length, files: []});
    });
  }
  return new DetailStore();
});

import FileListTab from '../detail/FileListTab';
import FileHistoryModal from '../detail/FileHistoryModal';
import store from '../detail/store';

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
];

const CURRENT_FILES = {
  version_id: 9, version_no: 3, change_note: 'v3 发布',
  previous_version_no: 2,
  items: [
    {id: 101, manual_file_id: 11, file_name: '甲.docx',
      sort_order: 0, file_size: 2048, file_hash: 'aaaa1111',
      change_type: 'modified'},
    {id: 102, manual_file_id: 12, file_name: '乙.docx',
      sort_order: 1, file_size: 1024, file_hash: 'bbbb2222',
      change_type: 'unchanged'},
  ],
  removed_items: [],
};

const DRAFT_STATUS = {
  has_current_version: true, current_version_no: 3,
  items: [
    {file_id: 11, name: '甲.docx', status: 'modified', has_draft: true,
      draft_revision: 5, revision_open: true, renamed: false,
      current_name: null,
      unconfirmed_reason: null, unconfirmed_message: null, session: null},
    {file_id: 12, name: '乙.docx', status: 'unchanged', has_draft: true,
      draft_revision: 2, revision_open: false, renamed: false,
      current_name: null,
      unconfirmed_reason: null, unconfirmed_message: null, session: null},
  ],
  removed_items: [],
  summary: {total_files: 2, modified: 1, added: 0, unconfirmed: 0,
    removed: 0, renamed: 0, reordered: false, revising: 1,
    has_current_version: true, has_pending_changes: true,
    determinable: true, consistent: false},
};

function renderTab(props = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<FileListTab {...props}/>, container);
  });
  return container;
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

function findButton(root, text) {
  const needle = String(text).replace(/\s+/g, '');
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(needle));
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
    is_owner: true, is_admin: false,
    current_version: {id: 9, version_no: 3}};
  store.files = FILES;
  store.isFetchingFiles = false;
  store.currentFiles = CURRENT_FILES;
  store.currentFilesError = '';
  store.draftStatus = DRAFT_STATUS;
  store.draftStatusError = '';
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

describe('FileListTab（文件历史入口：两视图共用，按 file_id 开弹窗）', () => {
  it('生效视图行「文件历史」：按 file_id+文件名直接打开弹窗，不依赖页签跳转回调', () => {
    container = renderTab(); // 不传 onOpenFileHistory：详情页已不再下发该回调
    const btn = rowAction(container, '甲.docx', '文件历史');
    expect(btn).not.toBeUndefined();
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(FileHistoryModal.lastProps.visible).toBe(true);
    expect(FileHistoryModal.lastProps.fileId).toBe(11);
    expect(FileHistoryModal.lastProps.fileName).toBe('甲.docx');
  });

  it('修订草稿视图行「文件历史」：同样按 file_id 打开弹窗（同一 file_id）', () => {
    container = renderTab();
    switchView(container, '修订草稿');
    const btn = rowAction(container, '甲.docx', '文件历史');
    expect(btn).not.toBeUndefined();
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(FileHistoryModal.lastProps.visible).toBe(true);
    expect(FileHistoryModal.lastProps.fileId).toBe(11);
    expect(FileHistoryModal.lastProps.fileName).toBe('甲.docx');
  });

  it('仅查看角色也能在生效视图进入文件历史（无草稿域入口）', () => {
    const {hasPermission} = require('libs');
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view');
    store.manual = Object.assign({}, store.manual, {my_roles: ['view'],
      is_owner: false, is_admin: false});
    container = renderTab();
    // 仅查看角色只有生效视图（无切换控件、无草稿域入口）
    expect(container.querySelector('.ant-segmented')).toBeNull();
    expect(findButton(container, '继续编辑')).toBeUndefined();
    const btn = rowAction(container, '甲.docx', '文件历史');
    expect(btn).not.toBeUndefined();
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(FileHistoryModal.lastProps.visible).toBe(true);
    expect(FileHistoryModal.lastProps.fileId).toBe(11);
  });

  it('弹窗关闭后清单视图、滚动内容与行勾选保持不变', () => {
    container = renderTab();
    switchView(container, '修订草稿');
    // 勾选一行 + 打开弹窗
    const checkbox = rowOf(container, '甲.docx')
      .querySelector('.ant-checkbox-input');
    act(() => {
      checkbox.click();
    });
    expect(container.textContent).toContain('已选 1 份文件');
    act(() => {
      rowAction(container, '甲.docx', '文件历史')
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(FileHistoryModal.lastProps.visible).toBe(true);
    // 模拟弹窗关闭回调：清单状态不得被重置
    act(() => {
      FileHistoryModal.lastProps.onClose();
    });
    expect(FileHistoryModal.lastProps.visible).toBe(false);
    expect(container.textContent).toContain('已选 1 份文件');
    // 活动视图仍是修订草稿（批量分工栏只在草稿视图渲染）
    expect(rowAction(container, '甲.docx', '继续编辑')).not.toBeUndefined();
  });

  it('两个视图都不提供「更换来源」入口（日常更换来源已取消）', () => {
    container = renderTab();
    expect(container.textContent).not.toContain('更换来源');
    switchView(container, '修订草稿');
    expect(container.textContent).not.toContain('更换来源');
  });
});

describe('FileListTab（原稿历史与高级恢复入口已取消）', () => {
  it('生效视图不渲染「高级恢复」（不混入生效版本的历史查阅）', () => {
    container = renderTab();
    expect(rowAction(container, '甲.docx', '高级恢复')).toBeUndefined();
    expect(container.textContent).not.toContain('从历史原稿重建草稿');
  });

  it('修订草稿视图也不渲染「高级恢复」，负责人/所有者同样不出现', () => {
    // 默认夹具：当前账号既是所有者又是负责人——入口仍不得出现
    container = renderTab();
    switchView(container, '修订草稿');
    expect(rowAction(container, '甲.docx', '高级恢复')).toBeUndefined();
    expect(container.textContent).not.toContain('从历史原稿重建草稿');
  });

  it('非负责人（持编制授权未指派）与手册停用：同样无高级恢复入口', () => {
    store.files = FILES.map(f => f.id === 11
      ? Object.assign({}, f, {assignment: {owner_id: 5, owner_name: '李四',
        note: '', is_mine: false}})
      : f);
    store.manual = Object.assign({}, store.manual, {is_owner: false,
      is_admin: false, status: 'archived'});
    container = renderTab();
    switchView(container, '修订草稿');
    expect(rowAction(container, '甲.docx', '高级恢复')).toBeUndefined();
  });
});

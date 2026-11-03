/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 「文件清单行 → 文件历史弹窗」全链路集成测试（jsdom + ReactDOM）：
 * 真实 detail/index.js（antd Tabs 受控页签）+ 真实 FileListTab +
 * 真实 FileHistoryModal + 真实 detail store，仅 mock libs.http 与
 * PreviewModal。钉死 2026-11-01 文件历史简化后的行为：
 * - 顶层页签不再有「文件历史」；行内「文件历史」按 file_id 直接开弹窗
 *   （不切顶层页签），弹窗标题=制度文件名，内部 发布记录/操作记录 两页签；
 * - 两种清单视图（当前生效版本/修订草稿）的行入口都能打开对应文件的
 *   弹窗并请求其发布/操作记录；
 * - 连续打开不同文件：旧文件数据被清空，展示内容与当前文件一致
 *   （A→B→A 稳定）；
 * - 弹窗关闭后清单视图、行勾选保持不变；
 * - 操作记录翻页携带当前文件 file_id；全程不产生 originals-overview 调用；
 * - 修订草稿视图不再有「高级恢复」入口（原稿历史不在界面展示）。
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

jest.mock('../detail/PreviewModal', () => function PreviewModal() {
  return null;
});

import {http} from 'libs';
import InstitutionManualDetail from '../detail';
import store from '../detail/store';

const MANUAL = {id: 7, name: '跳转验证手册', status: 'active',
  my_roles: ['view', 'edit', 'publish'],
  current_version: {id: 9, version_no: 3,
    published_at: '2026-03-01T09:00:00', published_by_name: '张三'},
  files_count: 2,
  org_type_display: '部门', org_name: '运行部',
  owner_id: 5, owner_name: '王五',
  // 所有者身份：草稿视图渲染批量分工勾选列（用于弹窗关闭后选择保持断言）
  is_owner: true, is_admin: false};

const FILES = [
  {id: 11, manual_id: 7, name: '甲文件.docx', sort_order: 0,
    is_removed: false, revision_open: false,
    draft: {revision: 3, last_saved_at: '2026-01-02T10:00:00'},
    active_session: null, assignment: null},
  {id: 12, manual_id: 7, name: '乙文件.docx', sort_order: 1,
    is_removed: false, revision_open: false,
    draft: {revision: 1, last_saved_at: '2026-01-03T10:00:00'},
    active_session: null, assignment: null},
];

const CURRENT_FILES = {
  version_id: 9, version_no: 3, change_note: 'v3 发布',
  items: [
    {id: 201, manual_file_id: 11, file_name: '甲文件.docx',
      file_size: 1024, file_hash: 'aaaa1111aaaa1111'},
    {id: 202, manual_file_id: 12, file_name: '乙文件.docx',
      file_size: 2048, file_hash: 'bbbb2222bbbb2222'},
  ],
  removed_items: [],
};

const VERSION_HISTORY = {
  11: {file_id: 11, file_name: '甲文件.docx', items: [
    {version_id: 31, snapshot_id: 301, version_no: 3, change_type: 'modified',
      change_note: '甲文件的修改说明', file_size: 1024,
      file_hash: 'aaaa1111aaaa1111', published_by_name: '张三',
      published_at: '2026-03-01T09:00:00', is_cleaned: false},
  ]},
  12: {file_id: 12, file_name: '乙文件.docx', items: [
    {version_id: 31, snapshot_id: 302, version_no: 3, change_type: 'added',
      change_note: '乙文件首次进入版本', file_size: 2048,
      file_hash: 'bbbb2222bbbb2222', published_by_name: '张三',
      published_at: '2026-03-01T09:00:00', is_cleaned: false},
  ]},
};

function routeGet(url, config) {
  config = config || {};
  if (url.includes('/operation-logs/')) {
    const fileId = config.params && config.params.file_id;
    if (fileId === 11) return Promise.resolve({items: [], total: 30});
    return Promise.resolve({items: [], total: 0});
  }
  const historyMatch = url.match(/files\/(\d+)\/version-history\//);
  if (historyMatch) {
    const payload = VERSION_HISTORY[Number(historyMatch[1])];
    return payload
      ? Promise.resolve(payload)
      : Promise.reject(new Error('no history ' + url));
  }
  if (url.includes('/draft-status/')) {
    return Promise.resolve({
      has_current_version: true, current_version_no: 3,
      items: FILES.map(f => ({file_id: f.id, name: f.name,
        status: 'unchanged', has_draft: true, draft_revision: 1,
        revision_open: false, renamed: false, current_name: null,
        unconfirmed_reason: null, unconfirmed_message: null,
        session: null})),
      removed_items: [],
      summary: {total_files: 2, modified: 0, added: 0, unconfirmed: 0,
        removed: 0, renamed: 0, reordered: false, revising: 0,
        has_current_version: true, has_pending_changes: false,
        determinable: true, consistent: true},
    });
  }
  if (url.includes('/chapters/')) return Promise.resolve([]);
  if (url.includes('/versions/9/files/')) return Promise.resolve(CURRENT_FILES);
  if (url.includes('/versions/')) {
    return Promise.resolve({items: [Object.assign(
      {files: [], removed_items: []}, MANUAL.current_version)], total: 1});
  }
  if (url.endsWith('/files/')) return Promise.resolve(FILES);
  if (url.endsWith('/manuals/7/')) return Promise.resolve(MANUAL);
  return Promise.reject(new Error('unexpected url ' + url));
}

function mockHttp() {
  http.get.mockImplementation(routeGet);
}

function renderPage() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(
      React.createElement(InstitutionManualDetail, {match: {params: {id: '7'}}}),
      container);
  });
  return container;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function clickEl(el) {
  act(() => {
    el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

/** 应用容器内当前激活的顶层页签内容（弹窗 portal 在 container 之外） */
function activePane() {
  const pane = container.querySelector('.ant-tabs-tabpane-active');
  expect(pane).not.toBeNull();
  return pane;
}

function modalEl() {
  return document.querySelector('.ant-modal');
}

/** 点击文件清单中指定文件行的「文件历史」按钮 */
function clickRowHistory(fileName) {
  const row = Array.from(activePane().querySelectorAll('.ant-table-row'))
    .find(el => el.textContent.includes(fileName));
  expect(row).not.toBeUndefined();
  const btn = Array.from(row.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === '文件历史');
  expect(btn).not.toBeUndefined();
  clickEl(btn);
}

/** 点击文件清单页签内 Segmented 视图切换（修订草稿/当前生效版本） */
function clickSegmented(label) {
  const item = Array.from(container.querySelectorAll('.ant-segmented-item'))
    .find(el => el.textContent.includes(label));
  expect(item).not.toBeUndefined();
  clickEl(item.querySelector('input'));
}

/** 勾选文件清单行选择框（批量分工勾选列） */
function checkRow(fileName) {
  const row = Array.from(activePane().querySelectorAll('.ant-table-row'))
    .find(el => el.textContent.includes(fileName));
  expect(row).not.toBeUndefined();
  const checkbox = row.querySelector('.ant-checkbox-input');
  expect(checkbox).not.toBeNull();
  clickEl(checkbox);
}

function tabTitles() {
  return Array.from(container.querySelectorAll('.ant-tabs-tab'))
    .map(el => el.textContent.trim());
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  mockHttp();
  store.reset();
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    container = null;
  }
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
  document.querySelectorAll('.ant-modal, .ant-modal-wrap, .ant-modal-mask')
    .forEach(el => el.remove());
});

describe('文件清单行 → 文件历史弹窗（真实页签生命周期）', () => {
  it('顶层无「文件历史」页签', async () => {
    container = renderPage();
    await flush();
    // 顶层页签只减不增：「文件历史」页签已取消
    expect(tabTitles()).toEqual(
      ['文件清单', '版本与发布', '操作记录', '权限配置']);
    expect(tabTitles()).not.toContain('文件历史');
  });

  it('行入口按 file_id 开弹窗且不切顶层页签', async () => {
    container = renderPage();
    await flush();
    // 生效视图行「文件历史」：弹窗打开，顶层激活页签仍是文件清单
    clickRowHistory('甲文件.docx');
    await flush();
    expect(modalEl()).not.toBeNull();
    expect(document.querySelector('.ant-modal-title').textContent)
      .toBe('文件历史：甲文件.docx');
    expect(activePane().textContent).toContain('甲文件.docx');
    expect(activePane().textContent).toContain('文件名');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/version-history/');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/operation-logs/',
      expect.objectContaining({params: expect.objectContaining(
        {file_id: 11, page: 1})}));
    // 弹窗内只有 发布记录/操作记录 两个子页签，默认发布记录
    const modalTabs = Array.from(
      modalEl().querySelectorAll('.ant-tabs-tab')).map(el => el.textContent.trim());
    expect(modalTabs).toEqual(['发布记录', '操作记录']);
    expect(modalEl().textContent).toContain('甲文件的修改说明');
    // 全程不产生 originals-overview 调用（前端管线已随历史来源入口取消）
    expect(http.get).not.toHaveBeenCalledWith(
      expect.stringContaining('/originals-overview/'));
  });

  it('弹窗关闭后生效视图保持（视图与行操作不受弹窗影响）', async () => {
    container = renderPage();
    await flush();
    clickRowHistory('甲文件.docx');
    await flush();
    clickEl(modalEl().querySelector('.ant-modal-close'));
    await flush();
    // 生效视图保持：Segmented 选中项仍是「当前生效版本」
    const selected = container.querySelector('.ant-segmented-item-selected');
    expect(selected.textContent).toContain('当前生效版本');
    // 清单行仍在（弹窗开关不触碰清单数据）
    const row = Array.from(activePane().querySelectorAll('.ant-table-row'))
      .find(el => el.textContent.includes('甲文件.docx'));
    expect(row).not.toBeUndefined();
  });

  it('弹窗关闭后行勾选保持', async () => {
    container = renderPage();
    await flush();
    // 勾选列在修订草稿视图（批量分工属草稿视图操作）
    clickSegmented('修订草稿');
    await flush();
    checkRow('甲文件.docx');
    expect(activePane().textContent).toContain('已选 1 份文件');
    clickRowHistory('甲文件.docx');
    await flush();
    expect(modalEl().textContent).toContain('甲文件的修改说明');

    // 关闭弹窗：勾选保持
    clickEl(modalEl().querySelector('.ant-modal-close'));
    await flush();
    expect(activePane().textContent).toContain('已选 1 份文件');
    const checkedAfterClose = Array.from(
      activePane().querySelectorAll('.ant-table-row'))
      .find(el => el.textContent.includes('甲文件.docx'))
      .querySelector('.ant-checkbox-input').checked;
    expect(checkedAfterClose).toBe(true);
  });
});

describe('文件清单行 → 文件历史弹窗（切换文件与收尾契约）', () => {
  it('连续打开不同文件清空旧数据（A→B→A 稳定）', async () => {
    container = renderPage();
    await flush();
    clickSegmented('修订草稿');
    await flush();
    clickRowHistory('甲文件.docx');
    await flush();
    expect(modalEl().textContent).toContain('甲文件的修改说明');
    clickEl(modalEl().querySelector('.ant-modal-close'));
    await flush();

    // 打开乙文件弹窗：旧文件数据被清空，展示内容与乙一致
    clickRowHistory('乙文件.docx');
    await flush();
    expect(document.querySelector('.ant-modal-title').textContent)
      .toBe('文件历史：乙文件.docx');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/12/version-history/');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/operation-logs/',
      expect.objectContaining({params: expect.objectContaining({file_id: 12})}));
    expect(modalEl().textContent).toContain('乙文件首次进入版本');
    expect(modalEl().textContent).not.toContain('甲文件的修改说明');

    // 连续 A→B→A：再打开甲，重新展示甲的记录
    clickEl(modalEl().querySelector('.ant-modal-close'));
    await flush();
    clickRowHistory('甲文件.docx');
    await flush();
    expect(document.querySelector('.ant-modal-title').textContent)
      .toBe('文件历史：甲文件.docx');
    expect(modalEl().textContent).toContain('甲文件的修改说明');
    expect(modalEl().textContent).not.toContain('乙文件首次进入版本');
  });

  it('修订草稿视图不再有「高级恢复」入口（原稿历史不在界面展示）', async () => {
    container = renderPage();
    await flush();
    clickSegmented('修订草稿');
    await flush();
    const draftButtons = Array.from(
      activePane().querySelectorAll('button'))
      .map(b => b.textContent.replace(/\s+/g, ''));
    expect(draftButtons).not.toContain('高级恢复');
    expect(activePane().textContent).not.toContain('从历史原稿重建草稿');
  });

  it('弹窗操作记录翻页携带当前文件 file_id', async () => {
    container = renderPage();
    await flush();
    clickRowHistory('甲文件.docx');
    await flush();
    // 操作记录子页签首次激活才挂载（rc-tabs 懒挂载）
    const logsTab = Array.from(modalEl().querySelectorAll('.ant-tabs-tab'))
      .find(el => el.textContent.trim() === '操作记录');
    clickEl(logsTab);
    await flush();
    jest.clearAllMocks();
    mockHttp();
    const page2 = modalEl().querySelector('.ant-pagination-item-2');
    expect(page2).not.toBeNull();
    clickEl(page2);
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/operation-logs/',
      expect.objectContaining({params: expect.objectContaining(
        {file_id: 11, page: 2})}));
  });
});

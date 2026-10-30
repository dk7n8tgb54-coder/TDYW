/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 「文件清单 → 变更记录」全链路跳转集成测试（jsdom + ReactDOM）：
 * 真实 detail/index.js（antd Tabs 受控页签，rc-tabs 页签首次激活后保持
 * 挂载）+ 真实 FileListTab + 真实 FileChangeTab + 真实 detail store，
 * 仅 mock libs.http 与 PreviewModal。钉死 2026-10-30 修复的行为：
 * - 首次点击文件行「变更记录」：切页签、预选该文件并请求其发布/操作记录；
 * - 页签已挂载后再次点击另一文件：目标仍被消费（此前仅 componentDidMount
 *   消费 fileChangeTarget，页签保持挂载时二次跳转不生效——本套件复现的
 *   回归场景）；
 * - 连续 A→A→B→A 跳转与同文件重复跳转均稳定，展示记录与选中文件一致；
 * - 操作记录翻页携带当前文件 file_id（originals-overview 行键是 file_id）。
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
  my_roles: ['view', 'edit', 'publish'], editor_can_view_published: true,
  current_version: {id: 9, version_no: 3,
    published_at: '2026-03-01T09:00:00', published_by_name: '张三'},
  files_count: 2, owner_type_display: '部门', owner_name: '运行部'};

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

const OVERVIEW = {files: [
  {file_id: 11, name: '甲文件.docx', sort_order: 0, is_removed: false},
  {file_id: 12, name: '乙文件.docx', sort_order: 1, is_removed: false},
]};

const VERSION_HISTORY = {
  11: {file_id: 11, file_name: '甲文件.docx', items: [
    {version_id: 31, version_no: 3, change_type: 'modified',
      change_note: '甲文件的修改说明', file_size: 1024,
      file_hash: 'aaaa1111aaaa1111', published_by_name: '张三',
      published_at: '2026-03-01T09:00:00', is_cleaned: false},
  ]},
  12: {file_id: 12, file_name: '乙文件.docx', items: [
    {version_id: 31, version_no: 3, change_type: 'added',
      change_note: '乙文件首次进入版本', file_size: 2048,
      file_hash: 'bbbb2222bbbb2222', published_by_name: '张三',
      published_at: '2026-03-01T09:00:00', is_cleaned: false},
  ]},
};

function routeGet(url, config) {
  config = config || {};
  if (url.includes('/operation-logs/')) {
    const fileId = config.params && config.params.file_id;
    if (fileId === 11) {
      return Promise.resolve({items: [
        {id: 1, action: 'save_draft', user_name: '张三',
          created_at: '2026-03-01T10:00:00', detail: '{"file_revision": 6}'},
      ], total: 1});
    }
    return Promise.resolve({items: [], total: 0});
  }
  const historyMatch = url.match(/files\/(\d+)\/version-history\//);
  if (historyMatch) {
    const payload = VERSION_HISTORY[Number(historyMatch[1])];
    return payload
      ? Promise.resolve(payload)
      : Promise.reject(new Error('no history ' + url));
  }
  if (url.includes('/originals-overview/')) return Promise.resolve(OVERVIEW);
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

/** 点击页签栏上的指定页签（真实 rc-tabs 交互） */
function clickTab(container, title) {
  const tab = Array.from(container.querySelectorAll('.ant-tabs-tab'))
    .find(el => el.textContent.trim() === title);
  expect(tab).not.toBeUndefined();
  clickEl(tab);
}

/** 点击文件清单中指定文件行的「变更记录」按钮（在活动页签内查找） */
function clickRowHistory(container, fileName) {
  const pane = activePane();
  const row = Array.from(pane.querySelectorAll('.ant-table-row'))
    .find(el => el.textContent.includes(fileName));
  expect(row).not.toBeUndefined();
  const btn = Array.from(row.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '') === '变更记录');
  expect(btn).not.toBeUndefined();
  clickEl(btn);
}

function activePane() {
  const pane = document.querySelector('.ant-tabs-tabpane-active');
  expect(pane).not.toBeNull();
  return pane;
}

function selectedFileText() {
  const item = activePane().querySelector('.ant-select-selection-item');
  return item ? item.textContent : '';
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
});

describe('文件清单 → 文件变更记录 全链路跳转（真实页签生命周期）', () => {
  it('首次与已挂载后的 A→A→B→A 跳转均预选对应文件并请求其记录', async () => {
    container = renderPage();
    await flush();
    // 默认页签=文件清单，变更记录页签尚未挂载
    expect(activePane().textContent).toContain('甲文件.docx');

    // 1. 首次点击文件甲的「变更记录」：切页签、预选甲、请求甲的两类记录
    clickRowHistory(container, '甲文件.docx');
    await flush();
    expect(activePane().textContent).toContain('发布记录');
    expect(selectedFileText()).toContain('甲文件.docx');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/version-history/');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/operation-logs/',
      expect.objectContaining({params: expect.objectContaining(
        {file_id: 11, page: 1})}));
    expect(activePane().textContent).toContain('甲文件的修改说明');
    expect(activePane().textContent).not.toContain('乙文件首次进入版本');

    // 2. 回到文件清单，再次点击同一文件甲（页签已挂载）：选中保持稳定
    clickTab(container, '文件清单');
    await flush();
    jest.clearAllMocks();
    mockHttp();
    clickRowHistory(container, '甲文件.docx');
    await flush();
    expect(selectedFileText()).toContain('甲文件.docx');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/11/version-history/');

    // 3. 回到文件清单，点击文件乙（页签已挂载——修复前的回归场景）：
    //    必须选中乙并请求乙的记录，展示内容与选中文件一致
    clickTab(container, '文件清单');
    await flush();
    jest.clearAllMocks();
    mockHttp();
    clickRowHistory(container, '乙文件.docx');
    await flush();
    expect(selectedFileText()).toContain('乙文件.docx');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/12/version-history/');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/operation-logs/',
      expect.objectContaining({params: expect.objectContaining(
        {file_id: 12, page: 1})}));
    expect(activePane().textContent).toContain('乙文件首次进入版本');
    expect(activePane().textContent).not.toContain('甲文件的修改说明');
    expect(store.fileChangeTarget).toBeNull();

    // 4. 连续 A→B→A：再点甲，重新选中甲并展示甲的记录
    clickTab(container, '文件清单');
    await flush();
    jest.clearAllMocks();
    mockHttp();
    clickRowHistory(container, '甲文件.docx');
    await flush();
    expect(selectedFileText()).toContain('甲文件.docx');
    expect(activePane().textContent).toContain('甲文件的修改说明');
    expect(activePane().textContent).not.toContain('乙文件首次进入版本');
  });

  it('变更记录页签内手动切换下拉文件：按新文件重新拉取（能力保持）', async () => {
    container = renderPage();
    await flush();
    clickRowHistory(container, '甲文件.docx');
    await flush();
    jest.clearAllMocks();
    mockHttp();
    const select = activePane().querySelector('.ant-select-selector');
    act(() => {
      select.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await flush();
    const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
      .find(o => o.textContent.includes('乙文件.docx'));
    expect(option).not.toBeUndefined();
    clickEl(option);
    await flush();
    expect(selectedFileText()).toContain('乙文件.docx');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/files/12/version-history/');
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/operation-logs/',
      expect.objectContaining({params: expect.objectContaining({file_id: 12})}));
  });

  it('变更记录页签操作记录翻页携带当前文件 file_id', async () => {
    // 乙文件无操作记录（total 0）不渲染翻页；甲文件 total>15 时出现第 2 页
    http.get.mockImplementation((url, config) => {
      if (url.includes('/operation-logs/')) {
        const fileId = (config || {}).params && config.params.file_id;
        if (fileId === 11) return Promise.resolve({items: [], total: 30});
        return Promise.resolve({items: [], total: 0});
      }
      return routeGet(url, config);
    });
    container = renderPage();
    await flush();
    clickRowHistory(container, '甲文件.docx');
    await flush();
    jest.clearAllMocks();
    mockHttp();
    const page2 = activePane().querySelector('.ant-pagination-item-2');
    expect(page2).not.toBeNull();
    clickEl(page2);
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/operation-logs/',
      expect.objectContaining({params: expect.objectContaining(
        {file_id: 11, page: 2})}));
  });
});

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 制度详情页信息层级测试（jsdom + ReactDOM，2026-10-29 交互优化）：
 * - 页签结构：文件清单（默认，由原「当前生效文件」与「草稿工作区」合并，
 *   顶层页签只减不增）→ 版本与发布 → 文件变更记录 → 初始来源 →
 *   操作记录（→ 权限配置）。
 * - 2026-10-29 文件分工替代章节分工：独立的「章节分工」顶层页签取消，
 *   分工入口在文件清单行内；旧章节记录由文件清单页签只读过渡展示。
 * - 页签可见性对所有可见者统一（文件清单对查看/编制/发布角色都渲染，
 *   列内容按权限收窄），不再按发布可见权切换默认页签。
 * - 头部渲染 整套草稿状态摘要 + 发布新版本入口（PublishButton）；
 *   进入详情按权限拉取草稿状态（fetchDraftStatusIfAllowed）。
 * - 文件清单行「变更记录」可切换到文件变更记录页签。
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

// 子页签全部 mock 为可识别文本占位，隔离页签结构与可见性断言
jest.mock('../detail/FileListTab', () =>
  function FileListTab({onOpenFileHistory}) {
    return (
      <div data-testid="file-list-tab">
        FILE_LIST_TAB
        {onOpenFileHistory && (
          <button id="jump-history" onClick={onOpenFileHistory}>跳转变更记录</button>
        )}
      </div>
    );
  });
jest.mock('../detail/VersionsTab', () =>
  function VersionsTab() {
    return <div data-testid="versions-tab">VERSIONS_TAB</div>;
  });
jest.mock('../detail/FileChangeTab', () =>
  function FileChangeTab() {
    return <div data-testid="file-changes-tab">FILE_CHANGES_TAB</div>;
  });
jest.mock('../detail/OriginalsTab', () =>
  function OriginalsTab() {
    return <div data-testid="originals-tab">ORIGINALS_TAB</div>;
  });
jest.mock('../detail/RecordsTab', () =>
  function RecordsTab() {
    return <div data-testid="logs-tab">LOGS_TAB</div>;
  });
jest.mock('../detail/ConfigTab', () =>
  function ConfigTab() {
    return <div data-testid="config-tab">CONFIG_TAB</div>;
  });
jest.mock('../detail/DraftStatusSummary', () =>
  function DraftStatusSummary() {
    return <div data-testid="draft-status-summary">DRAFT_STATUS_SUMMARY</div>;
  });
jest.mock('../detail/PublishButton', () =>
  function PublishButton() {
    return <button data-testid="publish-button">PUBLISH_BUTTON</button>;
  });

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = null;
    @observable isFetching = false;
    @observable error = '';
    _manualOverrides = null;
    fetchDetail = jest.fn(function (id) {
      this.id = id;
      this.manual = Object.assign({id, name: '科室操作手册', status: 'active',
        files_count: 2, my_roles: ['view', 'edit', 'publish'],
        current_version: {id: 9, version_no: 3}},
        this._manualOverrides || {});
      return Promise.resolve();
    });
    fetchVersions = jest.fn(function () { return Promise.resolve(); });
    fetchChapters = jest.fn(function () { return Promise.resolve(); });
    fetchLogs = jest.fn(function () { return Promise.resolve(); });
    fetchDraftStatusIfAllowed = jest.fn(function () { return Promise.resolve(); });
    reset = jest.fn(function () {});
  }
  return new DetailStore();
});

import InstitutionManualDetail from '../detail';
import store from '../detail/store';
import {hasPermission} from 'libs';

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

function activeTabText() {
  return document.querySelector('.ant-tabs-tabpane-active').textContent;
}

function tabTitles(container) {
  return Array.from(container.querySelectorAll('.ant-tabs-tab'))
    .map(el => el.textContent);
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  store._manualOverrides = null;
  // mock store 的 reset 是空实现：必须显式清掉上一用例的 manual——
  // 否则 Tabs 在首个同步渲染即以旧 manual 挂载，activeKey 被锁死
  store.manual = null;
  store.id = null;
  store.error = '';
  // 默认模块权限全放行（与既有套件一致）；可见性用例内收窄为仅页面 view 权限
  // （AuthDiv 依赖 institution.manual.view 作整页入口，必须放行）
  hasPermission.mockImplementation(() => true);
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

describe('制度详情页（信息层级与页签结构）', () => {
  it('默认页签为文件清单（合并页签），页签按层级排序且无「草稿工作区/章节分工」', async () => {
    container = renderPage();
    await flush();
    const titles = tabTitles(container);
    expect(titles).toEqual([
      '文件清单', '版本与发布', '文件变更记录',
      '初始来源', '操作记录', '权限配置',
    ]);
    // 不再有与"草稿工作台"编辑页撞名的只读页签
    expect(titles).not.toContain('草稿工作区');
    expect(titles).not.toContain('当前生效文件');
    // 文件分工替代章节分工：独立页签取消（分工入口在文件清单行内）
    expect(titles).not.toContain('章节分工');
    // 默认激活=文件清单
    expect(activeTabText()).toContain('FILE_LIST_TAB');
  });

  it('详情加载后拉取版本/章节/操作记录与整套草稿状态（按权限）', async () => {
    container = renderPage();
    await flush();
    expect(store.fetchVersions).toHaveBeenCalledWith('7');
    expect(store.fetchChapters).toHaveBeenCalledWith('7');
    expect(store.fetchLogs).toHaveBeenCalledWith('7');
    expect(store.fetchDraftStatusIfAllowed).toHaveBeenCalledWith('7');
  });

  it('头部渲染整套草稿状态摘要与发布新版本入口（发布入口在状态旁）', async () => {
    container = renderPage();
    await flush();
    expect(document.querySelector('[data-testid="draft-status-summary"]'))
      .not.toBeNull();
    expect(document.querySelector('[data-testid="publish-button"]'))
      .not.toBeNull();
  });

  it('仅查看角色（无编制/发布/管理权限）：文件清单仍是默认页签', async () => {
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view');
    store._manualOverrides = {
      my_roles: ['view'],
      current_version: {id: 9, version_no: 2},
    };
    container = renderPage();
    await flush();
    const titles = tabTitles(container);
    expect(titles[0]).toBe('文件清单');
    expect(activeTabText()).toContain('FILE_LIST_TAB');
  });

  it('纯编制授权（无查看授权，不可见发布版）：仍渲染文件清单（列内容由组件收窄）', async () => {
    // 2026-10-31 二轮权限模型：editor_can_view_published 开关已删，
    // 仅 can_edit 授权不再可见发布版
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view');
    store._manualOverrides = {
      my_roles: ['edit'],
      current_version: {id: 9, version_no: 3},
    };
    container = renderPage();
    await flush();
    expect(tabTitles(container)[0]).toBe('文件清单');
    expect(activeTabText()).toContain('FILE_LIST_TAB');
  });

  it('权限配置页签可见性（2026-10-31）：手册所有者无需 config 权限码', async () => {
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view');
    store._manualOverrides = {my_roles: ['view'], is_owner: true,
      is_admin: false};
    container = renderPage();
    await flush();
    expect(tabTitles(container)).toContain('权限配置');
  });

  it('权限配置页签可见性（2026-10-31）：制度管理员（is_admin）无需 config 权限码', async () => {
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view');
    store._manualOverrides = {my_roles: ['view'], is_owner: false,
      is_admin: true};
    container = renderPage();
    await flush();
    expect(tabTitles(container)).toContain('权限配置');
  });

  it('权限配置页签可见性（2026-10-31）：非所有者/管理员的编制角色不渲染', async () => {
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view');
    store._manualOverrides = {my_roles: ['view', 'edit'], is_owner: false,
      is_admin: false};
    container = renderPage();
    await flush();
    expect(tabTitles(container)).not.toContain('权限配置');
  });

  it('文件清单行「变更记录」切换到文件变更记录页签', async () => {
    container = renderPage();
    await flush();
    const jump = document.querySelector('#jump-history');
    expect(jump).not.toBeNull();
    act(() => {
      jump.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(activeTabText()).toContain('FILE_CHANGES_TAB');
  });
});

describe('挂载链发布内容拉取守卫', () => {
  it('无 can_view_published 口径权限：挂载不发版本请求（其余拉取不变）', async () => {
    // 2026-10-31 授权模型：版本历史属已发布内容，后端 VersionListView 以
    // can_view_published 拒绝；挂载链不得产生注定失败的调用（不弹
    // 「手册不存在或无权限访问」toast）
    store._manualOverrides = {
      my_roles: ['edit'],
      current_version: {id: 9, version_no: 3},
    };
    container = renderPage();
    await flush();
    expect(store.fetchVersions).not.toHaveBeenCalled();
    expect(store.fetchChapters).toHaveBeenCalledWith('7');
    expect(store.fetchLogs).toHaveBeenCalledWith('7');
    expect(store.fetchDraftStatusIfAllowed).toHaveBeenCalledWith('7');
  });
});

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 版本与发布页签行为测试（jsdom + ReactDOM）：
 * - 发布主入口已上移为详情头部 PublishButton（发布确认窗口见其专属套件）；
 *   本套件聚焦发布历史、版本文件清单 Modal、整套回退与保留策略状态。
 * - 版本文件清单 Modal：完整文件集合 + 新增/修改/沿用/本版本移除状态，
 *   移除文件不静默隐藏。
 * - 生命周期刷新（发布/回退/废止）统一走 store.refreshAfterLifecycle。
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

jest.mock('../detail/PreviewModal', () => function PreviewModal() {
  return null;
});

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', status: 'active',
      my_roles: ['view', 'edit', 'publish'],
      // 2026-10-31 授权模型：整套回退业务门=所有者/制度管理员
      is_owner: true, is_admin: false,
      current_version: {id: 9, version_no: 3, published_at: '2026-01-01T10:00:00',
        published_by_name: '张三'}};
    @observable versions = [];
    @observable versionsPage = 1;
    @observable versionsTotal = 0;
    @observable versionsError = '';
    @observable files = [];
    @observable currentFiles = null;
    @observable currentFilesError = '';
    @observable isFetchingCurrentFiles = false;
    @observable publishPreview = null;
    @observable isFetchingPublishPreview = false;
    @observable isFetchingVersions = false;
    fetchFiles = jest.fn(function () { return Promise.resolve(); });
    fetchDetail = jest.fn(function () { return Promise.resolve(); });
    fetchVersions = jest.fn(function () { return Promise.resolve(); });
    fetchLogs = jest.fn(function () { return Promise.resolve(); });
    fetchCurrentFiles = jest.fn(function () { return Promise.resolve(); });
    fetchPublishPreview = jest.fn(function () { return Promise.resolve(); });
    fetchDraftStatus = jest.fn(function () { return Promise.resolve(); });
    clearCurrentFiles = jest.fn(function () {});
    refreshAfterLifecycle = jest.fn(function () { return Promise.resolve(); });
  }
  return new DetailStore();
});

import VersionsTab from '../detail/VersionsTab';
import {message} from 'antd';
import * as utils from '../utils';
import {http} from 'libs';
import store from '../detail/store';

const GRANTED = ['institution.manual.view', 'institution.manual.download',
  'institution.manual.publish', 'institution.manual.draft_edit'];

function makeSnap(id, name, over = {}) {
  return Object.assign({id, manual_file_id: id + 100, file_name: name,
    sort_order: 0, file_size: 2048, file_hash: 'abcdef1234567890'}, over);
}

function makeVersion(over = {}) {
  return Object.assign({
    id: 1, version_no: 1, change_note: '初版发布', file_name: '第一章.docx',
    file_size: 2048, published_by_name: '张三',
    published_at: '2026-01-01T10:00:00', is_effective: true, is_current: false,
    files: [makeSnap(5, '第一章.docx')],
  }, over);
}

function renderTab() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(React.createElement(VersionsTab), container);
  });
  return container;
}

function flushAsync() {
  // antd Modal.confirm 经 setTimeout(0) 异步渲染（见 antd/es/modal/confirm.js），
  // 触发链（点击→then→confirm 的 setTimeout）至少要两个宏任务轮次才落到 DOM
  return act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function findButton(container, text) {
  // antd 两字中文按钮会在 DOM 中插入空格（如"重 试"，仅非 link 型），
  // 查找时归一化空白
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(text));
}

beforeEach(() => {
  jest.clearAllMocks();
  utils.downloadFile = jest.fn().mockResolvedValue();
  http.get.mockResolvedValue({version_no: 1, change_note: '初版发布', items: [
    makeSnap(5, '第一章.docx'), makeSnap(6, '第二章.docx', {sort_order: 1}),
  ]});
  http.post.mockResolvedValue({});
  store.files = [];
  store.versions = [];
  store.currentFiles = null;
  store.publishPreview = null;
  store.versionsError = '';
  store.currentFilesError = '';
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

let container = null;

describe('版本文件清单 Modal', () => {
  it('版本行渲染文件总数列，打开清单 Modal 拉取快照与变更状态', async () => {
    store.versions = [makeVersion({files: [
      makeSnap(5, '第一章.docx'), makeSnap(6, '第二章.docx'), makeSnap(7, '附则.docx'),
    ]})];
    // 清单 Modal 打开时取服务端最新快照（3 份，含变更状态）
    http.get.mockResolvedValueOnce({
      version_id: 1, version_no: 1, change_note: '初版发布', previous_version_no: null,
      items: [
        makeSnap(5, '第一章.docx', {change_type: 'added'}),
        makeSnap(6, '第二章.docx', {change_type: 'modified', sort_order: 1}),
        makeSnap(7, '附则.docx', {change_type: 'unchanged', sort_order: 2}),
      ],
      removed_items: [],
    });
    container = renderTab();
    expect(container.textContent).toContain('3 份');
    const viewLink = findButton(container, '查看文件清单');
    expect(viewLink).not.toBeUndefined();
    act(() => {
      viewLink.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/versions/1/files/');
    const modalText = document.body.textContent;
    expect(modalText).toContain('第一章.docx');
    expect(modalText).toContain('第二章.docx');
    expect(modalText).toContain('附则.docx');
    expect(modalText).toContain('新增');
    expect(modalText).toContain('修改');
    expect(modalText).toContain('沿用上一版本');
    // 哈希前 8 位
    expect(modalText).toContain('abcdef12');
    expect(modalText).not.toContain('abcdef1234567890');
  });

  it('本版本移除的文件显式展示，不静默隐藏', async () => {
    store.versions = [makeVersion({files: [makeSnap(6, '第二章.docx')]})];
    http.get.mockResolvedValueOnce({
      version_id: 1, version_no: 2, change_note: '移除甲', previous_version_no: 1,
      items: [makeSnap(6, '第二章.docx', {change_type: 'unchanged'})],
      removed_items: [{
        file_id: 105, name: '第一章.docx', sort_order: 0, file_size: 1024,
        file_hash: '1234abcd5678', change_type: 'removed',
        previous_version_id: 1, previous_snapshot_id: 5,
        latest_changed_version_no: 1,
      }],
    });
    container = renderTab();
    act(() => {
      findButton(container, '查看文件清单').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    const modalText = document.body.textContent;
    expect(modalText).toContain('本版本移除');
    expect(modalText).toContain('第一章.docx');
    expect(modalText).toContain('本版本移除了 1 份文件');
  });
});

describe('版本表行内与失败重试', () => {
  it('多文件版本行内下载打开清单 Modal，不调旧接口', async () => {
    store.versions = [makeVersion({files: [makeSnap(5, '第一章.docx'), makeSnap(6, '第二章.docx')]})];
    container = renderTab();
    const downloadBtn = findButton(container, '下载');
    act(() => {
      downloadBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    expect(utils.downloadFile).not.toHaveBeenCalled();
    const calledUrls = http.get.mock.calls.map(args => args[0]);
    expect(calledUrls.some(u => u.includes('/versions/1/files/'))).toBe(true);
    expect(calledUrls.some(u => u.endsWith('/versions/1/download/'))).toBe(false);
    // 清单 Modal 已打开并展示快照
    expect(document.body.textContent).toContain('第二章.docx');
  });

  it('单文件版本行内下载保持旧接口直下', async () => {
    store.versions = [makeVersion()];
    container = renderTab();
    const downloadBtn = findButton(container, '下载');
    act(() => {
      downloadBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    expect(utils.downloadFile).toHaveBeenCalledWith(
      '/api/institution/manuals/7/versions/1/download/', '第一章.docx');
    expect(http.get).not.toHaveBeenCalled();
  });

  it('清单 Modal 内逐份下载走 sfid 级接口', async () => {
    store.versions = [makeVersion({files: [makeSnap(5, '第一章.docx'), makeSnap(6, '第二章.docx')]})];
    container = renderTab();
    act(() => {
      findButton(container, '查看文件清单').dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    // Modal 渲染在 body portal 内，取其中的下载按钮
    const modalDownload = Array.from(document.querySelectorAll('.ant-modal button'))
      .find(b => b.textContent.includes('下载'));
    expect(modalDownload).not.toBeUndefined();
    act(() => {
      modalDownload.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    expect(utils.downloadFile).toHaveBeenCalledWith(
      '/api/institution/manuals/7/versions/1/files/5/download/', '第一章.docx');
  });

  it('版本清单加载失败显示错误与重试，不以空列表冒充成功', async () => {
    store.versions = [];
    store.versionsError = '版本清单加载失败，请重试';
    container = renderTab();
    expect(container.textContent).toContain('版本清单加载失败');
    const retry = findButton(container, '重试');
    expect(retry).not.toBeUndefined();
    act(() => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    expect(store.fetchVersions).toHaveBeenCalledWith(7, 1);
  });
});

describe('从历史版本回退（整套回退语义）', () => {
  it('确认文案改为整套回退，确认后 POST from-version', async () => {
    store.versions = [makeVersion()];
    container = renderTab();
    const rollbackBtn = findButton(container, '从历史版本回退');
    expect(rollbackBtn).not.toBeUndefined();
    act(() => {
      rollbackBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    // Modal.confirm 异步渲染，先冲刷宏任务再断言
    await flushAsync();
    const confirmText = document.querySelector('.ant-modal-confirm').textContent;
    expect(confirmText).toContain('整套回退');
    expect(confirmText).toContain('完整文件清单');
    expect(confirmText).toContain('会被替换');
    expect(confirmText).toContain('失效');
    http.post.mockResolvedValue({restored_files: 3, from_version_no: 1});
    const okButton = document.querySelector('.ant-modal-confirm .ant-btn-primary');
    await act(async () => {
      okButton.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/draft/from-version/', {version_id: 1});
    // 生命周期刷新统一入口
    expect(store.refreshAfterLifecycle).toHaveBeenCalledWith(7);
  });

  it('非所有者/管理员的编制授权账号不渲染整套回退（2026-10-31 业务门收窄）', () => {
    const savedManual = store.manual;
    store.versions = [makeVersion()];
    store.manual = {...savedManual, is_owner: false, is_admin: false};
    container = renderTab();
    expect(findButton(container, '从历史版本回退')).toBeUndefined();
    // 发布授权仍可见（长期保留是发布域操作）
    expect(container.textContent).not.toContain('从历史版本回退');
    store.manual = savedManual;
  });
});

describe('版本保留策略状态与长期保留标记', () => {
  it('整版文件已清理的版本：状态列展示清理标记，无预览/下载/回退按钮', async () => {
    store.versions = [makeVersion({
      files_cleaned_at: '2026-03-01T08:00:00',
      files_clean_status: 'cleaned',
    })];
    container = renderTab();
    expect(container.textContent).toContain('文件已按保留策略清理');
    expect(findButton(container, '预览')).toBeUndefined();
    expect(findButton(container, '下载')).toBeUndefined();
    expect(findButton(container, '从历史版本回退')).toBeUndefined();
  });

  it('部分清理的版本：标记不可完整回退，不渲染回退按钮', async () => {
    store.versions = [makeVersion({
      files_cleaned_at: '2026-03-01T08:00:00',
      files_clean_status: 'partial',
      files_clean_error: '「第二章.docx」物理文件删除失败',
    })];
    container = renderTab();
    expect(container.textContent).toContain('部分文件已清理');
    expect(findButton(container, '从历史版本回退')).toBeUndefined();
  });

  it('长期保留版本展示标记与"取消长期保留"操作，点击后 POST protect 并刷新', async () => {
    store.versions = [makeVersion({long_term_protected: true})];
    container = renderTab();
    expect(container.textContent).toContain('长期保留');
    const btn = findButton(container, '取消长期保留');
    expect(btn).not.toBeUndefined();
    http.post.mockResolvedValue({});
    act(() => {
      btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/versions/1/protect/', {long_term_protected: false});
    expect(store.fetchVersions).toHaveBeenCalledWith(7, 1);
  });

  it('未标记的历史版本提供"设为长期保留"；当前生效版本不提供（永久受保护）', async () => {
    store.versions = [
      makeVersion({id: 2, version_no: 2, is_current: true, is_effective: true}),
      makeVersion({id: 1, version_no: 1, is_current: false, is_effective: false}),
    ];
    container = renderTab();
    const protectButtons = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent.replace(/\s+/g, '') === '设为长期保留');
    // 仅历史/废止版本可标记；生效中的版本不出现该操作
    expect(protectButtons.length).toBe(1);
  });

  it('清单 Modal 中已清理快照不渲染预览/下载，展示已清理标记', async () => {
    store.versions = [makeVersion({files: [makeSnap(5, '第一章.docx'),
      makeSnap(6, '第二章.docx')]})];
    http.get.mockResolvedValue({version_id: 1, version_no: 1,
      previous_version_no: null,
      items: [
        Object.assign(makeSnap(5, '第一章.docx'), {change_type: 'modified', is_cleaned: true}),
        Object.assign(makeSnap(6, '第二章.docx', {sort_order: 1}),
          {change_type: 'added', is_cleaned: false}),
      ],
      removed_items: []});
    container = renderTab();
    const modalBtn = findButton(container, '查看文件清单');
    act(() => {
      modalBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flushAsync();
    const modal = document.querySelector('.ant-modal');
    expect(modal.textContent).toContain('已清理');
    // 已清理快照无预览/下载按钮；可用快照保留
    const previews = Array.from(modal.querySelectorAll('button'))
      .filter(b => b.textContent === '预览');
    expect(previews.length).toBe(1);
  });
});

describe('无 can_view_published 口径权限的版本页签', () => {
  it('展示无权说明而非空版本表冒充，且不发版本请求', () => {
    // 2026-10-31 二轮权限模型改造：仅持编制授权且非所有者/平台超管的账号
    // 不自动可见发布版（「编制授权者可查看发布版」开关已废除；所有者
    // 自动可见发布版）；版本历史对齐后端 VersionListView 的
    // can_view_published 门禁
    const original = store.manual;
    store.manual = Object.assign({}, original,
      {my_roles: ['edit'], is_owner: false, is_admin: false});
    try {
      const container = renderTab();
      expect(container.textContent)
        .toContain('当前账号无可查看发布版本的授权');
      expect(container.querySelectorAll('.ant-table').length).toBe(0);
      expect(store.fetchVersions).not.toHaveBeenCalled();
    } finally {
      store.manual = original;
    }
  });
});

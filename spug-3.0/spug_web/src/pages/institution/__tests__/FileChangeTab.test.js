/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件变更记录页签行为测试（jsdom + ReactDOM；2026-10-29 交互优化）：
 * - 挂载拉取 originals-overview 全集（含已移除文件）并自动选中首个文件，
 *   触发 发布参与记录 + 按文件操作记录。
 * - 已从待发布集合移除的文件在下拉中明确标注且可选（变更记录必须能
 *   找到它们）；文件清单行跳入时经 store.fileChangeTarget 预选。
 * - 发布记录渲染 版本号/该文件变化(新增/修改/沿用)/变更说明/发布人/时间；
 *   已清理快照行只显示元数据与"已清理"，不渲染预览/下载。
 * - 聚合清单/发布记录加载失败置错误态可重试；无发布可见权时仅展示
 *   操作记录。
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

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', status: 'active',
      my_roles: ['view']};
    @observable originalsOverview = [];
    @observable isFetchingOriginalsOverview = false;
    @observable originalsOverviewError = '';
    @observable fileChangeTarget = null;
    @observable fileVersion = null;
    @observable isFetchingFileVersion = false;
    @observable fileVersionError = '';
    @observable fileLogs = [];
    @observable fileLogsTotal = 0;
    @observable fileLogsPage = 1;
    @observable isFetchingFileLogs = false;
    fetchOriginalsOverview = jest.fn(function () {
      this.originalsOverview = [
        {file_id: 11, name: '管理规定.docx', sort_order: 0, is_removed: false},
        {file_id: 12, name: '应急手册.docx', sort_order: 1, is_removed: false},
        {file_id: 13, name: '已移除文件.docx', sort_order: 2, is_removed: true},
      ];
      return Promise.resolve();
    });
    fetchFileVersionHistory = jest.fn(function () { return Promise.resolve(); });
    fetchFileLogs = jest.fn(function () { return Promise.resolve(); });
    clearFileRecords = jest.fn(function () {});
  }
  return new DetailStore();
});

import FileChangeTab from '../detail/FileChangeTab';
import store from '../detail/store';

function renderTab() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(React.createElement(FileChangeTab), container);
  });
  return container;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  store.originalsOverview = [];
  store.originalsOverviewError = '';
  store.fileChangeTarget = null;
  // clearAllMocks 不清除 mockImplementation：逐用例显式恢复默认成功实现，
  // 防止失败用例的持久实现泄漏到后续用例
  store.fetchOriginalsOverview.mockImplementation(function () {
    this.originalsOverview = [
      {file_id: 11, name: '管理规定.docx', sort_order: 0, is_removed: false},
      {file_id: 12, name: '应急手册.docx', sort_order: 1, is_removed: false},
      {file_id: 13, name: '已移除文件.docx', sort_order: 2, is_removed: true},
    ];
    return Promise.resolve();
  });
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

describe('文件变更记录页签（按文件回看，含已移除文件）', () => {
  it('挂载拉取 originals-overview 全集并自动选中首个文件', async () => {
    container = renderTab();
    await flush();
    expect(store.fetchOriginalsOverview).toHaveBeenCalledWith(7);
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 11);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 11, 1);
  });

  it('已移除文件在下拉中可选（变更记录能找到已移除文件）', async () => {
    container = renderTab();
    await flush();
    const select = container.querySelector('.ant-select-selector');
    act(() => {
      select.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await flush();
    const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
      .find(o => o.textContent.includes('已移除文件.docx'));
    expect(option).not.toBeUndefined();
    expect(option.textContent).toContain('已移除');
    act(() => {
      option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 13);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 13, 1);
  });

  it('文件清单行跳入：store.fileChangeTarget 预选对应文件并清空', async () => {
    store.fileChangeTarget = 13;
    container = renderTab();
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 13);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 13, 1);
    expect(store.fileChangeTarget).toBeNull();
  });

  it('发布记录渲染版本参与行（变化状态/变更说明/发布人/哈希）', async () => {
    container = renderTab();
    await flush();
    store.fileVersion = {file_id: 11, file_name: '管理规定.docx', items: [
      {version_id: 31, version_no: 3, change_type: 'modified',
        change_note: '第三章更新', file_size: 2048, file_hash: 'abcd1234ef567890',
        published_by_name: '张三', published_at: '2026-03-01T09:30:00'},
      {version_id: 30, version_no: 2, change_type: 'unchanged',
        change_note: '仅更新其他文件', file_size: 2048, file_hash: 'abcd1234ef567890',
        published_by_name: '张三', published_at: '2026-02-01T09:30:00'},
      {version_id: 29, version_no: 1, change_type: 'added',
        change_note: '初版发布', file_size: 1024, file_hash: '9999aaaa12345678',
        published_by_name: '李四', published_at: '2026-01-01T09:30:00'},
    ]};
    await flush();
    const text = container.textContent;
    expect(text).toContain('发布记录');
    expect(text).toContain('v3');
    expect(text).toContain('修改');
    expect(text).toContain('沿用上一版本');
    expect(text).toContain('新增');
    expect(text).toContain('第三章更新');
    expect(text).toContain('abcd1234');
    expect(text).toContain('张三');
    expect(text).toContain('2026-03-01 09:30:00');
  });

  it('已清理快照行只显示元数据与"已清理"，不渲染预览/下载', async () => {
    container = renderTab();
    await flush();
    store.fileVersion = {file_id: 11, file_name: '管理规定.docx', items: [
      {version_id: 31, version_no: 3, change_type: 'modified',
        change_note: '更新', file_size: 2048, file_hash: 'abcd1234ef567890',
        published_by_name: '张三', published_at: '2026-03-01T09:30:00',
        is_cleaned: true},
      {version_id: 29, version_no: 1, change_type: 'added',
        change_note: '初版发布', file_size: 1024, file_hash: '9999aaaa12345678',
        published_by_name: '李四', published_at: '2026-01-01T09:30:00',
        is_cleaned: false},
    ]};
    await flush();
    const text = container.textContent;
    expect(text).toContain('已清理');
    const previewButtons = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent.replace(/\s+/g, '') === '预览');
    expect(previewButtons.length).toBe(1); // 仅未清理行
  });

  it('操作记录展示该文件过滤后的时间线', async () => {
    container = renderTab();
    await flush();
    store.fileLogs = [
      {id: 1, action: 'save_draft', user_name: '张三',
        created_at: '2026-03-01T10:00:00', detail: '{"file_revision": 6}'},
      {id: 2, action: 'file_rename', user_name: '李四',
        created_at: '2026-02-01T10:00:00', detail: '{"before": "旧名", "after": "新名"}'},
    ];
    store.fileLogsTotal = 2;
    await flush();
    const text = container.textContent;
    expect(text).toContain('操作记录');
    expect(text).toContain('保存草稿');
    expect(text).toContain('文件改名');
    expect(text).toContain('张三');
    expect(text).toContain('修订 r6');
  });
});

describe('文件变更记录页签（失败重试与权限收窄）', () => {
  it('发布记录加载失败显示错误与重试，重试携带当前文件', async () => {
    container = renderTab();
    await flush();
    store.fileVersionError = '发布记录加载失败，请重试';
    await flush();
    expect(container.textContent).toContain('发布记录加载失败');
    const retry = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '').includes('重试'));
    expect(retry).not.toBeUndefined();
    act(() => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 11);
  });

  it('聚合清单加载失败：错误+重试，成功后自动选中首个文件', async () => {
    store.fetchOriginalsOverview.mockImplementationOnce(function () {
      this.originalsOverviewError = '初始来源加载失败，请重试';
      return Promise.reject(new Error('e'));
    });
    container = renderTab();
    await flush();
    expect(container.textContent).toContain('初始来源加载失败');
    const retry = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '').includes('重试'));
    expect(retry).not.toBeUndefined();
    act(() => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchOriginalsOverview).toHaveBeenCalledTimes(2);
    // 重试成功后恢复选择链路（首个文件）
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 11);
  });

  it('切换文件下拉后按新文件重新拉取', async () => {
    container = renderTab();
    await flush();
    const select = container.querySelector('.ant-select-selector');
    act(() => {
      select.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    });
    await flush();
    const option = Array.from(document.querySelectorAll('.ant-select-item-option'))
      .find(o => o.textContent.includes('应急手册.docx'));
    expect(option).not.toBeUndefined();
    act(() => {
      option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 12);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 12, 1);
  });

  it('无发布可见权：不请求发布记录，仅展示操作记录并说明', async () => {
    // FileChangeTab 经 Babel CommonJS 互操作在调用点读取 utils 导出，
    // 覆写模块导出即可控制入口判定（真实 utils，仅替换该函数）
    const utils = require('../utils');
    const original = utils.canViewPublished;
    utils.canViewPublished = () => false;
    try {
      container = renderTab();
      await flush();
      expect(container.textContent).toContain('不可查看该制度的发布记录');
      // 无权限时不该出现发布记录区域，也绝不发起 version-history 请求
      expect(store.fetchFileVersionHistory).not.toHaveBeenCalled();
      expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 11, 1);
      expect(container.textContent).toContain('操作记录');
    } finally {
      utils.canViewPublished = original;
    }
  });
});

describe('文件变更记录页签（页签保持挂载时的再次跳转与目标解析）', () => {
  it('页签已挂载时再次「变更记录」跳转：预选新文件并重新拉取', async () => {
    container = renderTab();
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 11);
    // 模拟文件清单行再次点击另一文件：页签保持挂载，不会重新执行
    // componentDidMount，目标必须仍被消费
    jest.clearAllMocks();
    store.fileChangeTarget = 12;
    await flush();
    expect(store.fileChangeTarget).toBeNull();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 12);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 12, 1);
    const shown = container.querySelector('.ant-select-selection-item');
    expect(shown && shown.textContent).toContain('应急手册.docx');
  });

  it('连续 A→B→A 跳转：每次都选中对应文件并重新拉取', async () => {
    container = renderTab();
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenLastCalledWith(7, 11);
    jest.clearAllMocks();
    store.fileChangeTarget = 12;
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenLastCalledWith(7, 12);
    jest.clearAllMocks();
    store.fileChangeTarget = 11;
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenLastCalledWith(7, 11);
    expect(store.fetchFileLogs).toHaveBeenLastCalledWith(7, 11, 1);
    const shown = container.querySelector('.ant-select-selection-item');
    expect(shown && shown.textContent).toContain('管理规定.docx');
  });

  it('再次跳转当前已选文件：选中保持稳定并刷新记录', async () => {
    container = renderTab();
    await flush();
    jest.clearAllMocks();
    store.fileChangeTarget = 11;
    await flush();
    expect(store.fileChangeTarget).toBeNull();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 11);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 11, 1);
    const shown = container.querySelector('.ant-select-selection-item');
    expect(shown && shown.textContent).toContain('管理规定.docx');
  });

  it('文件全集尚在加载时保留跳转目标，加载成功后再选中', async () => {
    let resolveFetch;
    store.fetchOriginalsOverview.mockImplementation(function () {
      this.isFetchingOriginalsOverview = true;
      return new Promise(resolve => {resolveFetch = resolve;});
    });
    container = renderTab();
    await flush();
    expect(store.fetchFileVersionHistory).not.toHaveBeenCalled();
    store.fileChangeTarget = 12;
    await flush();
    // 全集加载中：目标保留未消费，也不发起按文件的请求
    expect(store.fileChangeTarget).toBe(12);
    expect(store.fetchFileVersionHistory).not.toHaveBeenCalled();
    await act(async () => {
      store.isFetchingOriginalsOverview = false;
      store.originalsOverview = [
        {file_id: 11, name: '管理规定.docx', sort_order: 0, is_removed: false},
        {file_id: 12, name: '应急手册.docx', sort_order: 1, is_removed: false},
      ];
      resolveFetch();
      await Promise.resolve();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 12);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 12, 1);
    expect(store.fileChangeTarget).toBeNull();
    const shown = container.querySelector('.ant-select-selection-item');
    expect(shown && shown.textContent).toContain('应急手册.docx');
  });

  it('跳转目标不在全集中：回退首个文件，不把旧文件记录冒充目标', async () => {
    container = renderTab();
    await flush();
    jest.clearAllMocks();
    store.fileChangeTarget = 99;
    await flush();
    expect(store.fileChangeTarget).toBeNull();
    expect(store.fetchFileVersionHistory).not.toHaveBeenCalledWith(7, 99);
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 11);
    const shown = container.querySelector('.ant-select-selection-item');
    expect(shown && shown.textContent).toContain('管理规定.docx');
  });

  it('操作记录翻页携带当前文件 file_id（originals-overview 行键是 file_id）', async () => {
    container = renderTab();
    await flush();
    store.fileLogsTotal = 30;
    await flush();
    const page2 = container.querySelector('.ant-pagination-item-2');
    expect(page2).not.toBeNull();
    act(() => {
      page2.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 11, 2);
  });
});

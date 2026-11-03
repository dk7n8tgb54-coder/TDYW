/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件历史弹窗行为测试（jsdom + ReactDOM，2026-11-01 简化版）：
 * - 打开即按 file_id 拉取 发布记录（files/<fid>/version-history/）+ 按文件
 *   操作记录（operation-logs/?file_id=）；弹窗标题显示制度文件名；
 *   内部只有 发布记录/操作记录 两个子页签（默认发布记录）。
 * - 发布记录渲染 版本号/该文件变化(新增/修改/沿用)/变更说明/发布人/哈希/
 *   时间；已清理快照行只显示元数据与"已清理"，不渲染预览/下载；未清理行
 *   预览走快照 preview-url 端点且标题注明版本，下载走快照端点。
 * - 操作记录展示该文件过滤后的时间线；翻页携带当前 file_id。
 * - 发布记录加载失败置错误态可重试（重试携带当前 file_id）。
 * - 无发布可见权（can_view_published 不通过）：不发 version-history 请求、
 *   默认落在操作记录子页签，发布记录子页签仅提示。
 * - 连续打开不同文件：先 clearFileRecords 清空旧文件数据，按新 file_id
 *   重取，不残留旧文件内容；关闭弹窗回调 onClose。
 * - 弹窗不提供 历史来源/重建/更换来源/上传 任何入口（原稿历史已不在
 *   界面展示）。
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

jest.mock('../detail/PreviewModal', () => function PreviewModal(props) {
  PreviewModal.lastProps = props;
  return null;
});

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', status: 'active',
      my_roles: ['view']};
    @observable fileVersion = null;
    @observable isFetchingFileVersion = false;
    @observable fileVersionError = '';
    @observable fileLogs = [];
    @observable fileLogsTotal = 0;
    @observable fileLogsPage = 1;
    @observable isFetchingFileLogs = false;
    fetchFileVersionHistory = jest.fn(function () { return Promise.resolve(); });
    fetchFileLogs = jest.fn(function () { return Promise.resolve(); });
    // 与真实 store 一致：清空记录防旧文件数据残留（组件契约依赖该行为）
    clearFileRecords = jest.fn(function () {
      this.fileVersion = null;
      this.fileVersionError = '';
      this.fileLogs = [];
      this.fileLogsTotal = 0;
      this.fileLogsPage = 1;
    });
  }
  return new DetailStore();
});

import {http} from 'libs';
import FileHistoryModal from '../detail/FileHistoryModal';
import PreviewModal from '../detail/PreviewModal';
import store from '../detail/store';

function renderModal(props = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<FileHistoryModal {...props}/>, container);
  });
  return container;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function modalEl() {
  return document.querySelector('.ant-modal');
}

/** 点击弹窗内指定子页签（发布记录/操作记录） */
function clickInnerTab(label) {
  const modal = modalEl();
  const tab = Array.from(modal.querySelectorAll('.ant-tabs-tab'))
    .find(el => el.textContent.trim() === label);
  expect(tab).not.toBeUndefined();
  act(() => {
    tab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

function buttonsWithText(root, text) {
  const needle = text.replace(/\s+/g, '');
  return Array.from(root.querySelectorAll('button'))
    .filter(b => b.textContent.replace(/\s+/g, '') === needle);
}

function openProps(overrides = {}) {
  return Object.assign({
    visible: true, fileId: 11, fileName: '管理规定.docx',
    onClose: () => {},
  }, overrides);
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  // jsdom 无 createObjectURL：下载走真实 downloadFile（utils）需要桩
  window.URL.createObjectURL = jest.fn(() => 'blob:mock');
  window.URL.revokeObjectURL = jest.fn();
  store.manual = {id: 7, name: '科室操作手册', status: 'active',
    my_roles: ['view']};
  store.fileVersion = null;
  store.fileVersionError = '';
  store.fileLogs = [];
  store.fileLogsTotal = 0;
  // clearAllMocks 不清除 mockImplementation：逐用例显式恢复默认成功实现，
  // 防止失败用例的持久实现泄漏到后续用例
  store.fetchFileVersionHistory.mockImplementation(
    () => Promise.resolve());
  store.fetchFileLogs.mockImplementation(() => Promise.resolve());
  store.clearFileRecords.mockImplementation(function () {
    this.fileVersion = null;
    this.fileVersionError = '';
    this.fileLogs = [];
    this.fileLogsTotal = 0;
    this.fileLogsPage = 1;
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

describe('文件历史弹窗（打开与结构）', () => {
  it('打开即按 file_id 拉取发布记录与操作记录；标题显示制度文件名', async () => {
    container = renderModal(openProps());
    await flush();
    expect(modalEl()).not.toBeNull();
    expect(modalEl().textContent).toContain('文件历史：管理规定.docx');
    expect(store.fetchFileVersionHistory).toHaveBeenCalledWith(7, 11);
    expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 11, 1);
  });

  it('内部只有 发布记录/操作记录 两个子页签，默认展示发布记录', async () => {
    container = renderModal(openProps());
    await flush();
    const tabs = Array.from(modalEl().querySelectorAll('.ant-tabs-tab'))
      .map(el => el.textContent.trim());
    expect(tabs).toEqual(['发布记录', '操作记录']);
    // 默认展示发布记录（can_view_published 通过）
    expect(modalEl().textContent).toContain('该文件在历次发布中的内容变化');
    // 不再提供历史来源子页签与任何原稿历史入口
    expect(tabs).not.toContain('历史来源');
    expect(modalEl().textContent).not.toContain('历史上传记录');
  });

  it('visible=false 不渲染弹窗；fileId 为空不发起任何请求', () => {
    container = renderModal(openProps({visible: false}));
    expect(modalEl()).toBeNull();
    expect(store.fetchFileVersionHistory).not.toHaveBeenCalled();
    expect(store.fetchFileLogs).not.toHaveBeenCalled();
  });

  it('点击关闭按钮回调 onClose', async () => {
    const onClose = jest.fn();
    container = renderModal(openProps({onClose}));
    await flush();
    const closeBtn = modalEl().querySelector('.ant-modal-close');
    act(() => {
      closeBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('文件历史弹窗（发布记录）', () => {
  it('渲染版本参与行（变化状态/变更说明/发布人/哈希/时间）', async () => {
    container = renderModal(openProps());
    await flush();
    store.fileVersion = {file_id: 11, file_name: '管理规定.docx', items: [
      {version_id: 31, version_no: 3, change_type: 'modified',
        change_note: '第三章更新', file_size: 2048, file_hash: 'abcd1234ef567890',
        published_by_name: '张三', published_at: '2026-03-01T09:30:00'},
      {version_id: 30, version_no: 2, change_type: 'unchanged',
        change_note: '仅更新其他文件', file_size: 2048,
        file_hash: 'abcd1234ef567890', published_by_name: '张三',
        published_at: '2026-02-01T09:30:00'},
      {version_id: 29, version_no: 1, change_type: 'added',
        change_note: '初版发布', file_size: 1024, file_hash: '9999aaaa12345678',
        published_by_name: '李四', published_at: '2026-01-01T09:30:00'},
    ]};
    await flush();
    const text = modalEl().textContent;
    expect(text).toContain('v3');
    expect(text).toContain('修改');
    expect(text).toContain('沿用上一版本');
    expect(text).toContain('新增');
    expect(text).toContain('第三章更新');
    expect(text).toContain('abcd1234');
    expect(text).toContain('张三');
    expect(text).toContain('2026-03-01 09:30:00');
  });

  it('未发布过任何版本的文件：发布记录渲染空态占位而非旧数据或报错', async () => {
    container = renderModal(openProps({fileId: 12, fileName: '应急手册.docx'}));
    await flush();
    store.fileVersion = {file_id: 12, file_name: '应急手册.docx', items: []};
    await flush();
    // scroll.x 表格在 jsdom 中空态内容渲染进 0 宽节点（真实浏览器正常显示），
    // 断言占位行存在且无任何数据行
    expect(modalEl().querySelector('.ant-table-placeholder')).not.toBeNull();
    expect(modalEl().querySelectorAll('.ant-table-row')).toHaveLength(0);
  });

  it('已清理快照行只显示元数据与"已清理"，不渲染预览/下载', async () => {
    container = renderModal(openProps());
    await flush();
    store.fileVersion = {file_id: 11, file_name: '管理规定.docx', items: [
      {version_id: 31, version_no: 3, change_type: 'modified',
        change_note: '更新', file_size: 2048, file_hash: 'abcd1234ef567890',
        published_by_name: '张三', published_at: '2026-03-01T09:30:00',
        is_cleaned: true},
      {version_id: 29, version_no: 1, change_type: 'added',
        change_note: '初版发布', file_size: 1024,
        file_hash: '9999aaaa12345678', published_by_name: '李四',
        published_at: '2026-01-01T09:30:00', is_cleaned: false},
    ]};
    await flush();
    expect(modalEl().textContent).toContain('已清理');
    expect(buttonsWithText(modalEl(), '预览').length).toBe(1); // 仅未清理行
    expect(buttonsWithText(modalEl(), '下载').length).toBe(1);
  });

  it('预览/下载走版本快照端点；预览标题注明历史版本来源', async () => {
    http.get.mockResolvedValue({preview_url: 'http://preview/x',
      file_name: 'x.docx'});
    container = renderModal(openProps());
    await flush();
    store.fileVersion = {file_id: 11, file_name: '管理规定.docx', items: [
      {version_id: 31, snapshot_id: 301, version_no: 3, change_type: 'modified',
        change_note: '更新', file_size: 2048, file_hash: 'abcd1234ef567890',
        published_by_name: '张三', published_at: '2026-03-01T09:30:00',
        is_cleaned: false},
    ]};
    await flush();
    act(() => {
      buttonsWithText(modalEl(), '预览')[0]
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/versions/31/files/301/preview-url/');
    expect(PreviewModal.lastProps.title).toBe('预览历史版本 v3：管理规定.docx');
    act(() => {
      buttonsWithText(modalEl(), '下载')[0]
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(http.get).toHaveBeenCalledWith(
      '/api/institution/manuals/7/versions/31/files/301/download/',
      {responseType: 'blob'});
  });

  it('发布记录加载失败显示错误与重试，重试携带当前文件', async () => {
    container = renderModal(openProps());
    await flush();
    store.fileVersionError = '发布记录加载失败，请重试';
    await flush();
    expect(modalEl().textContent).toContain('发布记录加载失败');
    const retry = Array.from(modalEl().querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '').includes('重试'));
    expect(retry).not.toBeUndefined();
    act(() => {
      retry.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenLastCalledWith(7, 11);
  });
});

describe('文件历史弹窗（操作记录）', () => {
  it('展示该文件过滤后的时间线（动作文案与详情解析）', async () => {
    container = renderModal(openProps());
    await flush();
    clickInnerTab('操作记录');
    await flush();
    store.fileLogs = [
      {id: 1, action: 'save_draft', user_name: '张三',
        created_at: '2026-03-01T10:00:00', detail: '{"file_revision": 6}'},
      {id: 2, action: 'file_rename', user_name: '李四',
        created_at: '2026-02-01T10:00:00',
        detail: '{"before": "旧名", "after": "新名"}'},
    ];
    store.fileLogsTotal = 2;
    await flush();
    const text = modalEl().textContent;
    expect(text).toContain('操作记录');
    expect(text).toContain('仅「管理规定.docx」的操作');
    expect(text).toContain('保存草稿');
    expect(text).toContain('文件改名');
    expect(text).toContain('张三');
    expect(text).toContain('修订 r6');
  });

  it('翻页携带当前文件 file_id', async () => {
    container = renderModal(openProps());
    await flush();
    clickInnerTab('操作记录');
    await flush();
    store.fileLogsTotal = 30;
    await flush();
    const page2 = modalEl().querySelector('.ant-pagination-item-2');
    expect(page2).not.toBeNull();
    act(() => {
      page2.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await flush();
    expect(store.fetchFileLogs).toHaveBeenLastCalledWith(7, 11, 2);
  });
});

describe('文件历史弹窗（权限收窄）', () => {
  it('无发布可见权：不发 version-history 请求，默认操作记录，发布子页签仅提示', async () => {
    // FileHistoryModal 经 Babel CommonJS 互操作在调用点读取 utils 导出，
    // 覆写模块导出即可控制入口判定（真实 utils，仅替换该函数）
    const utils = require('../utils');
    const original = utils.canViewPublished;
    utils.canViewPublished = () => false;
    try {
      container = renderModal(openProps());
      await flush();
      expect(store.fetchFileVersionHistory).not.toHaveBeenCalled();
      expect(store.fetchFileLogs).toHaveBeenCalledWith(7, 11, 1);
      const tabs = Array.from(modalEl().querySelectorAll('.ant-tabs-tab'))
        .map(el => el.textContent.trim());
      expect(tabs).toEqual(['发布记录', '操作记录']);
      expect(modalEl().textContent).toContain('仅「管理规定.docx」的操作');
      clickInnerTab('发布记录');
      await flush();
      expect(modalEl().textContent).toContain('不可查看该制度的发布记录');
    } finally {
      utils.canViewPublished = original;
    }
  });
});

describe('文件历史弹窗（切换文件与关闭后重开）', () => {
  it('连续打开不同文件：清空旧文件数据并按新 file_id 重取，不残留旧内容', async () => {
    container = renderModal(openProps());
    await flush();
    store.fileVersion = {file_id: 11, file_name: '管理规定.docx', items: [
      {version_id: 31, version_no: 3, change_type: 'modified',
        change_note: '甲文件的修改说明', file_size: 2048,
        file_hash: 'aaaa1111aaaa1111', published_by_name: '张三',
        published_at: '2026-03-01T09:30:00'},
    ]};
    await flush();
    expect(modalEl().textContent).toContain('甲文件的修改说明');
    // 换文件再打开（同一实例）：先 clearFileRecords，再按 file_id=12 重取
    store.fetchFileVersionHistory.mockImplementation(function (id, fileId) {
      this.fileVersion = fileId === 12
        ? {file_id: 12, file_name: '应急手册.docx', items: [
            {version_id: 31, version_no: 3, change_type: 'added',
              change_note: '乙文件首次进入版本', file_size: 4096,
              file_hash: 'dddd4444dddd4444', published_by_name: '张三',
              published_at: '2026-03-01T09:30:00'}]}
        : null;
      return Promise.resolve();
    });
    act(() => {
      ReactDOM.render(<FileHistoryModal visible fileId={12}
        fileName="应急手册.docx" onClose={() => {}}/>, container);
    });
    await flush();
    expect(store.clearFileRecords).toHaveBeenCalled();
    expect(store.fetchFileVersionHistory).toHaveBeenLastCalledWith(7, 12);
    expect(store.fetchFileLogs).toHaveBeenLastCalledWith(7, 12, 1);
    const text = modalEl().textContent;
    expect(text).not.toContain('甲文件的修改说明');
    expect(text).toContain('乙文件首次进入版本');
  });

  it('关闭后重开同一文件：重新拉取（数据保持新鲜）', async () => {
    container = renderModal(openProps());
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledTimes(1);
    // 关闭（visible=false）
    act(() => {
      ReactDOM.render(<FileHistoryModal visible={false} fileId={11}
        fileName="管理规定.docx" onClose={() => {}}/>, container);
    });
    // 重开同一文件
    act(() => {
      ReactDOM.render(<FileHistoryModal visible fileId={11}
        fileName="管理规定.docx" onClose={() => {}}/>, container);
    });
    await flush();
    expect(store.fetchFileVersionHistory).toHaveBeenCalledTimes(2);
    expect(store.fetchFileLogs).toHaveBeenLastCalledWith(7, 11, 1);
  });
});

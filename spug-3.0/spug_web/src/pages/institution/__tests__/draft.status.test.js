/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿状态摘要行为测试（jsdom + ReactDOM，2026-10-29）：
 * - DraftStatusSummary（详情页头部整套摘要）：一致 / 待发布变化（修改/
 *   新增/移除/改名/排序）/ 无生效版本等待首次发布 / 暂不能确认 /
 *   缺草稿 / 加载失败重试；仅查看角色不渲染也不请求。
 * - 逐份"草稿 vs 生效版本"关系列与刷新时机见 FileListTab.test.js 与
 *   detail.store.test.js（refreshAfterLifecycle）。
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

jest.mock('../detail/store', () => {
  const {observable} = require('mobx');
  class DetailStore {
    @observable id = 7;
    @observable manual = {id: 7, name: '科室操作手册', status: 'active',
      my_roles: ['edit'],
      current_version: {id: 3, version_no: 2}};
    @observable isFetching = false;
    @observable error = '';
    @observable files = [];
    @observable isFetchingFiles = false;
    @observable draftStatus = null;
    @observable isFetchingDraftStatus = false;
    @observable draftStatusError = '';
    _manualOverrides = null;
    fetchDetail = jest.fn(function (id) { return Promise.resolve(); });
    fetchDraftStatus = jest.fn(function () { return Promise.resolve(); });
    reset = jest.fn(function () {});
  }
  return new DetailStore();
});

import {hasPermission} from 'libs';
import DraftStatusSummary from '../detail/DraftStatusSummary';
import store from '../detail/store';

const CONSISTENT_STATUS = {
  has_current_version: true, current_version_no: 2, items: [],
  removed_items: [],
  summary: {total_files: 2, unchanged: 2, modified: 0, added: 0,
    awaiting_first_publish: 0, no_draft: 0, unconfirmed: 0, removed: 0,
    renamed: 0, reordered: false, revising: 0, has_current_version: true,
    current_version_no: 2, has_pending_changes: false, determinable: true,
    consistent: true},
};

let container = null;

function mount(node) {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(node, container);
  });
}

function findButton(root, text) {
  // antd 两字中文按钮（非 link 型）会插空格（"重 试"），查找须归一化空白
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(text));
}

beforeEach(() => {
  jest.clearAllMocks();
  hasPermission.mockImplementation(() => true);
  store.manual = {id: 7, name: '科室操作手册', status: 'active',
    my_roles: ['edit'],
    current_version: {id: 3, version_no: 2}};
  store.draftStatus = null;
  store.draftStatusError = '';
  store.isFetchingDraftStatus = false;
  store.files = [];
  store.isFetchingFiles = false;
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

describe('DraftStatusSummary（详情头部整套摘要）', () => {
  it('一致：显示"已生效，无未发布修改"，不再并排罗列草稿版本语义', () => {
    store.draftStatus = CONSISTENT_STATUS;
    mount(<DraftStatusSummary/>);
    const text = container.textContent;
    expect(text).toContain('已生效');
    expect(text).toContain('无未发布修改');
    expect(text).not.toContain('当前草稿与生效版本一致');
  });

  it('修订进行中（暂无待发布变化）：独立呈现，不冒充一致也不冒充变化', () => {
    store.draftStatus = {summary: {
      total_files: 2, has_current_version: true, current_version_no: 2,
      unchanged: 2, modified: 0, added: 0, removed: 0, renamed: 0,
      reordered: false, revising: 1, no_draft: 0, unconfirmed: 0,
      has_pending_changes: false, determinable: true, consistent: false}};
    mount(<DraftStatusSummary/>);
    const text = container.textContent;
    expect(text).toContain('1 份文件修订进行中');
    expect(text).toContain('暂无待发布变化');
    expect(text).not.toContain('已生效');
  });

  it('待发布变化：按服务端摘要逐项罗列（修改/新增/移除/改名/排序）', () => {
    store.draftStatus = {summary: {
      total_files: 4, has_current_version: true, current_version_no: 2,
      modified: 2, added: 1, removed: 1, renamed: 1, reordered: true,
      revising: 0,
      no_draft: 0, unconfirmed: 0, has_pending_changes: true,
      determinable: true, consistent: false}};
    mount(<DraftStatusSummary/>);
    const text = container.textContent;
    expect(text).toContain('2 份文件有未发布修改');
    expect(text).toContain('1 份新增文件');
    expect(text).toContain('1 份文件被移除');
    expect(text).toContain('1 份文件已改名');
    expect(text).toContain('文件顺序已调整');
    expect(text).not.toContain('已生效');
  });

  it('待发布变化与修订进行中并存：变化优先罗列，修订计数同时可见', () => {
    store.draftStatus = {summary: {
      total_files: 4, has_current_version: true, current_version_no: 2,
      modified: 2, added: 0, removed: 0, renamed: 0, reordered: false,
      revising: 3, no_draft: 0, unconfirmed: 0,
      has_pending_changes: true, determinable: true, consistent: false}};
    mount(<DraftStatusSummary/>);
    const text = container.textContent;
    expect(text).toContain('2 份文件有未发布修改');
    expect(text).toContain('3 份文件修订进行中');
  });

  it('无生效版本：显示"等待首次发布"而非一致/变化', () => {
    store.draftStatus = {summary: {
      total_files: 2, has_current_version: false, current_version_no: null,
      awaiting_first_publish: 2, modified: 0, added: 0, removed: 0,
      renamed: 0, reordered: false, revising: 0, no_draft: 0, unconfirmed: 0,
      has_pending_changes: true, determinable: true, consistent: false}};
    mount(<DraftStatusSummary/>);
    expect(container.textContent).toContain('尚无生效版本，等待首次发布');
    expect(container.textContent).not.toContain('已生效');
  });

  it('存在暂不能确认的文件：绝不显示"已生效"', () => {
    store.draftStatus = {summary: {
      total_files: 2, has_current_version: true, current_version_no: 2,
      unchanged: 1, modified: 0, added: 0, removed: 0, renamed: 0,
      reordered: false, revising: 0, no_draft: 0, unconfirmed: 1,
      has_pending_changes: false, determinable: false, consistent: false}};
    mount(<DraftStatusSummary/>);
    const text = container.textContent;
    expect(text).toContain('1 份暂不能确认');
    expect(text).not.toContain('已生效');
  });

  it('缺草稿单独计数展示，且不显示"已生效"', () => {
    store.draftStatus = {summary: {
      total_files: 2, has_current_version: true, current_version_no: 2,
      unchanged: 1, modified: 0, added: 0, removed: 0, renamed: 0,
      reordered: false, revising: 0, no_draft: 1, unconfirmed: 0,
      has_pending_changes: false, determinable: true, consistent: false}};
    mount(<DraftStatusSummary/>);
    const text = container.textContent;
    expect(text).toContain('1 份缺草稿');
    expect(text).not.toContain('无未发布修改');
  });

  it('加载失败：报错+重试，不显示已生效/无变化；重试触发重新拉取', () => {
    store.draftStatusError = '草稿状态加载失败，请重试';
    mount(<DraftStatusSummary/>);
    expect(container.textContent).toContain('草稿状态加载失败');
    expect(container.textContent).not.toContain('已生效');
    const retry = findButton(container, '重试');
    retry.click();
    expect(store.fetchDraftStatus).toHaveBeenCalledWith(store.id);
  });

  it('仅查看角色：不渲染摘要（不泄漏草稿信息）', () => {
    store.manual = Object.assign({}, store.manual, {my_roles: ['view']});
    hasPermission.mockImplementation(
      perm => perm === 'institution.manual.view');
    store.draftStatus = CONSISTENT_STATUS;
    mount(<DraftStatusSummary/>);
    expect(container.textContent).toBe('');
  });
});

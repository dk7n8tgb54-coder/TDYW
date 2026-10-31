/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 发布新版本入口测试（2026-10-29 交互优化：发布主入口上移到详情头部
 * 整套待发布状态旁，PublishButton 组件）：
 * - 点击先请求 publish-preview 分组预检，确认窗口展示 固定文案+全部分组；
 * - 受阻文件点名、给出可执行处理入口（我的会话→工作台深链结束会话；
 *   他人会话→等待说明；缺草稿→编制角色（负责人）恢复 / 无编制角色说明），
 *   受阻时禁用确认按钮（不让用户点击必然失败的确认；服务端仍权威校验）；
 * - 确认后携带变更说明 POST publish，成功走统一生命周期刷新；
 *   失败不显示成功、不清空现有数据；
 * - 仅发布角色可渲染（编制/查看角色不渲染）；归档手册不渲染。
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
      my_roles: ['publish'], current_version: {id: 9, version_no: 3}};
    @observable publishPreview = null;
    @observable isFetchingPublishPreview = false;
    @observable draftStatus = null;
    fetchPublishPreview = jest.fn(function () { return Promise.resolve(); });
    refreshAfterLifecycle = jest.fn(function () { return Promise.resolve(); });
  }
  return new DetailStore();
});

import PublishButton from '../detail/PublishButton';
import {message} from 'antd';
import {history} from 'libs';
import {http} from 'libs';
import store from '../detail/store';

function setupPublishPreview(over = {}) {
  store.fetchPublishPreview.mockImplementation(function () {
    this.publishPreview = Object.assign({
      current_version_no: 2,
      first_publish: false, has_changes: true, renamed: 0, reordered: false,
      changed: [{file_id: 11, name: '管理规定.docx', sort_order: 0,
        draft_revision: 3, draft_size: 2048, change_type: 'modified'}],
      unchanged: [{file_id: 12, name: '应急手册.docx', sort_order: 1,
        draft_revision: 1, draft_size: 1024, change_type: 'unchanged'}],
      added: [{file_id: 13, name: 'SMS手册.docx', sort_order: 2,
        draft_revision: 1, draft_size: 4096, change_type: 'added'}],
      removed: [{file_id: 14, name: '旧附则.docx', from_version_no: 2}],
      blocked: [],
    }, over);
    return Promise.resolve();
  });
}

function renderButton() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<PublishButton/>, container);
  });
  return container;
}

function flushAsync() {
  // antd Modal.confirm 经 setTimeout(0) 异步渲染，至少两个宏任务轮次才落 DOM
  return act(async () => {
    await new Promise(resolve => setTimeout(resolve, 0));
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function findButton(container, text) {
  // antd 两字中文按钮（非 link 型）会插空格，查找须归一化空白
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(text));
}

async function openConfirm() {
  act(() => {
    findButton(container, '发布新版本')
      .dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await flushAsync();
}

async function fillNoteAndConfirm(note) {
  const textarea = document.querySelector('#institution-change-note');
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype, 'value').set;
  act(() => {
    setter.call(textarea, note);
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  const okButton = document.querySelector('.ant-modal-confirm .ant-btn-primary');
  await act(async () => {
    okButton.click();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  http.post.mockResolvedValue({});
  store.manual = {id: 7, name: '科室操作手册', status: 'active',
    my_roles: ['publish'], current_version: {id: 9, version_no: 3}};
  store.publishPreview = null;
});

afterEach(() => {
  if (container) {
    ReactDOM.unmountComponentAtNode(container);
    container = null;
  }
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
  document.querySelectorAll('.ant-modal').forEach(el => el.remove());
  document.querySelectorAll('.ant-modal-wrap').forEach(el => el.remove());
  document.querySelectorAll('.ant-modal-mask').forEach(el => el.remove());
});

describe('PublishButton（发布新版本入口）', () => {
  it('点击发布先请求分组预检；重点展示变化文件，未修改以数量汇总可展开', async () => {
    setupPublishPreview();
    container = renderButton();
    await openConfirm();
    expect(store.fetchPublishPreview).toHaveBeenCalledWith(7);
    const modalText = document.body.textContent;
    expect(modalText).toContain('本次将把全部未移除文件发布为新的制度版本');
    expect(modalText).toContain('本次内容变化');
    expect(modalText).toContain('管理规定.docx');
    expect(modalText).toContain('新增文件');
    expect(modalText).toContain('SMS手册.docx');
    expect(modalText).toContain('被移除（不再进入新版本）');
    expect(modalText).toContain('旧附则.docx');
    expect(modalText).toContain('草稿 r3');
    // 未修改文件数量汇总 + 展开核对完整清单（默认折叠，不逐行罗列）
    expect(modalText).toContain('未修改（将继续纳入新版本）（1）');
    expect(modalText).toContain('展开核对完整清单（1）');
    expect(modalText).not.toContain('应急手册.docx');
    const expand = Array.from(document.querySelectorAll('.ant-modal a'))
      .find(a => a.textContent.includes('展开核对完整清单'));
    act(() => {
      expand.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(document.body.textContent).toContain('应急手册.docx');
    expect(document.querySelector('#institution-change-note')).not.toBeNull();
  });

  it('无内容/结构变化（非首发）：提示无需重复发布并禁用确认', async () => {
    setupPublishPreview({
      changed: [], added: [], removed: [],
      has_changes: false,
      unchanged: [
        {file_id: 12, name: '应急手册.docx', sort_order: 1,
          draft_revision: 1, draft_size: 1024, change_type: 'unchanged'},
      ],
    });
    container = renderButton();
    await openConfirm();
    expect(document.body.textContent).toContain('当前没有内容或结构变化，无需重复发布');
    expect(document.querySelector('.ant-modal-confirm .ant-btn-primary').disabled)
      .toBe(true);
    expect(http.post).not.toHaveBeenCalled();
  });

  it('预检失败不开确认窗（拦截器已提示，不产生成功语义）', async () => {
    store.fetchPublishPreview.mockImplementation(
      function () { return Promise.reject('预检失败'); });
    container = renderButton();
    await openConfirm();
    expect(document.querySelector('.ant-modal-confirm')).toBeNull();
  });

  it('受阻文件点名、确认按钮禁用；我的会话给出"去结束会话"处理入口', async () => {
    setupPublishPreview({
      changed: [], added: [],
      blocked: [
        {file_id: 16, name: '编辑中文件.docx', sort_order: 4, reason: 'session_busy',
          message: '该文件仍有进行中的编辑会话（含未完成的同步）',
          session: {is_mine: true, user_name: 'editor'}},
      ],
    });
    container = renderButton();
    await openConfirm();
    const modalText = document.body.textContent;
    expect(modalText).toContain('受阻文件（处理后方可发布）');
    expect(modalText).toContain('编辑中文件.docx');
    expect(modalText).toContain('去结束我的编辑会话');
    const okButton = document.querySelector('.ant-modal-confirm .ant-btn-primary');
    // 受阻时禁用确认：不让用户点击必然被服务端拒绝的按钮
    expect(okButton.disabled).toBe(true);
    expect(http.post).not.toHaveBeenCalled();
  });

  it('他人会话受阻：显示等待说明；缺草稿且持编制角色：给出"去恢复草稿"入口', async () => {
    store.manual = Object.assign({}, store.manual, {my_roles: ['publish', 'edit']});
    setupPublishPreview({
      changed: [], added: [],
      blocked: [
        {file_id: 17, name: '他人文件.docx', sort_order: 5, reason: 'session_busy',
          message: '该文件仍有进行中的编辑会话（含未完成的同步）',
          session: {is_mine: false, user_name: '李四'}},
        {file_id: 18, name: '无草稿文件.docx', sort_order: 6, reason: 'no_draft',
          message: '该文件还没有可发布的草稿'},
      ],
    });
    container = renderButton();
    await openConfirm();
    const modalText = document.body.textContent;
    expect(modalText).toContain('需该账号保存并退出会话');
    expect(modalText).toContain('去恢复草稿');
    expect(document.querySelector('.ant-modal-confirm .ant-btn-primary').disabled)
      .toBe(true);
  });
});

describe('PublishButton（受阻处理与确认发布）', () => {
  it('缺草稿且无编制角色（发布者）：说明需文件负责人处理，不渲染注定失败的入口', async () => {
    setupPublishPreview({
      changed: [], added: [],
      blocked: [{file_id: 18, name: '无草稿文件.docx', sort_order: 6,
        reason: 'no_draft', message: '该文件还没有可发布的草稿'}],
    });
    container = renderButton();
    await openConfirm();
    const modalText = document.body.textContent;
    expect(modalText).toContain('需该文件负责人（持编制资格）建立草稿');
    expect(modalText).not.toContain('去恢复草稿');
  });

  it('填写变更说明确认后 POST publish 并统一刷新（生命周期刷新入口）', async () => {
    setupPublishPreview();
    container = renderButton();
    await openConfirm();
    await fillNoteAndConfirm('整套核对后发布');
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/7/publish/', {change_note: '整套核对后发布'});
    expect(message.success).toHaveBeenCalled();
    expect(store.refreshAfterLifecycle).toHaveBeenCalledWith(7);
  });

  it('发布失败不显示成功、不刷新（错误由拦截器统一提示）', async () => {
    setupPublishPreview();
    container = renderButton();
    await openConfirm();
    http.post.mockRejectedValueOnce('文件「管理规定.docx」仍有进行中的编辑会话');
    await fillNoteAndConfirm('受阻发布');
    expect(message.success).not.toHaveBeenCalled();
    expect(store.refreshAfterLifecycle).not.toHaveBeenCalled();
  });
});

describe('PublishButton（入口可见性与弱化）', () => {
  it('无发布角色不渲染按钮；归档手册不渲染', () => {
    store.manual = Object.assign({}, store.manual, {my_roles: ['view']});
    container = renderButton();
    expect(container.textContent).toBe('');
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    store.manual = Object.assign({}, store.manual,
      {my_roles: ['publish'], status: 'archived'});
    act(() => {
      ReactDOM.render(<PublishButton/>, container);
    });
    expect(container.textContent).toBe('');
  });

  it('已生效且无待发布变化：发布入口弱化为非主按钮（仍可点开核对）', () => {
    store.draftStatus = {summary: {has_current_version: true,
      has_pending_changes: false, current_version_no: 3}};
    container = renderButton();
    const btn = findButton(container, '发布新版本');
    expect(btn).not.toBeUndefined();
    expect(btn.className).not.toContain('ant-btn-primary');
    // 有待发布变化时仍为主按钮
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    store.draftStatus = {summary: {has_current_version: true,
      has_pending_changes: true, current_version_no: 3}};
    act(() => {
      ReactDOM.render(<PublishButton/>, container);
    });
    expect(findButton(container, '发布新版本').className)
      .toContain('ant-btn-primary');
  });
});

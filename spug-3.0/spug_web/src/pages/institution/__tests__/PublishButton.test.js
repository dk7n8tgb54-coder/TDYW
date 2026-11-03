/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 发布新版本入口测试（2026-10-29 交互优化：发布主入口上移到详情头部
 * 整套待发布状态旁，PublishButton 组件；2026-11-03 固定快照交接）：
 * - 点击先请求 publish-preview 分组预检，确认窗口展示 固定文案+全部分组；
 * - 受阻文件点名、给出可执行处理入口（我的会话→工作台深链结束会话；
 *   他人会话→等待说明；缺草稿→编制角色（负责人）恢复 / 无编制角色说明；
 *   unassigned→所有者/管理员"去修订草稿视图指定负责人"、
 *   submission_pending/submission_stale→"等待有效负责人「X」提交/重新提交
 *   待发布核对"（逐份 message 来自服务端，确认按钮禁用；服务端仍权威校验）；
 * - 逐行固定快照核对信息（服务端 publish_source 决定，前端不臆测）：
 *   draft→"将使用当前草稿"（发布人即有效负责人时再无需要提交）、
 *   submission→"将使用已提交快照（提交人 X，提交时间 Y）"、
 *   current_version→"将沿用当前生效快照（内容未变化）"；
 *   有效负责人展示 owner_assigned=false 时注明"（手册所有者，默认）"，
 *   提交记录状态=待发布人核对/已撤回/已退回/提交已失效/尚未提交待发布核对；
 *   publish_source=null（旧后端）时不输出来源文案，保持旧展示；
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

// 发布成功后的菜单红点刷新钩子（InstitutionBadgeStore 单例）单独 mock：
// 本套件聚焦发布流程本身，红点 store 契约钉死在 layout/__tests__
jest.mock('../../../layout/InstitutionBadgeStore', () => ({
  __esModule: true,
  default: {fetch: jest.fn()},
}));

import PublishButton from '../detail/PublishButton';
import {message} from 'antd';
import {history} from 'libs';
import {http} from 'libs';
import store from '../detail/store';
import institutionBadge from '../../../layout/InstitutionBadgeStore';

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
    // 发布语义：完整/不可变的新版本快照；发布后保留当前草稿作为后续
    // 修订工作副本；历史发布版本不会被本次或后续发布覆盖
    expect(modalText).toContain('完整、不可变的新版本快照');
    expect(modalText).toContain('发布后保留当前草稿作为后续修订的工作副本');
    expect(modalText).toContain('不会被本次或后续发布覆盖');
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

describe('PublishButton（固定快照交接：逐份发布来源与提交状态）', () => {
  const PENDING = {status: 'pending', state: 'submitted', frozen: true,
    submitted_at: '2026-01-05T09:00:00', submitted_by_name: '张三',
    submission_revision: 3, draft_revision: 3};
  const NONE = {status: 'none', submitted_at: null, submitted_by_name: '',
    submission_revision: null, draft_revision: 3};

  it('变化行：发布人即有效负责人 → 将使用当前草稿；需提交行显示已提交快照来源与提交人时间', async () => {
    setupPublishPreview({
      changed: [{file_id: 11, name: '管理规定.docx', sort_order: 0,
        draft_revision: 3, draft_size: 2048, change_type: 'modified',
        owner_id: 9, owner_name: '我', submission: NONE,
        publisher_is_owner: true, submission_required: false,
        publish_source: 'draft', content_changed: true}],
      added: [{file_id: 13, name: 'SMS手册.docx', sort_order: 2,
        draft_revision: 1, draft_size: 4096, change_type: 'added',
        owner_id: 10, owner_name: '张三', submission: PENDING,
        publisher_is_owner: false, submission_required: true,
        publish_source: 'submission', content_changed: true}],
      unchanged: [{file_id: 12, name: '应急手册.docx', sort_order: 1,
        draft_revision: 1, draft_size: 1024, change_type: 'unchanged',
        owner_id: null, owner_name: '', owner_assigned: false,
        effective_owner_name: '王五', submission: NONE,
        publisher_is_owner: false, submission_required: false,
        publish_source: 'current_version', content_changed: false}],
    });
    container = renderButton();
    await openConfirm();
    const modalText = document.body.textContent;
    // 逐份发布来源（服务端 publish_source）
    expect(modalText).toContain('将使用当前草稿');
    expect(modalText).toContain('将使用已提交快照（提交人 张三，提交时间 2026-01-05 09:00:00）');
    expect(modalText).toContain('发布人即该文件有效负责人，无需提交');
    // 提交记录状态与有效负责人（默认负责人注明手册所有者默认）
    expect(modalText).toContain('待发布人核对');
    expect(modalText).toContain('负责人 张三');
    // 未修改文件：沿用当前生效快照（折叠时仅数量汇总，展开后逐行展示）
    const expand = Array.from(document.querySelectorAll('.ant-modal a'))
      .find(a => a.textContent.includes('展开核对完整清单'));
    act(() => {
      expand.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(document.body.textContent)
      .toContain('将沿用当前生效快照（内容未变化）');
    expect(document.body.textContent).toContain('负责人 王五（手册所有者，默认）');
    // 无需提交行不显示误导性「未提交」
    expect(document.body.textContent).not.toContain('未提交');
  });

  it('新增阻断原因：unassigned 所有者指引 / submission_pending·stale 等待有效负责人提交', async () => {
    store.manual = Object.assign({}, store.manual, {is_owner: true});
    setupPublishPreview({
      changed: [], added: [], removed: [], unchanged: [],
      blocker_summary: {unassigned: 1, submission_pending: 1, submission_stale: 1},
      blocked: [
        {file_id: 21, name: '新增未分配.docx', sort_order: 0, reason: 'unassigned',
          message: '文件「新增未分配.docx」未分配负责人，本次新增或内容变化须先指定负责人',
          owner_id: null, owner_name: '', submission: NONE,
          publisher_is_owner: false, submission_required: true,
          publish_source: null, content_changed: true},
        {file_id: 22, name: '待提交.docx', sort_order: 1, reason: 'submission_pending',
          message: '文件「待提交.docx」等待有效负责人「张三」提交待发布核对',
          owner_id: 10, owner_name: '张三', effective_owner_name: '张三',
          submission: NONE,
          publisher_is_owner: false, submission_required: true,
          publish_source: null, content_changed: true},
        {file_id: 23, name: '提交失效.docx', sort_order: 2, reason: 'submission_stale',
          message: '文件「提交失效.docx」提交待发布核对已失效，请有效负责人「李四」重新提交',
          owner_id: 11, owner_name: '李四', effective_owner_name: '李四',
          submission: {...PENDING, state: 'stale', submitted_by_name: '李四',
            submission_revision: 1, draft_revision: 3},
          publisher_is_owner: false, submission_required: true,
          publish_source: null, content_changed: true},
      ],
    });
    container = renderButton();
    await openConfirm();
    const modalText = document.body.textContent;
    // 逐份展示服务端 message（三种阻断原因）+ 有效负责人 + 提交状态
    expect(modalText).toContain('未分配负责人，本次新增或内容变化须先指定负责人');
    expect(modalText).toContain('等待有效负责人「张三」提交待发布核对');
    expect(modalText).toContain('提交待发布核对已失效，请有效负责人「李四」重新提交');
    expect(modalText).toContain('尚未提交待发布核对');
    expect(modalText).toContain('提交已失效');
    // 汇总用 blocker_summary 计数（新文案）
    expect(modalText).toContain('未分配负责人 1 份');
    expect(modalText).toContain('待负责人提交待发布核对 1 份');
    expect(modalText).toContain('提交已失效 1 份');
    // 所有者：unassigned 给出"去修订草稿视图指定负责人"指引
    expect(modalText).toContain('请在「修订草稿」视图为该文件指定负责人');
    // 交接类阻断：等待说明，不渲染链接、不做单/多人模式切换
    expect(modalText).toContain('等待有效负责人「张三」提交待发布核对');
    expect(modalText).toContain('等待有效负责人「李四」重新提交待发布核对');
    expect(document.querySelectorAll('.ant-modal a').length).toBe(0);
    // 存在受阻文件 → 禁用确认
    expect(document.querySelector('.ant-modal-confirm .ant-btn-primary').disabled)
      .toBe(true);
    expect(http.post).not.toHaveBeenCalled();
  });

  it('非所有者非管理员：unassigned 显示需所有者/管理员指定负责人', async () => {
    setupPublishPreview({
      changed: [], added: [], removed: [], unchanged: [],
      blocked: [
        {file_id: 21, name: '新增未分配.docx', sort_order: 0, reason: 'unassigned',
          message: '文件「新增未分配.docx」未分配负责人，本次新增或内容变化须先指定负责人',
          owner_name: '', submission: NONE},
      ],
    });
    container = renderButton();
    await openConfirm();
    const modalText = document.body.textContent;
    expect(modalText).toContain('需手册所有者/管理员指定负责人');
    expect(modalText).not.toContain('请在「修订草稿」视图为该文件指定负责人');
  });

  it('旧后端缺失交接字段：保持旧展示（负责人+草稿修订号+提交状态），不臆测发布来源', async () => {
    setupPublishPreview({
      changed: [{file_id: 11, name: '管理规定.docx', sort_order: 0,
        draft_revision: 3, draft_size: 2048, change_type: 'modified',
        owner_name: '张三', submission: NONE}],
      added: [], unchanged: [], removed: [],
    });
    container = renderButton();
    await openConfirm();
    const modalText = document.body.textContent;
    expect(modalText).toContain('草稿 r3');
    expect(modalText).toContain('负责人 张三');
    // 旧后端无 publish_source：不输出任何来源文案（不臆测草稿/快照）
    expect(modalText).not.toContain('将使用当前草稿');
    expect(modalText).not.toContain('将使用已提交快照');
    expect(modalText).not.toContain('将沿用当前生效快照');
    // 旧后端无 submission_required：仍按旧版展示提交记录状态
    expect(modalText).toContain('尚未提交待发布核对');
    expect(modalText).not.toContain('发布人即该文件负责人，无需提交');
    expect(modalText).not.toContain('未变化，无需提交');
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
    // 发布真实成功后立即刷新菜单红点（待核对提交数清零）
    expect(institutionBadge.fetch).toHaveBeenCalled();
  });

  it('发布失败不显示成功、不刷新（错误由拦截器统一提示）', async () => {
    setupPublishPreview();
    container = renderButton();
    await openConfirm();
    http.post.mockRejectedValueOnce('文件「管理规定.docx」仍有进行中的编辑会话');
    await fillNoteAndConfirm('受阻发布');
    expect(message.success).not.toHaveBeenCalled();
    expect(store.refreshAfterLifecycle).not.toHaveBeenCalled();
    // 业务失败不得刷新红点
    expect(institutionBadge.fetch).not.toHaveBeenCalled();
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

  it('owner 的 my_roles 由后端下发含 publish：发布按钮可见（前端透传不特判）', () => {
    // 二轮权限模型改造：所有者全部权限由后端经 my_roles 下发，前端不特判
    store.manual = Object.assign({}, store.manual,
      {my_roles: ['view', 'edit', 'publish'], is_owner: true});
    container = renderButton();
    expect(findButton(container, '发布新版本')).not.toBeUndefined();
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

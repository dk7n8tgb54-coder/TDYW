/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台（多文件）组件行为测试（jsdom + ReactDOM）：
 * - 多文件制度：左侧文件导航（名称/有效负责人/修订号（次要灰字）/编辑占用/
 *   编制状态 Tag），右侧编辑区主体；单文件制度不渲染导航。
 * - 右侧顶部状态条：当前文件/修订号/独立的"制度草稿保存状态"（服务端
 *   确认落盘才显示"已保存到制度草稿：rN、时间"）/编制状态 Tag；
 *   流程按钮 开始编辑 → 保存并结束编辑 → 提交待发布核对。
 * - 编制状态与详情页同一口径（compilationStatusShared.buildCompilationState）：
 *   待发布人核对/可直接纳入整套发布/待提交待发布核对/待负责人提交待发布核对/
 *   已撤回/已退回/提交已失效/旧版提交记录/编制中/无需提交；草稿工作台
 *   没有 draft-status，relation 传 null（已发布无变化绝不当成待提交）。
 * - 提交待发布核对仅文件有效负责人（assignment.is_effective_owner，旧
 *   payload 回退 is_mine）渲染：手册所有者非该文件有效负责人不得代提交；
 *   pending 显示不可点击「待发布人核对」+「撤回提交」；提交失效「重新提交」；
 *   本文件编辑会话进行中禁用并提示先「保存并结束编辑」；有效负责人兼发布权
 *   时提示可直接纳入整套发布、提交只是交给其他发布人核对快照的可选动作。
 *   **冻结文件（有效提交固定快照）不渲染编辑器与任何编辑/结构入口**，改
 *   提示内容冻结并提供「预览待核对快照」「下载待核对快照」。提交/撤回/退回
 *   真实成功后刷新清单 + 菜单红点（InstitutionBadgeStore，事件驱动）。
 * - 「保存并结束编辑」：降级路径直接撤销会话；在线路径经 forcesave +
 *   轮询确认落盘 + no_changes 复核后才撤销（成功/超时/失败三态）。
 * - 切换文件/返回详情的离开保护与保存状态显示的组件行为测试拆分至
 *   draft.workspace.leaveGuard.test.js（文件行数门禁，只减不增）。
 * - 密码门验证成功=第一份有草稿文件的会话建立并进入工作区；本地恢复
 *   会话时跳过密码门；?file= 深链目标不可用时给出明确状态。
 * - 保存失败错误含"会话"时清除该文件会话且不重复弹错（HTTP 拦截器已
 *   提示，业务代码不得再 message.error，也不得弹假成功）。
 * - 新增文件：每个上传文件各建立一个独立制度文件与当前草稿；创建成功提示
 *   等待真实响应，失败由 HTTP 拦截器提示（不再有 draft_error 业务警示）；
 *   新增文件负责人默认手册所有者（候选 assignment-owners）。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { message } from 'antd';

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

jest.mock('../draft/OnlyOfficeEditor', () => function OnlyOfficeEditor() {
  return null;
});
jest.mock('../detail/PreviewModal', () => function PreviewModal() {
  return null;
});
jest.mock('../../../layout/useWorkTabUnsaved', () => () => {});
// 菜单红点：提交待发布核对真实成功后应刷新（事件驱动，测试只断言被调用）
jest.mock('../../../layout/InstitutionBadgeStore', () => ({fetch: jest.fn()}));

import InstitutionDraftWorkspace from '../draft';
import institutionBadge from '../../../layout/InstitutionBadgeStore';
import {http} from 'libs';
import store from '../draft/store';

function makeFile(id, overrides) {
  return Object.assign({
    id,
    manual_id: 5,
    name: `文件${id}`,
    sort_order: id,
    is_removed: false,
    // 真实 /files/ 行：有草稿且修订轮开启（显示"待提交/编制中"的常态）
    revision_open: true,
    created_at: '2026-10-01T10:00:00',
    draft: {
      id: 100 + id,
      revision: id,
      file_name: `文件${id}.docx`,
      file_size: 1024,
      file_hash: `hash-${id}`,
      base_version_id: null,
      last_saved_by_name: '张三',
      last_saved_at: '2026-10-01T10:00:00',
      created_at: '2026-10-01T10:00:00',
    },
    active_session: null,
    // 2026-10-31 负责人独占：默认当前账号是负责人（会话/提交入口可见）
    assignment: {owner_id: 9, owner_name: '我', note: '', is_mine: true},
  }, overrides);
}

function mockFetch(files, manual) {
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: false});
    }
    if (url.includes('/files/')) return Promise.resolve(files);
    return Promise.resolve(manual || {id: 5, name: '测试手册', owner_id: 9,
      my_roles: ['edit'], is_owner: true, is_admin: false});
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

let pageInstance = null;

function renderPage() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    pageInstance = ReactDOM.render(
      React.createElement(InstitutionDraftWorkspace, {match: {params: {id: '5'}}}),
      container);
  });
  return container;
}

function findListRows(container) {
  return Array.from(container.querySelectorAll('div'))
    .filter(el => el.style && el.style.cursor === 'pointer');
}

function findButton(container, text) {
  return Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.includes(text));
}

function findFileInputs(container) {
  return Array.from(container.querySelectorAll('input[type="file"]'));
}

function click(el) {
  el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
}

let errorSpy, successSpy, warningSpy;

beforeEach(() => {
  jest.clearAllMocks();
  store.reset();
  pageInstance = null;
  sessionStorage.clear();
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  warningSpy = jest.spyOn(message, 'warning').mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
  successSpy.mockRestore();
  warningSpy.mockRestore();
  Array.from(document.body.children).forEach(el => {
    if (el.tagName === 'DIV') el.remove();
  });
});

describe('草稿工作台（多文件清单）', () => {
  it('多文件制度渲染有序清单，点击切换选中文件', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    // 无会话时先见密码门；已过密码门（本次访问已验证）后进入工作区
    expect(container.textContent).toContain('验证并进入编辑');
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('待发布文件（共 2 份）');
    expect(container.textContent).toContain('文件1');
    expect(container.textContent).toContain('文件2');
    expect(container.textContent).toContain('r2');
    // 独立保存状态：非在线编辑文件直接呈现服务端草稿数据（服务端确认）
    expect(container.textContent).toContain('已保存到制度草稿：r1');
    expect(container.textContent).toContain('张三');
    // 工作区默认选中第一份文件
    expect(container.textContent).toContain('当前文件：文件1');
    // 点击第二行切换选中文件，工作区随之切换
    const rows = findListRows(container);
    expect(rows).toHaveLength(2);
    await act(async () => {
      click(rows[1]);
      await Promise.resolve();
    });
    expect(store.selectedFileId).toBe(2);
    expect(container.textContent).toContain('当前文件：文件2');
    // 切换到无会话文件不触发编辑配置请求
    const configCalls = http.get.mock.calls.filter(
      ([url]) => url.includes('editor-config'));
    expect(configCalls).toHaveLength(0);
  });

  it('单文件制度不渲染清单，直接显示工作区', async () => {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).not.toContain('待发布文件');
    expect(container.textContent).toContain('当前文件：文件1');
  });

  it('0 文件空态指向详情页「文件清单 → 修订草稿」的「新增制度文件」（上传直接生成当前草稿）', async () => {
    mockFetch([]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('该制度还没有待发布文件');
    expect(container.textContent).toContain('文件清单 → 修订草稿');
    expect(container.textContent).toContain('新增待发布文件');
    // 上传文件直接生成当前草稿（每个上传文件各建独立制度文件与草稿）
    expect(container.textContent).toContain('上传文件作为待发布文件的当前草稿');
    expect(container.textContent).toContain('当前草稿');
    // 已取消的历史来源入口不得再出现
    expect(container.textContent).not.toContain('初始来源');
    expect(container.textContent).not.toContain('原稿');
  });

  it('本地恢复了会话时跳过密码门直接进入工作区并取编辑配置', async () => {
    sessionStorage.setItem('institution_edit_session_5_1',
      JSON.stringify({sessionKey: 'sess-1', expiresAt: '2099-01-01T00:00:00'}));
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(container.textContent).not.toContain('验证并进入编辑');
    expect(container.textContent).toContain('当前文件：文件1');
    const configCalls = http.get.mock.calls.filter(
      ([url]) => url.includes('editor-config'));
    expect(configCalls).toHaveLength(1);
    // editor_available=false：显示本机编辑降级提示
    expect(container.textContent).toContain('在线编辑服务未配置');
  });
});

describe('草稿工作台（密码门与按文件会话）', () => {
  it('密码门验证成功=第一份有草稿文件的会话建立并进入工作区', async () => {
    mockFetch([makeFile(1), makeFile(2, {draft: null})]);
    const container = renderPage();
    await flush();
    expect(container.textContent).toContain('验证并进入编辑');
    expect(container.textContent).not.toContain('当前文件：');
    const pwInput = container.querySelector('input[type="password"]');
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    await act(async () => {
      setter.call(pwInput, 'pw1');
      pwInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
    http.post.mockResolvedValue({
      session_key: 'sess-1', expires_at: '2099-01-01T00:00:00',
      revision: 1, file_name: '文件1.docx', base_version_id: null,
    });
    await act(async () => {
      click(findButton(container, '验证并进入编辑'));
      await Promise.resolve();
    });
    await flush();
    // 无草稿的第一份不能承载会话：会话建立在有草稿的文件 1 上
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/session/', {password: 'pw1'});
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(container.textContent).toContain('当前文件：文件1');
    // 成功提示等真实成功后给出
    expect(successSpy).toHaveBeenCalledWith('已进入编辑会话');
  });

  it('无已验证密码时「开始编辑此文件」回密码门且不发请求', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    // 模拟恢复会话直入工作区（本次访问未过密码门）
    store.passwordVerified = true;
    store.verifiedPassword = '';
    await flush();
    const rows = findListRows(container);
    await act(async () => {
      click(rows[1]);
      await Promise.resolve();
    });
    const startBtn = findButton(container, '开始编辑');
    expect(startBtn).not.toBeUndefined();
    await act(async () => {
      click(startBtn);
      await Promise.resolve();
    });
    await flush();
    expect(http.post).not.toHaveBeenCalled();
    expect(store.passwordVerified).toBe(false);
    // 回到密码门
    expect(container.textContent).toContain('验证并进入编辑');
  });

  it('「开始编辑」用已验证密码开启该文件会话', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.verifiedPassword = 'pw1';
    await flush();
    const rows = findListRows(container);
    await act(async () => {
      click(rows[1]);
      await Promise.resolve();
    });
    http.post.mockResolvedValue({
      session_key: 'sess-2', expires_at: '2099-01-01T00:00:00',
      revision: 2, file_name: '文件2.docx', base_version_id: null,
    });
    const startBtn = findButton(container, '开始编辑');
    expect(startBtn).not.toBeUndefined();
    await act(async () => {
      click(startBtn);
      await Promise.resolve();
    });
    await flush();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/2/draft/session/', {password: 'pw1'});
    expect(store.sessionKeyOf(2)).toBe('sess-2');
    expect(successSpy).toHaveBeenCalledWith('编辑会话已开启');
    // 会话开启后流程按钮切换为「保存并结束编辑」（确认落盘后才撤销会话）
    expect(findButton(container, '保存并结束编辑')).not.toBeUndefined();
    expect(findButton(container, '开始编辑')).toBeUndefined();
  });
});

describe('草稿工作台（保存与新增文件）', () => {
  it('保存失败错误含"会话"时清除该文件会话且不重复弹错', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.verifiedPassword = 'pw1';
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    await flush();
    expect(container.textContent).toContain('当前文件：文件1');
    // 第二个隐藏 input 为保存上传控件（第一个是新增文件控件）；
    // 本机上传须先有下载基线（模拟已下载草稿 r1）
    store.recordLocalBaseline(1, 1);
    const saveInput = findFileInputs(container)[1];
    expect(saveInput).not.toBeUndefined();
    http.post.mockRejectedValue('编辑会话已过期，请重新验证密码');
    Object.defineProperty(saveInput, 'files',
      {value: [new File(['x'], 'a.docx')]});
    await act(async () => {
      saveInput.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await flush();
    // 该文件会话被清除（回验证态），错误含"会话"不回密码门
    expect(store.sessionKeyOf(1)).toBe('');
    expect(sessionStorage.getItem('institution_edit_session_5_1')).toBeNull();
    expect(store.passwordVerified).toBe(true);
    // 拦截器（真实环境）已提示：业务代码不得再弹错，也不得弹假成功
    expect(errorSpy).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    // 工作区仍在，该文件回到"未持会话"状态并给出开始编辑入口
    expect(container.textContent).not.toContain('验证并进入编辑');
    expect(findButton(container, '开始编辑')).not.toBeUndefined();
  });

  it('点击新增文件按钮触发隐藏 file input（死按钮回归防护）', async () => {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addBtn = findButton(container, '新增文件');
    expect(addBtn).not.toBeUndefined();
    const clickSpy = jest.spyOn(HTMLInputElement.prototype, 'click')
      .mockImplementation(() => {});
    await act(async () => {
      click(addBtn);
      await Promise.resolve();
    });
    expect(clickSpy).toHaveBeenCalledTimes(1);
    clickSpy.mockRestore();
  });

  it('新增文件成功：每个上传文件各建独立条目+当前草稿，成功提示等真实响应', async () => {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addInput = findFileInputs(container)[0];
    const created = {id: 2, name: '新文件', sort_order: 2,
      draft: {revision: 1, file_name: '新文件.docx'}, active_session: null};
    http.post.mockResolvedValue(created);
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1), created]);
      return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit'], is_owner: true, is_admin: false});
    });
    Object.defineProperty(addInput, 'files',
      {value: [new File(['x'], 'new.docx')]});
    await act(async () => {
      addInput.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await flush();
    // 选中文件后先弹分工弹窗（负责人可选），点「创建」才上传
    const okBtn = document.querySelector('.ant-modal .ant-btn-primary');
    expect(okBtn).not.toBeNull();
    await act(async () => {
      okBtn.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    // 单次上传=单个独立制度文件（不追加到同一项），一次 files/create
    expect(http.post).toHaveBeenCalledTimes(1);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/create/', expect.any(FormData));
    // 成功提示只在真实成功后出现；无 draft_error 类警示
    expect(successSpy).toHaveBeenCalledWith('文件已新增');
    expect(warningSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(store.files).toHaveLength(2);
    expect(container.textContent).toContain('待发布文件（共 2 份）');
  });

  it('新增文件失败：由 HTTP 拦截器提示一次，不弹业务警示、不假成功、清单不变', async () => {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addInput = findFileInputs(container)[0];
    http.post.mockRejectedValue(
      '文件「新文件.docx」.doc 转换为 .docx 失败，未创建制度文件，请改用 .docx 上传或联系管理员');
    Object.defineProperty(addInput, 'files',
      {value: [new File(['x'], 'new.doc')]});
    await act(async () => {
      addInput.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await flush();
    await act(async () => {
      document.querySelector('.ant-modal .ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).toHaveBeenCalledTimes(1);
    // 拦截器已提示：业务代码不得重复弹错，也不得报成功或 draft_error 警示
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warningSpy).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    expect(store.files).toHaveLength(1);
    // 失败不自动关闭分工弹窗（保留用户上下文）：显式关闭，避免弹窗残留
    // 到后续用例（antd Modal 经 portal 渲染在 document.body）
    await act(async () => {
      pageInstance.setState({pendingFile: null});
    });
  });
});

describe('草稿工作台（文件分工）', () => {
  it('新增文件弹窗可指定负责人与分工说明，确认后携带 owner_id/note 上传', async () => {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addInput = findFileInputs(container)[0];
    http.post.mockResolvedValue(
      {id: 2, name: '新文件', sort_order: 2, draft: null, active_session: null});
    Object.defineProperty(addInput, 'files',
      {value: [new File(['x'], 'new.docx')]});
    await act(async () => {
      addInput.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await flush();
    // 直接以组件状态预置负责人选择（Select 交互属 antd 内部实现细节）
    await act(async () => {
      pageInstance.setState({assignOwnerId: 9, assignNote: '由乙编制'});
    });
    await act(async () => {
      document.querySelector('.ant-modal .ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/create/', expect.any(FormData));
    const formData = http.post.mock.calls[0][1];
    expect(formData.get('owner_id')).toBe('9');
    expect(formData.get('note')).toBe('由乙编制');
  });

  it('新增文件负责人默认手册所有者，可改选其他持编制资格账号或清空（创建携带 owner_id/note）', async () => {
    const manual = {id: 5, name: '测试手册', owner_id: 9,
      my_roles: ['edit'], is_owner: true, is_admin: false};
    http.get.mockImplementation(url => {
      if (url.includes('assignment-owners')) {
        return Promise.resolve([{id: 9, name: '所有者甲'}, {id: 8, name: '乙'}]);
      }
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve(manual);
    });
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addInput = findFileInputs(container)[0];
    http.post.mockResolvedValue(
      {id: 2, name: '新文件', sort_order: 2, draft: null, active_session: null});
    Object.defineProperty(addInput, 'files',
      {value: [new File(['x'], 'new.docx')]});
    await act(async () => {
      addInput.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await flush();
    // 打开即默认负责人=手册所有者（不预置其他选择）
    expect(pageInstance.state.assignOwnerId).toBe(9);
    expect(pageInstance.state.assignOwners)
      .toEqual([{id: 9, name: '所有者甲'}, {id: 8, name: '乙'}]);
    // 直接确认：创建携带默认所有者
    await act(async () => {
      document.querySelector('.ant-modal .ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/create/', expect.any(FormData));
    const created = http.post.mock.calls[0][1];
    expect(created.get('owner_id')).toBe('9');
  });

  it('新增文件负责人可清空：清空后创建显式携带空 owner_id（未分配，绝不回退所有者）', async () => {
    const manual = {id: 5, name: '测试手册', owner_id: 9,
      my_roles: ['edit'], is_owner: true, is_admin: false};
    http.get.mockImplementation(url => {
      if (url.includes('assignment-owners')) {
        return Promise.resolve([{id: 9, name: '所有者甲'}]);
      }
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve(manual);
    });
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addInput = findFileInputs(container)[0];
    http.post.mockResolvedValue(
      {id: 2, name: '新文件', sort_order: 2, draft: null, active_session: null});
    Object.defineProperty(addInput, 'files',
      {value: [new File(['x'], 'new.docx')]});
    await act(async () => {
      addInput.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await flush();
    expect(pageInstance.state.assignOwnerId).toBe(9);
    await act(async () => {
      pageInstance.setState({assignOwnerId: undefined});
    });
    await act(async () => {
      document.querySelector('.ant-modal .ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    const created = http.post.mock.calls[0][1];
    // 后端契约：字段存在且为空串=未分配；字段缺失才默认手册所有者。
    // 清空负责人必须显式发送空串，不能被静默改派给所有者。
    expect(created.get('owner_id')).toBe('');
  });

  it('新增文件候选加载失败：弹窗内展示错误与重试（请求抑制拦截器弹错）', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('assignment-owners')) return Promise.reject('权限拒绝');
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit'], is_owner: true, is_admin: false});
    });
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addInput = findFileInputs(container)[0];
    Object.defineProperty(addInput, 'files',
      {value: [new File(['x'], 'new.docx')]});
    await act(async () => {
      addInput.dispatchEvent(new Event('change', {bubbles: true}));
    });
    await flush();
    const modal = document.querySelector('.ant-modal');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain('负责人候选加载失败');
    expect(modal.textContent).toContain('权限拒绝');
    expect(modal.textContent).toContain('重试');
    // 错误只在弹窗内展示一次：请求必须抑制 HTTP 拦截器提示
    const ownersCall = http.get.mock.calls.find(
      c => c[0].includes('assignment-owners'));
    expect(ownersCall[1]).toEqual({skipErrorNotification: true});
    // 重试成功：错误消失，候选进入下拉数据源
    http.get.mockImplementation(url => {
      if (url.includes('assignment-owners')) {
        return Promise.resolve([{id: 9, name: '乙'}]);
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit'], is_owner: true, is_admin: false});
    });
    const retryBtn = Array.from(modal.querySelectorAll('button'))
      .find(b => b.textContent.replace(/\s+/g, '') === '重试');
    expect(retryBtn).not.toBeUndefined();
    await act(async () => {
      retryBtn.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(document.querySelector('.ant-modal').textContent)
      .not.toContain('负责人候选加载失败');
    expect(pageInstance.state.assignOwners).toEqual([{id: 9, name: '乙'}]);
  });
});

describe('草稿工作台（文件分工展示与提交待发布核对）', () => {
  it('清单行显示负责人/未分配，选中文件卡展示负责人与分工说明', async () => {
    mockFetch([
      makeFile(1, {assignment: {owner_id: 9, owner_name: '乙', note: '负责正文',
        is_mine: false}}),
      makeFile(2, {assignment: {owner_id: null, owner_name: '', note: '',
        is_mine: false}}),
    ]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const text = container.textContent;
    expect(text).toContain('乙');
    expect(text).toContain('未分配');
    expect(text).toContain('负责正文');
  });

  it('有效负责人（is_effective_owner）可提交待发布核对：确认后 POST submit 并刷新清单', async () => {
    mockFetch([makeFile(1, {assignment: {owner_id: 9, owner_name: '我',
      note: '', is_mine: true, is_effective_owner: true,
      effective_owner_id: 9, effective_owner_name: '我'}})]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const submitBtn = findButton(container, '提交待发布核对');
    expect(submitBtn).not.toBeUndefined();
    http.post.mockResolvedValue({});
    await act(async () => {
      click(submitBtn);
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    const okBtn = document.querySelector('.ant-modal-confirm .ant-btn-primary');
    expect(okBtn).not.toBeNull();
    // 确认窗说明固定快照与冻结语义（不再有"无副本"措辞）
    expect(document.querySelector('.ant-modal-confirm').textContent)
      .toContain('固定不可变内容快照');
    await act(async () => {
      okBtn.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/submit/', {});
    expect(successSpy)
      .toHaveBeenCalledWith(expect.stringContaining('已提交待发布核对'));
    // 提交真实成功后刷新菜单红点（事件驱动，不轮询）
    expect(institutionBadge.fetch).toHaveBeenCalled();
  });

  it('非有效负责人行不渲染提交待发布核对接入', async () => {
    // 非所有者夹具：所有者可编辑任意文件，但提交入口仅文件有效负责人
    mockFetch([makeFile(1, {assignment: {owner_id: 8, owner_name: '丙',
      note: '', is_mine: false, is_effective_owner: false,
      effective_owner_id: 8, effective_owner_name: '丙'}})],
      {id: 5, name: '测试手册', my_roles: ['edit'], is_owner: false,
        is_admin: false});
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
  });
});

describe('草稿工作台（负责人独占与文件管理门控，2026-10-31）', () => {
  it('非负责人且非所有者（含持编制授权未指派者）：无开始编辑入口，显示明确指派提示', async () => {
    // 二轮权限模型改造：所有者例外可编辑任意文件，本用例收窄为非所有者
    mockFetch([makeFile(1, {assignment: {owner_id: 8, owner_name: '丙',
      note: '', is_mine: false}})],
      {id: 5, name: '测试手册', my_roles: ['edit'], is_owner: false,
        is_admin: false});
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(findButton(container, '开始编辑')).toBeUndefined();
    expect(container.textContent).toContain('编辑仅限文件负责人，请先由手册所有者指派');
    // 非负责人同样不渲染 下载/预览草稿（文件管理行按负责人收窄）
    expect(findButton(container, '下载草稿')).toBeUndefined();
    expect(findButton(container, '预览草稿')).toBeUndefined();
    expect(container.textContent).toContain('下载/预览草稿仅限文件负责人');
  });

  it('owner 对非本人负责文件出现开始编辑入口（所有者例外可编辑任意文件）', async () => {
    mockFetch([makeFile(1, {assignment: {owner_id: 8, owner_name: '丙',
      note: '', is_mine: false}})]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    // 默认夹具手册 is_owner=true：所有者对非本人负责文件渲染编辑入口
    //（后端 can_edit_file 已放行 owner），不再出现「编辑仅限文件负责人」
    expect(findButton(container, '开始编辑')).not.toBeUndefined();
    expect(container.textContent)
      .not.toContain('编辑仅限文件负责人，请先由手册所有者指派');
    // 下载/预览草稿与编辑入口同域：所有者同样可见
    expect(findButton(container, '下载草稿')).not.toBeUndefined();
    expect(findButton(container, '预览草稿')).not.toBeUndefined();
  });

  it('非所有者/管理员：文件管理行的 改名/移除/新增 不可见（下载预览由负责人可见）', async () => {
    mockFetch([makeFile(1)], {id: 5, name: '测试手册', my_roles: ['edit'],
      is_owner: false, is_admin: false});
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(findButton(container, '改名')).toBeUndefined();
    expect(findButton(container, '移除')).toBeUndefined();
    expect(findButton(container, '新增文件')).toBeUndefined();
    // 负责人可见下载/预览
    expect(findButton(container, '下载草稿')).not.toBeUndefined();
    expect(findButton(container, '预览草稿')).not.toBeUndefined();
  });

  it('多文件制度：非所有者/管理员导航底部无新增文件入口', async () => {
    mockFetch([makeFile(1), makeFile(2)], {id: 5, name: '测试手册',
      my_roles: ['edit'], is_owner: false, is_admin: false});
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('待发布文件（共 2 份）');
    expect(findButton(container, '新增文件')).toBeUndefined();
  });

  it('密码门：持编制授权但未指派负责人时明确提示（负责人独占）', async () => {
    mockFetch([makeFile(1, {assignment: {owner_id: 8, owner_name: '丙',
      note: '', is_mine: false}})]);
    const container = renderPage();
    await flush();
    expect(container.textContent).toContain('验证并进入编辑');
    expect(container.textContent).toContain('编辑仅限文件负责人');
    expect(container.textContent).toContain('尚未被指派任何文件的负责人');
  });
});

describe('草稿工作台（?file= 深链选中文件）', () => {
  it('清单就绪后选中 ?file= 指定文件（详情页"编辑此文件"入口）', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = document.createElement('div');
    document.body.appendChild(container);
    await act(async () => {
      ReactDOM.render(React.createElement(InstitutionDraftWorkspace,
        {match: {params: {id: '5'}}, location: {search: '?file=2'}}), container);
    });
    await flush();
    expect(store.selectedFileId).toBe(2);
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('当前文件：文件2');
  });

  it('?file= 指向不存在或已移除的文件时回落默认首个', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = document.createElement('div');
    document.body.appendChild(container);
    await act(async () => {
      ReactDOM.render(React.createElement(InstitutionDraftWorkspace,
        {match: {params: {id: '5'}}, location: {search: '?file=99'}}), container);
    });
    await flush();
    expect(store.selectedFileId).toBe(1);
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('当前文件：文件1');
  });

  it('?file= 指向不存在的文件时给出明确状态且不建立任何会话', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = document.createElement('div');
    document.body.appendChild(container);
    await act(async () => {
      ReactDOM.render(React.createElement(InstitutionDraftWorkspace,
        {match: {params: {id: '5'}}, location: {search: '?file=99'}}), container);
    });
    await flush();
    expect(store.deeplinkNotice).toContain('不存在或已移除');
    expect(container.textContent).toContain('未建立任何编辑会话');
    expect(store.hasAnySession).toBe(false);
    expect(http.post).not.toHaveBeenCalled();
  });

  it('?file= 指向无草稿文件时密码门禁用并明确提示（绝不静默改开其他文件）', async () => {
    mockFetch([makeFile(1), makeFile(2, {draft: null})]);
    const container = document.createElement('div');
    document.body.appendChild(container);
    await act(async () => {
      ReactDOM.render(React.createElement(InstitutionDraftWorkspace,
        {match: {params: {id: '5'}}, location: {search: '?file=2'}}), container);
    });
    await flush();
    expect(store.deeplinkNotice).toContain('还没有草稿');
    // 深链目标不可用：验证按钮禁用（不得改开文件 1 的会话）
    const verifyBtn = findButton(container, '验证并进入编辑');
    expect(verifyBtn.disabled).toBe(true);
    http.post.mockClear();
    await act(async () => {
      click(verifyBtn);
      await Promise.resolve();
    });
    await flush();
    expect(http.post).not.toHaveBeenCalled();
    expect(store.sessionKeyOf(1)).toBe('');
  });
});

describe('草稿工作台（保存并结束编辑）', () => {
  it('降级路径（无在线编辑器）：确认后撤销会话并提示成功', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.verifiedPassword = 'pw1';
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: false};
    await flush();
    const btn = findButton(container, '保存并结束编辑');
    expect(btn).not.toBeUndefined();
    http.delete.mockResolvedValue({});
    await act(async () => {
      click(btn);
      await Promise.resolve();
    });
    await flush();
    // 降级路径保存是同步 multipart：不请求 forcesave，直接撤销会话
    //（finishEditing 的 revoke 一律显式 discard=false 保存意图）
    expect(http.post).not.toHaveBeenCalled();
    expect(http.delete).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/session/',
      {data: {session_key: 'sess-1', discard: false}});
    expect(store.sessionKeyOf(1)).toBe('');
    expect(successSpy).toHaveBeenCalledWith('已保存并结束编辑');
  });

  it('在线路径成功：forcesave 受理 → 轮询确认修订号推进 → 复核 no_changes → 才撤销会话', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: true, document_key: 'k1'};
    store.pollIntervalMs = 1;
    store.confirmSettleMs = 0;
    await flush();
    const forceSaveCalls = () => http.post.mock.calls.filter(
      ([url]) => url.includes('forcesave'));
    http.post.mockImplementation(url => {
      if (url.includes('forcesave')) {
        // 第一次受理；修订号推进后的复核轮 DS 报告无更多待存修改
        return forceSaveCalls().length === 1
          ? Promise.resolve({forcesave: 'requested', revision: 1})
          : Promise.resolve({forcesave: 'no_changes', revision: 2});
      }
      return Promise.resolve({});
    });
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true});
      }
      if (url.endsWith('/draft/')) {
        return Promise.resolve({
          revision: 2, last_saved_at: '2026-10-30T10:00:00',
          last_saved_by_name: '张三',
        }); // 回调已落盘（r1 → r2）
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1), makeFile(2)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    http.delete.mockResolvedValue({});
    const btn = findButton(container, '保存并结束编辑');
    await act(async () => {
      click(btn);
      await new Promise(resolve => setTimeout(resolve, 30));
    });
    await flush();
    expect(forceSaveCalls().length).toBeGreaterThanOrEqual(2);
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/forcesave/',
      {session_key: 'sess-1'});
    expect(http.delete).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/session/',
      {data: {session_key: 'sess-1', discard: false}});
    expect(store.sessionKeyOf(1)).toBe('');
    expect(successSpy).toHaveBeenCalledWith('已保存并结束编辑');
    // 结束编辑撤销会话（clearSession）后确认记录随之清除：
    // 无会话文件的保存状态回落到服务端草稿数据展示
    expect(store.saveConfirmed[1]).toBeUndefined();
  });
});

describe('草稿工作台（保存并结束编辑：失败与超时保护）', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    store.reset();
    sessionStorage.clear();
    errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
    successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
    warningSpy = jest.spyOn(message, 'warning').mockImplementation(() => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
    successSpy.mockRestore();
    warningSpy.mockRestore();
    Array.from(document.body.children).forEach(el => {
      if (el.tagName === 'DIV') el.remove();
    });
  });

  it('在线路径超时未确认：保留会话与编辑器并呈现可重试状态，不弹假成功', async () => {
    mockFetch([makeFile(1), makeFile(2)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: true, document_key: 'k1'};
    store.pollIntervalMs = 1;
    store.pollMaxAttempts = 2;
    store.confirmSettleMs = 0;
    await flush();
    http.post.mockResolvedValue({forcesave: 'requested', revision: 1});
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: true});
      }
      if (url.endsWith('/draft/')) {
        return Promise.resolve({revision: 1}); // 修订号始终未推进（未落盘）
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1), makeFile(2)]);
      return Promise.resolve({id: 5, name: '测试手册'});
    });
    const btn = findButton(container, '保存并结束编辑');
    await act(async () => {
      click(btn);
      await new Promise(resolve => setTimeout(resolve, 30));
    });
    await flush();
    // 会话未被撤销（不得在未确认时销毁编辑态）
    expect(store.sessionKeyOf(1)).toBe('sess-1');
    expect(http.delete).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    // 界面呈现可重试状态（重试保存 / 不保存并退出）
    expect(container.textContent).toContain('保存未确认');
    expect(findButton(container, '重试保存')).not.toBeUndefined();
    expect(findButton(container, '不保存并退出')).not.toBeUndefined();
  });

  it('DS 报告无修改（no_changes）：无需等待直接结束会话', async () => {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: true, document_key: 'k1'};
    store.confirmSettleMs = 0;
    await flush();
    http.post.mockResolvedValue({forcesave: 'no_changes', revision: 1});
    http.delete.mockResolvedValue({});
    const btn = findButton(container, '保存并结束编辑');
    await act(async () => {
      click(btn);
      await Promise.resolve();
    });
    await flush();
    expect(store.sessionKeyOf(1)).toBe('');
    expect(successSpy).toHaveBeenCalledWith('已保存并结束编辑');
  });
});

describe('草稿工作台（固定快照交接状态与提交门控，2026-11-03）', () => {
  // 非所有者（仅编制授权）视角：is_mine 的有效负责人看不到「可直接纳入整套发布」
  const nonOwnerManual = {id: 5, name: '测试手册', owner_id: 9,
    my_roles: ['edit'], is_owner: false, is_admin: false};

  it('编制状态与详情页同一口径：待发布人核对/无需提交/待负责人提交待发布核对（relation=null 不把已发布无变化当成待提交）', async () => {
    mockFetch([
      makeFile(1, {submission: {status: 'pending', frozen: true,
        submitted_at: '2026-10-29T10:00:00', submitted_by_name: '我',
        submission_revision: 1, draft_revision: 1}}),
      // 已发布且无变化：revision_open=false、提交随发布被消费 → 无需提交
      makeFile(2, {revision_open: false}),
      // 修订轮开启、无提交、非本人有效负责 → 待负责人提交待发布核对
      makeFile(3, {assignment: {owner_id: 8, owner_name: '丙', note: '',
        is_mine: false, is_effective_owner: false, effective_owner_id: 8,
        effective_owner_name: '丙'}}),
    ], nonOwnerManual);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const text = container.textContent;
    expect(text).toContain('待发布人核对');
    expect(text).toContain('无需提交');
    expect(text).toContain('待负责人提交待发布核对');
    // 不存在"未提交"这个 label（"已发布无变化"绝不显示待提交/未提交）
    expect(text).not.toContain('未提交');
  });

  it('文件导航修订号改为次要信息（不再是醒目蓝色 rN Tag），状态 Tag 走共享口径', async () => {
    mockFetch([makeFile(1), makeFile(2)], nonOwnerManual);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const row = findListRows(container)[0];
    expect(row).not.toBeUndefined();
    // 内部修订号文本仍在（Tooltip/次要灰字），但不再作为 Tag 渲染
    expect(row.textContent).toContain('r1');
    const revisionTags = Array.from(row.querySelectorAll('.ant-tag'))
      .filter(t => /^r\d+$/.test((t.textContent || '').trim()));
    expect(revisionTags).toHaveLength(0);
    expect(row.textContent).toContain('待提交待发布核对');
  });

  it('编制中：文件有活跃编辑会话时状态 Tag=编制中，提交按钮禁用并提示先保存并结束编辑', async () => {
    mockFetch([makeFile(1)], nonOwnerManual);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: false};
    await flush();
    expect(container.textContent).toContain('编制中');
    const submitBtn = findButton(container, '提交待发布核对');
    expect(submitBtn).not.toBeUndefined();
    expect(submitBtn.disabled).toBe(true);
    http.post.mockClear();
    await act(async () => {
      click(submitBtn);
      await Promise.resolve();
    });
    await flush();
    expect(http.post).not.toHaveBeenCalled();
  });

  it('提交失效且修订轮开启 → 状态「提交已失效」+「重新提交」按钮（确认后 POST 并刷新红点）', async () => {
    mockFetch([makeFile(1, {revision_open: true,
      submission: {status: 'pending', state: 'stale',
        submitted_at: '2026-10-28T10:00:00', submitted_by_name: '我',
        submission_revision: 2, draft_revision: 3}})],
      nonOwnerManual);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('提交已失效（需重新提交）');
    const resubmitBtn = findButton(container, '重新提交');
    expect(resubmitBtn).not.toBeUndefined();
    expect(resubmitBtn.disabled).toBe(false);
    http.post.mockResolvedValue({});
    await act(async () => {
      click(resubmitBtn);
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    const okBtn = document.querySelector('.ant-modal-confirm .ant-btn-primary');
    expect(okBtn).not.toBeNull();
    await act(async () => {
      okBtn.click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/submit/', {});
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining('已提交待发布核对'));
    expect(institutionBadge.fetch).toHaveBeenCalled();
  });

  it('提交失效但修订轮已关闭（已发布消费提交后的兜底）→ 无需提交，不给重新提交入口', async () => {
    mockFetch([makeFile(1, {revision_open: false,
      submission: {status: 'pending', state: 'stale',
        submitted_at: '2026-10-28T10:00:00', submitted_by_name: '我',
        submission_revision: 2, draft_revision: 2}})],
      nonOwnerManual);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('无需提交');
    expect(container.textContent).not.toContain('提交已失效');
    expect(findButton(container, '重新提交')).toBeUndefined();
  });

  it('有效快照（待发布人核对）：不提供可点击提交按钮，内容冻结不渲染编辑器', async () => {
    mockFetch([makeFile(1, {revision_open: false,
      submission: {status: 'pending', frozen: true,
        submitted_at: '2026-10-29T10:00:00', submitted_by_name: '我',
        submission_revision: 1, draft_revision: 1,
        snapshot: {file_name: '文件1_快照.docx'},
        can_withdraw: true, can_return: false}})],
      nonOwnerManual);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const text = container.textContent;
    expect(text).toContain('待发布人核对');
    expect(text).toContain('已冻结');
    expect(text).toContain('内容已冻结');
    // 冻结：无编辑入口/草稿预览下载，改提供待核对快照动作与撤回
    expect(findButton(container, '开始编辑')).toBeUndefined();
    expect(findButton(container, '预览草稿')).toBeUndefined();
    expect(findButton(container, '下载草稿')).toBeUndefined();
    expect(findButton(container, '预览待核对快照')).not.toBeUndefined();
    expect(findButton(container, '下载待核对快照')).not.toBeUndefined();
    expect(findButton(container, '撤回提交')).not.toBeUndefined();
    http.post.mockClear();
    await act(async () => {
      click(findButton(container, '待发布人核对'));
      await Promise.resolve();
    });
    await flush();
    expect(http.post).not.toHaveBeenCalled();
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
  });

  it('冻结文件结构写入口禁用：改名/上移/下移/移除不可点击（不给必然被拒的入口）', async () => {
    mockFetch([makeFile(1, {revision_open: false,
      submission: {status: 'pending', frozen: true}}), makeFile(2)],
      {id: 5, name: '测试手册', owner_id: 9, my_roles: ['edit'],
        is_owner: true, is_admin: false});
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const disabledLabels = ['改名', '上移', '下移', '移除'];
    disabledLabels.forEach(label => {
      const btn = Array.from(container.querySelectorAll('button'))
        .find(b => b.textContent.replace(/\s+/g, '') === label);
      expect(btn).not.toBeUndefined();
      expect(btn.disabled).toBe(true);
    });
  });

  it('冻结文件预览待核对快照：走 submission/preview-url/，标题含提交人与时间', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('submission/preview-url')) {
        return Promise.resolve({preview_url: 'http://snapshot',
          file_name: '文件1_快照.docx', submitted_by_name: '张三',
          submitted_at: '2026-10-30T09:00:00'});
      }
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) {
        return Promise.resolve([makeFile(1, {revision_open: false,
          submission: {status: 'pending', frozen: true,
            submitted_by_name: '张三', submitted_at: '2026-10-30T09:00:00',
            snapshot: {file_name: '文件1_快照.docx'}}})]);
      }
      return Promise.resolve({id: 5, name: '测试手册', owner_id: 9,
        my_roles: ['edit'], is_owner: true, is_admin: false});
    });
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    await act(async () => {
      click(findButton(container, '预览待核对快照'));
      await Promise.resolve();
    });
    await flush();
    expect(pageInstance.state.preview).not.toBeNull();
    expect(pageInstance.state.preview.title).toBe(
      '预览待核对快照：文件1_快照.docx（提交人 张三，提交时间 2026-10-30 09:00:00）');
  });

  it('负责人兼发布权：状态「可直接纳入整套发布」，提交待发布核对只是可选动作（入口仍渲染）', async () => {
    mockFetch([makeFile(1)],
      {id: 5, name: '测试手册', owner_id: 9, my_roles: ['edit', 'publish'],
        is_owner: false, is_admin: false});
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('可直接纳入整套发布');
    // 可选动作仍可提交（有效负责人本人决定是否交给其他发布人核对快照）
    expect(findButton(container, '提交待发布核对')).not.toBeUndefined();
  });

  it('手册所有者但非该文件有效负责人：不渲染提交/重新提交（不得代提交）', async () => {
    mockFetch([
      makeFile(1, {assignment: {owner_id: 8, owner_name: '丙', note: '',
        is_mine: false, is_effective_owner: false, effective_owner_id: 8,
        effective_owner_name: '丙'},
        submission: {status: 'pending', state: 'stale',
          submitted_at: '2026-10-28T10:00:00', submitted_by_name: '丙',
          submission_revision: 2, draft_revision: 3}}),
    ]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(findButton(container, '提交待发布核对')).toBeUndefined();
    expect(findButton(container, '重新提交')).toBeUndefined();
    expect(findButton(container, '待发布人核对')).toBeUndefined();
  });

  it('预览标题不含 rN，明确是当前待发布草稿（不暗示提交时快照）', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('preview-url')) {
        return Promise.resolve({preview_url: 'http://preview', file_name: '文件1.docx'});
      }
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册', owner_id: 9,
        my_roles: ['edit'], is_owner: true, is_admin: false});
    });
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const previewBtn = findButton(container, '预览草稿');
    expect(previewBtn).not.toBeUndefined();
    await act(async () => {
      click(previewBtn);
      await Promise.resolve();
    });
    await flush();
    expect(pageInstance.state.preview).not.toBeNull();
    expect(pageInstance.state.preview.title).toBe('预览待发布草稿：文件1.docx');
    expect(pageInstance.state.preview.title).not.toContain('r1');
  });
});

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台（多文件）组件行为测试（jsdom + ReactDOM）：
 * - 多文件制度：左侧文件导航（名称/负责人/修订号/编辑占用/提交状态），
 *   右侧编辑区主体；单文件制度不渲染导航。
 * - 右侧顶部状态条：当前文件/修订号/独立的"制度草稿保存状态"（服务端
 *   确认落盘才显示"已保存到制度草稿：rN、时间"）/提交编制状态；
 *   流程按钮 开始编辑 → 保存并结束编辑 → 提交编制。
 * - 「保存并结束编辑」：降级路径直接撤销会话；在线路径经 forcesave +
 *   轮询确认落盘 + no_changes 复核后才撤销（成功/超时/失败三态）。
 * - 切换文件/返回详情的离开保护与保存状态显示的组件行为测试拆分至
 *   draft.workspace.leaveGuard.test.js（文件行数门禁，只减不增）。
 * - 负责人持有编辑会话时提交编制禁用（先保存并结束编辑）。
 * - 密码门验证成功=第一份有草稿文件的会话建立并进入工作区；本地恢复
 *   会话时跳过密码门；?file= 深链目标不可用时给出明确状态。
 * - 保存失败错误含"会话"时清除该文件会话且不重复弹错（HTTP 拦截器已
 *   提示，业务代码不得再 message.error，也不得弹假成功）。
 * - 新增文件 draft_error 非空（文件已创建但草稿未就绪）只警示不算失败。
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

import InstitutionDraftWorkspace from '../draft';
import {http} from 'libs';
import store from '../draft/store';

function makeFile(id, overrides) {
  return Object.assign({
    id,
    manual_id: 5,
    name: `文件${id}`,
    sort_order: id,
    is_removed: false,
    created_at: '2026-10-01T10:00:00',
    originals_count: 1,
    draft: {
      id: 100 + id,
      revision: id,
      file_name: `文件${id}.docx`,
      file_size: 1024,
      file_hash: `hash-${id}`,
      base_version_id: null,
      source_original_id: null,
      last_saved_by_name: '张三',
      last_saved_at: '2026-10-01T10:00:00',
      created_at: '2026-10-01T10:00:00',
    },
    active_session: null,
  }, overrides);
}

function mockFetch(files, manual) {
  http.get.mockImplementation(url => {
    if (url.includes('editor-config')) {
      return Promise.resolve({editor_available: false});
    }
    if (url.includes('/files/')) return Promise.resolve(files);
    return Promise.resolve(manual || {id: 5, name: '测试手册', my_roles: ['edit']});
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
    // 第二个隐藏 input 为保存上传控件（第一个是新增文件控件）
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

  it('新增文件 draft_error 非空时警示不算失败并刷新清单', async () => {
    mockFetch([makeFile(1)]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const addInput = findFileInputs(container)[0];
    const created = {id: 2, name: '新文件', sort_order: 2, draft: null, active_session: null};
    http.post.mockResolvedValue(Object.assign(
      {draft_error: '文件已创建，但可编辑草稿建立失败：格式转换失败'}, created));
    http.get.mockImplementation(url => {
      if (url.includes('editor-config')) {
        return Promise.resolve({editor_available: false});
      }
      if (url.includes('/files/')) return Promise.resolve([makeFile(1), created]);
      return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit']});
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
    expect(http.post).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/create/', expect.any(FormData));
    expect(warningSpy).toHaveBeenCalledWith(expect.stringContaining('草稿建立失败'));
    expect(errorSpy).not.toHaveBeenCalled();
    expect(successSpy).not.toHaveBeenCalled();
    expect(store.files).toHaveLength(2);
    expect(container.textContent).toContain('待发布文件（共 2 份）');
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

  it('新增文件候选加载失败：弹窗内展示错误与重试（请求抑制拦截器弹错）', async () => {
    http.get.mockImplementation(url => {
      if (url.includes('assignment-owners')) return Promise.reject('权限拒绝');
      if (url.includes('/files/')) return Promise.resolve([makeFile(1)]);
      return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit']});
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
      return Promise.resolve({id: 5, name: '测试手册', my_roles: ['edit']});
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

describe('草稿工作台（文件分工展示与提交编制）', () => {
  it('清单行显示负责人/未分配，选中文件卡展示负责人与分工说明', async () => {
    mockFetch([
      makeFile(1, {assignment: {owner_id: 9, owner_name: '乙', note: '负责正文',
        is_mine: false}}),
      makeFile(2),
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

  it('负责人（is_mine）可提交编制：确认后 POST submit 并刷新清单', async () => {
    mockFetch([makeFile(1, {assignment: {owner_id: 9, owner_name: '我',
      note: '', is_mine: true}})]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    const submitBtn = findButton(container, '提交编制');
    expect(submitBtn).not.toBeUndefined();
    http.post.mockResolvedValue({});
    await act(async () => {
      click(submitBtn);
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
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining('已提交编制'));
  });

  it('非负责人行不渲染提交编制按钮', async () => {
    mockFetch([makeFile(1, {assignment: {owner_id: 8, owner_name: '丙',
      note: '', is_mine: false}})]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(findButton(container, '提交编制')).toBeUndefined();
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
    expect(http.post).not.toHaveBeenCalled();
    expect(http.delete).toHaveBeenCalledWith(
      '/api/institution/manuals/5/files/1/draft/session/',
      {data: {session_key: 'sess-1'}});
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
      {data: {session_key: 'sess-1'}});
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

describe('草稿工作台（提交状态与会话互斥）', () => {
  it('导航展示提交编制状态（已提交/提交已失效/未提交）', async () => {
    mockFetch([
      makeFile(1, {submission: {state: 'submitted', submitted_at:
        '2026-10-29T10:00:00', submitted_by_name: '我', submission_revision: 1,
        draft_revision: 1}}),
      makeFile(2, {submission: {state: 'stale', submitted_at:
        '2026-10-28T10:00:00', submitted_by_name: '我', submission_revision: 2,
        draft_revision: 3}}),
    ]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    await flush();
    expect(container.textContent).toContain('已提交');
    expect(container.textContent).toContain('提交已失效');
  });

  it('负责人持有该文件编辑会话时提交编制禁用（先保存并结束编辑）', async () => {
    mockFetch([makeFile(1, {assignment: {owner_id: 9, owner_name: '我',
      note: '', is_mine: true}})]);
    const container = renderPage();
    await flush();
    store.passwordVerified = true;
    store.saveSession(1, 'sess-1', '2099-01-01T00:00:00');
    store.editorConfigs[1] = {editor_available: false};
    await flush();
    const submitBtn = findButton(container, '提交编制');
    expect(submitBtn).not.toBeUndefined();
    expect(submitBtn.disabled).toBe(true);
    // 顶部状态条仍展示负责人视角的提交状态位（服务端 submission 缺省=未提交不渲染）
    http.post.mockClear();
    await act(async () => {
      click(submitBtn);
      await Promise.resolve();
    });
    await flush();
    expect(http.post).not.toHaveBeenCalled();
  });
});

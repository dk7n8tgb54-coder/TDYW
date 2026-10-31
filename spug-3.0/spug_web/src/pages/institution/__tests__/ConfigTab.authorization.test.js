/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 权限配置页签行为测试（2026-10-31 授权模型改造，替代旧「角色关联」配置）：
 * - 手册所有者卡：admin 可指定/接管/移交（Modal.confirm 明确语义 →
 *   POST owner/）；owner 只读展示；ownerCandidates 仅 admin 请求。
 * - 账号授权卡（AuthorizationCard）：仅 owner/admin 渲染与读写；挂载即
 *   拉授权清单与账号候选；行=账号名+查看/编制/发布 Checkbox+行删除；
 *   「添加账号」从候选追加行；「保存授权」整体替换（PUT authorizations，
 *   items 全量 + 卡内「编制授权者可查看发布版」Switch）；保存成功提示
 *   含 revoked_sessions 追加说明；清单/候选失败在卡片内展示错误+重试
 *   （候选请求抑制拦截器弹错，错误只展示一次）。
 * - 编辑密码卡：仅持 config 权限码渲染表单；owner/admin 无 config 码时
 *   显示说明文案；仅持 config 码（非 owner/admin）不渲染授权卡操作。
 * - 页签可见性（config 码 或 is_owner 或 is_admin）钉死在
 *   detail.index.tabs.test.js。
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
      owner_id: 5, owner_name: '王五', is_owner: true, is_admin: false,
      has_password: true, password_updated_at: '2026-10-01T08:00:00'};
    @observable authorizations = null;
    @observable isFetchingAuthorizations = false;
    @observable authorizationsError = '';
    @observable accountOptions = [];
    @observable accountOptionsError = '';
    @observable ownerCandidates = [];
    @observable ownerCandidatesError = '';
    fetchAuthorizations = jest.fn(function () {
      this.authorizations = {
        items: [
          {account_id: 11, account_name: '张三', can_view: true,
            can_edit: true, can_publish: false},
          {account_id: 12, account_name: '李四', can_view: true,
            can_edit: false, can_publish: true},
        ],
        editor_can_view_published: true,
      };
      return Promise.resolve();
    });
    fetchAccountOptions = jest.fn(function () {
      this.accountOptions = [
        {id: 11, name: '张三'}, {id: 12, name: '李四'}, {id: 13, name: '王五'},
      ];
      return Promise.resolve();
    });
    fetchOwnerCandidates = jest.fn(function () {
      this.ownerCandidates = [{id: 13, name: '王五'}, {id: 14, name: '赵六'}];
      return Promise.resolve();
    });
    saveAuthorizations = jest.fn(function (id, items, editorVisible) {
      return Promise.resolve({
        items: items.map(x => ({account_name: `账号${x.account_id}`, ...x})),
        editor_can_view_published: editorVisible,
        revoked_sessions: 0,
      });
    });
    setManualOwner = jest.fn(function (id, accountId) {
      this.manual = {...this.manual, owner_id: accountId,
        owner_name: accountId === 14 ? '赵六' : this.manual.owner_name};
      return Promise.resolve({...this.manual});
    });
    fetchDetail = jest.fn(function () { return Promise.resolve(); });
  }
  return new DetailStore();
});

import ConfigTab from '../detail/ConfigTab';
import store from '../detail/store';
import {message} from 'antd';
import {hasPermission} from 'libs';

let container = null;

beforeEach(() => {
  jest.clearAllMocks();
  // clearAllMocks 不恢复 mockImplementation：默认成功路径逐用例前复位
  store.fetchAuthorizations.mockImplementation(function () {
    this.authorizations = {
      items: [
        {account_id: 11, account_name: '张三', can_view: true,
          can_edit: true, can_publish: false},
        {account_id: 12, account_name: '李四', can_view: true,
          can_edit: false, can_publish: true},
      ],
      editor_can_view_published: true,
    };
    return Promise.resolve();
  });
  store.fetchAccountOptions.mockImplementation(function () {
    this.accountOptions = [
      {id: 11, name: '张三'}, {id: 12, name: '李四'}, {id: 13, name: '王五'},
    ];
    return Promise.resolve();
  });
  store.fetchOwnerCandidates.mockImplementation(function () {
    this.ownerCandidates = [{id: 13, name: '王五'}, {id: 14, name: '赵六'}];
    return Promise.resolve();
  });
  store.saveAuthorizations.mockImplementation(function (id, items, ev) {
    return Promise.resolve({
      items: items.map(x => ({account_name: `账号${x.account_id}`, ...x})),
      editor_can_view_published: ev, revoked_sessions: 0,
    });
  });
  store.setManualOwner.mockImplementation(function (id, accountId) {
    this.manual = {...this.manual, owner_id: accountId};
    return Promise.resolve({...this.manual});
  });
  store.manual = {id: 7, name: '科室操作手册', status: 'active',
    owner_id: 5, owner_name: '王五', is_owner: true, is_admin: false,
    has_password: true, password_updated_at: '2026-10-01T08:00:00'};
  store.authorizations = null;
  store.authorizationsError = '';
  store.accountOptions = [];
  store.accountOptionsError = '';
  store.ownerCandidates = [];
  store.ownerCandidatesError = '';
  hasPermission.mockImplementation(() => true);
  container = document.createElement('div');
  document.body.appendChild(container);
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

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

function renderTab() {
  act(() => {
    ReactDOM.render(<ConfigTab/>, container);
  });
}

function findButton(root, text) {
  return Array.from(root.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes(text));
}

/** 在账号授权卡内按账号名定位行（断言与操作都以真实渲染为准） */
function authRow(root, accountName) {
  return Array.from(root.querySelectorAll('.ant-table-tbody tr'))
    .find(tr => tr.textContent.includes(accountName));
}

/** 按卡片标题定位 Card（避免与卡片正文说明文案误匹配） */
function findCard(root, titleText) {
  return Array.from(root.querySelectorAll('.ant-card'))
    .find(c => {
      const title = c.querySelector('.ant-card-head-title');
      return title && title.textContent.includes(titleText);
    });
}

describe('权限配置页签（手册所有者卡）', () => {
  it('显示所有者账号；非 admin 的所有者只读（无候选请求与移交操作）', async () => {
    renderTab();
    await flush();
    const ownerCard = findCard(container, '手册所有者');
    expect(ownerCard.textContent).toContain('王五');
    expect(store.fetchOwnerCandidates).not.toHaveBeenCalled();
    expect(findButton(ownerCard, '移交')).toBeUndefined();
    expect(findButton(ownerCard, '指定所有者')).toBeUndefined();
    // 所有者提示移交须由管理员操作
    expect(ownerCard.textContent).toContain('移交所有者须由制度管理员操作');
  });

  it('无主手册（owner_name 空）显示「未指定」', async () => {
    store.manual = {...store.manual, owner_id: null, owner_name: ''};
    renderTab();
    await flush();
    const ownerCard = findCard(container, '手册所有者');
    expect(ownerCard.textContent).toContain('未指定');
  });

  it('admin 渲染候选下拉与「移交 / 接管」，未选账号时拦截不发请求', async () => {
    store.manual = {...store.manual, is_owner: false, is_admin: true};
    renderTab();
    await flush();
    expect(store.fetchOwnerCandidates).toHaveBeenCalledWith(7);
    const ownerCard = findCard(container, '手册所有者');
    const btn = findButton(ownerCard, '移交');
    expect(btn).not.toBeUndefined();
    await act(async () => {
      btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    // 未选择账号时拦截并提示（不发请求）
    expect(message.warning).toHaveBeenCalledWith('请先选择新的所有者账号');
    expect(store.setManualOwner).not.toHaveBeenCalled();
  });

  it('admin 选择候选后经确认窗移交：确认说明接管/移交语义并调用 setManualOwner', async () => {
    store.manual = {...store.manual, is_owner: false, is_admin: true};
    renderTab();
    await flush();
    const ownerCard = findCard(container, '手册所有者');
    await pickSelectOption(ownerCard, '赵六');
    await act(async () => {
      findButton(ownerCard, '移交').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
      await new Promise(resolve => setTimeout(resolve, 0));
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    const confirm = document.querySelector('.ant-modal-confirm');
    expect(confirm).not.toBeNull();
    // 确认窗明确语义：所有者职责 + 身份不自动给编辑/发布权/可见发布版
    expect(confirm.textContent).toContain('赵六');
    expect(confirm.textContent).toContain('所有者身份不自动获得');
    store.setManualOwner.mockResolvedValueOnce({...store.manual});
    await act(async () => {
      confirm.querySelector('.ant-btn-primary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.setManualOwner).toHaveBeenCalledWith(7, 14);
    expect(message.success).toHaveBeenCalledWith('手册所有者已更新');
  });
});

describe('权限配置页签（账号授权卡）', () => {
  it('owner/admin 挂载即拉授权清单与账号候选；行渲染三授权位', async () => {
    renderTab();
    await flush();
    expect(store.fetchAuthorizations).toHaveBeenCalledWith(7);
    expect(store.fetchAccountOptions).toHaveBeenCalledWith(7);
    const row11 = authRow(container, '张三');
    expect(row11).not.toBeUndefined();
    // 张三：查看+编制勾选、发布未勾选
    const checks = row11.querySelectorAll('input[type="checkbox"]');
    expect(checks.length).toBe(3);
    expect(checks[0].checked).toBe(true);
    expect(checks[1].checked).toBe(true);
    expect(checks[2].checked).toBe(false);
  });

  it('切换授权位与删除行后保存：PUT 载荷为全量 items + editor_can_view_published', async () => {
    renderTab();
    await flush();
    // 取消张三的编制（第 2 个勾选框）
    const row = authRow(container, '张三');
    await act(async () => {
      row.querySelectorAll('input[type="checkbox"]')[1].click();
    });
    // 删除李四行
    const row12 = authRow(container, '李四');
    await act(async () => {
      row12.querySelector('button').click();
    });
    await act(async () => {
      findButton(container, '保存授权').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(store.saveAuthorizations).toHaveBeenCalledWith(7, [
      {account_id: 11, can_view: true, can_edit: false, can_publish: false},
    ], true);
    expect(message.success).toHaveBeenCalledWith('授权已保存');
  });

  it('保存成功 revoked_sessions>0 时追加撤销会话说明', async () => {
    renderTab();
    await flush();
    store.saveAuthorizations.mockImplementationOnce(() => Promise.resolve({
      items: [], editor_can_view_published: true, revoked_sessions: 2,
    }));
    await act(async () => {
      findButton(container, '保存授权').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    expect(message.success).toHaveBeenCalledWith(
      '授权已保存；已撤销 2 个进行中的编辑会话');
  });

  it('「编制授权者可查看发布版」Switch 取自服务端值并随保存提交', async () => {
    renderTab();
    await flush();
    const card = findCard(container, '账号授权');
    const sw = card.querySelector('.ant-switch');
    expect(sw).not.toBeNull();
    expect(sw.className).toContain('ant-switch-checked');
    await act(async () => {
      sw.click();
    });
    await act(async () => {
      findButton(container, '保存授权').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    await flush();
    const payload = store.saveAuthorizations.mock.calls[0];
    expect(payload[2]).toBe(false);
  });
});

describe('权限配置页签（账号增删与失败态）', () => {
  it('添加账号：从候选选择后追加一行（默认勾选查看），已授权账号不再出现在候选', async () => {
    renderTab();
    await flush();
    const card = findCard(container, '账号授权');
    // 已有张三/李四：候选下拉应过滤已授权账号（王五可选）
    await pickSelectOption(card, '王五');
    await act(async () => {
      findButton(card, '添加账号').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    const newRow = authRow(container, '王五');
    expect(newRow).not.toBeUndefined();
    const checks = newRow.querySelectorAll('input[type="checkbox"]');
    expect(checks[0].checked).toBe(true);
    expect(checks[1].checked).toBe(false);
    // 已授权账号从候选下拉过滤（重复授权在入口即不可达）
    const select = card.querySelector('.ant-select');
    await act(async () => {
      const selector = select.querySelector('.ant-select-selector') || select;
      selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    const options = Array.from(
      document.querySelectorAll('.ant-select-dropdown .ant-select-item-option'))
      .map(o => o.textContent);
    expect(options.some(t => t.includes('王五'))).toBe(false);
    // 未选择账号直接点添加：拦截提示，不追加空行
    await act(async () => {
      findButton(card, '添加账号').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    expect(message.warning).toHaveBeenCalledWith('请先选择要添加的账号');
    expect(container.querySelectorAll('.ant-table-tbody tr').length).toBe(3);
  });

  it('授权清单加载失败：卡片内错误+重试，不以空清单冒充成功', async () => {
    store.fetchAuthorizations.mockImplementationOnce(function () {
      this.authorizations = null;
      this.authorizationsError = '授权清单加载失败，请重试';
      return Promise.resolve();
    });
    renderTab();
    await flush();
    expect(container.textContent).toContain('授权清单加载失败');
    const retry = findButton(container, '重试');
    await act(async () => {
      retry.click();
    });
    expect(store.fetchAuthorizations).toHaveBeenCalledTimes(2);
  });

  it('账号候选加载失败：卡片内错误+重试（请求抑制拦截器弹错，错误只展示一次）', async () => {
    store.fetchAccountOptions.mockImplementationOnce(function () {
      this.accountOptions = [];
      this.accountOptionsError = '权限拒绝';
      return Promise.resolve();
    });
    renderTab();
    await flush();
    expect(container.textContent).toContain('账号候选加载失败');
    expect(container.textContent).toContain('权限拒绝');
    const retry = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent.replace(/\s+/g, '') === '重试');
    expect(retry.length).toBeGreaterThanOrEqual(1);
    await act(async () => {
      retry[retry.length - 1].click();
    });
    expect(store.fetchAccountOptions).toHaveBeenCalledTimes(2);
  });
});

describe('权限配置页签（按身份收窄）', () => {
  it('仅持 config 码（非 owner/admin）：不渲染账号授权卡操作，显示说明文案', async () => {
    store.manual = {...store.manual, is_owner: false, is_admin: false,
      owner_id: 99, owner_name: '别人'};
    hasPermission.mockImplementation(
      code => code === 'institution.manual.view' ||
        code === 'institution.manual.config');
    renderTab();
    await flush();
    // config-only 也非 admin：授权卡不挂载、不发请求
    expect(store.fetchAuthorizations).not.toHaveBeenCalled();
    expect(store.fetchAccountOptions).not.toHaveBeenCalled();
    expect(store.fetchOwnerCandidates).not.toHaveBeenCalled();
    expect(container.textContent).toContain('由手册所有者或制度管理员维护');
    // 密码卡对 config 码账号可维护（表单渲染）
    expect(container.querySelector('input[type="password"]')).not.toBeNull();
  });

  it('owner/admin 无 config 码：授权卡可读写，密码卡只读并说明维护方', async () => {
    hasPermission.mockImplementation(code => code === 'institution.manual.view');
    renderTab();
    await flush();
    expect(store.fetchAuthorizations).toHaveBeenCalled();
    // 密码表单不渲染
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(container.textContent).toContain('密码由持配置权限的账号维护');
  });

  it('admin（is_admin）挂载 owner 候选请求；owner（非 admin）不请求', async () => {
    store.manual = {...store.manual, is_owner: false, is_admin: true};
    renderTab();
    await flush();
    expect(store.fetchOwnerCandidates).toHaveBeenCalledWith(7);
    ReactDOM.unmountComponentAtNode(container);
    container = document.createElement('div');
    document.body.appendChild(container);
    store.fetchOwnerCandidates.mockClear();
    store.manual = {...store.manual, is_owner: true, is_admin: false};
    renderTab();
    await flush();
    expect(store.fetchOwnerCandidates).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// antd Select 交互助手（rc-select 下拉经 portal 渲染到 document.body）

/** 打开 Select 并点击指定文本的选项 */
async function pickSelectOption(scope, optionText) {
  const select = scope.querySelector('.ant-select');
  expect(select).not.toBeNull();
  await act(async () => {
    const selector = select.querySelector('.ant-select-selector') || select;
    selector.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  const option = Array.from(
    document.querySelectorAll('.ant-select-dropdown .ant-select-item-option'))
    .find(o => o.textContent.includes(optionText));
  expect(option).not.toBeUndefined();
  await act(async () => {
    option.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await new Promise(resolve => setTimeout(resolve, 0));
  });
}

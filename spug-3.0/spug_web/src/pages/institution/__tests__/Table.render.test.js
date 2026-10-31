/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 制度列表渲染测试（2026-10-29 交互优化新增"工作状态"列）：
 * work_status 由服务端按 草稿哈希 vs 生效快照 与文件增删/改名/排序
 * 计算，前端只做文案映射；仅查看角色 work_status=null 显示 '-'。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

// jsdom 垫片（antd 4 需要）
window.matchMedia = window.matchMedia || function () {
  return {matches: false, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}};
};

jest.mock('libs', () => ({
  http: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
  history: {push: jest.fn()},
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: false, permissions: []},
}));

jest.mock('../store', () => {
  const {observable, action} = require('mobx');
  class Store {
    @observable records = [];
    @observable isFetching = false;
    @observable total = 0;
    @observable pageNum = 1;
    @observable pageSize = 20;
    @observable formVisible = false;
    @observable categoryVisible = false;
    @observable record = {};
    @observable categories = [];
    @observable f_keyword;
    @observable f_category_id;
    @observable f_org_type;
    @observable f_status;
    @action.bound fetchRecords() { return Promise.resolve(); }
    @action.bound fetchCategories() { return Promise.resolve(); }
    @action.bound setPage() {}
    @action.bound showForm(record) { this.record = record || {}; this.formVisible = true; }
    @action.bound showCategories() { this.categoryVisible = true; }
  }
  return new Store();
});

const {history, hasPermission} = require('libs');
const store = require('../store');

// 默认：仅持有查看/下载/删除权限（无 edit/config），角色判定交给行数据 my_roles
function grantViewOnly() {
  hasPermission.mockImplementation(code =>
    !code || ['institution.manual.view', 'institution.manual.download',
      'institution.manual.delete'].includes(code));
}
function grantManager() {
  hasPermission.mockReturnValue(true);
}

function makeRecord(over = {}) {
  return Object.assign({
    id: 1, name: '部门管理手册', code: 'GL-001', category_name: '部门手册',
    // 2026-10-31 授权模型：归属字段 org_*（原 owner_* 更名），
    // 所有者账号字段 owner_name + is_owner/is_admin 同时下发
    org_type: 'department', org_type_display: '部门', org_name: '某部门',
    owner_id: 5, owner_name: '王五', is_owner: false, is_admin: false,
    status: 'active',
    status_display: '启用', my_roles: ['view'], current_version: {
      id: 9, version_no: 2, published_at: '2026-10-27T10:00:00', published_by_name: '张',
    },
  }, over);
}

describe('institution Table', () => {
  let container;
  let ComTable;
  beforeAll(() => {
    ComTable = require('../Table').default;
  });
  beforeEach(() => {
    jest.clearAllMocks();
    grantViewOnly();
    store.records = [];
    store.isFetching = false;
    container = document.createElement('div');
    document.body.appendChild(container);
  });
  afterEach(() => {
    ReactDOM.unmountComponentAtNode(container);
    container.remove();
  });

  function renderTable() {
    act(() => {
      ReactDOM.render(<ComTable/>, container);
    });
  }

  it('渲染行数据：名称/编号/归属/所有者/当前生效版本', () => {
    store.records = [makeRecord()];
    renderTable();
    const text = container.textContent;
    expect(text).toContain('部门管理手册');
    expect(text).toContain('GL-001');
    expect(text).toContain('v2');
    // 归属列 = org_type_display · org_name（原 owner_* 更名）
    expect(text).toContain('部门 · 某部门');
    // 所有者列 = 手册所有者账号名
    expect(text).toContain('王五');
  });

  it('所有者列：未指定时以橙色 Tag 提示（便于管理员发现无主手册）', () => {
    store.records = [
      makeRecord({id: 41, name: '甲册', owner_id: null, owner_name: ''}),
      makeRecord({id: 42, name: '乙册'}),
    ];
    renderTable();
    const rows = Array.from(container.querySelectorAll('.ant-table-row'));
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('未指定');
    expect(rows[0].textContent).not.toContain('王五');
    expect(rows[1].textContent).toContain('王五');
    expect(rows[0].querySelector('.ant-tag-orange')).not.toBeNull();
  });

  it('已发布手册删除禁用（提示用归档），未发布可删除', () => {
    store.records = [
      makeRecord(),
      makeRecord({id: 2, name: '草稿手册', current_version: null}),
    ];
    renderTable();
    const buttons = Array.from(container.querySelectorAll('button'));
    const deleteButtons = buttons.filter(b => b.textContent.includes('删除'));
    expect(deleteButtons.length).toBe(2);
    expect(deleteButtons[0].disabled).toBe(true);
    expect(deleteButtons[1].disabled).toBe(false);
  });

  it('纯查看角色不显示草稿入口；持编制角色显示', () => {
    store.records = [makeRecord({id: 3, my_roles: ['view']})];
    renderTable();
    expect(container.textContent).not.toContain('草稿');
    ReactDOM.unmountComponentAtNode(container);
    store.records = [makeRecord({id: 3, my_roles: ['view', 'edit']})];
    renderTable();
    expect(container.textContent).toContain('草稿');
  });

  it('点击名称跳转手册详情路由', () => {
    store.records = [makeRecord()];
    renderTable();
    const link = Array.from(container.querySelectorAll('a'))
      .find(a => a.textContent === '部门管理手册');
    act(() => {
      link.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(history.push).toHaveBeenCalledWith('/institution/manuals/1');
  });

  it('管理者可见类别管理与新建按钮（权限按钮）', () => {
    grantManager();
    store.records = [];
    renderTable();
    expect(container.textContent).toContain('新建手册');
    expect(container.textContent).toContain('类别管理');
  });

  it('纯查看者不显示新建手册按钮', () => {
    store.records = [];
    renderTable();
    expect(container.textContent).not.toContain('新建手册');
  });
});

// 工作状态列测试（拆分为两个 describe 共用）：组件/容器/渲染助手
// 提升到模块层，两个 describe 各自 beforeEach 重建容器
const TableComp = require('../Table').default;
let wsContainer = null;

function resetWorkStatusTable() {
  jest.clearAllMocks();
  grantViewOnly();
  store.records = [];
  store.isFetching = false;
  wsContainer = document.createElement('div');
  document.body.appendChild(wsContainer);
}

function cleanupWorkStatusTable() {
  if (wsContainer) {
    ReactDOM.unmountComponentAtNode(wsContainer);
    wsContainer.remove();
    wsContainer = null;
  }
}

function renderWith(record) {
  store.records = [makeRecord(record)];
  act(() => {
    ReactDOM.render(<TableComp/>, wsContainer);
  });
  return wsContainer.textContent;
}

describe('institution Table 工作状态列', () => {
  beforeEach(resetWorkStatusTable);
  afterEach(cleanupWorkStatusTable);

  it('已生效：显示"已生效"+ 版本号无未发布修改', () => {
    const text = renderWith({id: 21, my_roles: ['publish'], work_status: {
      status: 'synced', total_files: 2, modified: 0, added: 0, removed: 0,
      renamed: 0, reordered: false, no_draft: 0, unconfirmed: 0,
      revising: 0,
      session_busy: 0, has_current_version: true, current_version_no: 3,
      has_pending_changes: false, determinable: true, consistent: true}});
    expect(text).toContain('已生效');
    expect(text).toContain('v3 无未发布修改');
  });

  it('修订进行中：修订开启但暂无待发布变化，独立呈现', () => {
    const text = renderWith({id: 29, my_roles: ['edit'], work_status: {
      status: 'revising', total_files: 2, modified: 0, added: 0, removed: 0,
      renamed: 0, reordered: false, no_draft: 0, unconfirmed: 0, revising: 1,
      session_busy: 0, has_current_version: true, current_version_no: 3,
      has_pending_changes: false, determinable: true, consistent: false}});
    expect(text).toContain('修订进行中');
    expect(text).toContain('1 份修订进行中（暂无待发布变化）');
    expect(text).not.toContain('已生效');
  });

  it('待发布变化：显示统计明细（修改/新增/移除）', () => {
    const text = renderWith({id: 22, my_roles: ['publish'], work_status: {
      status: 'pending_changes', total_files: 3, modified: 2, added: 1,
      removed: 1, renamed: 0, reordered: false, no_draft: 0, unconfirmed: 0,
      revising: 0,
      session_busy: 0, has_current_version: true, current_version_no: 3,
      has_pending_changes: true, determinable: true, consistent: false}});
    expect(text).toContain('待发布变化');
    expect(text).toContain('2 份修改');
    expect(text).toContain('1 份新增');
    expect(text).toContain('1 份移除');
    expect(text).not.toContain('已生效');
  });
});

describe('institution Table 工作状态列（异常态）', () => {
  beforeEach(resetWorkStatusTable);
  afterEach(cleanupWorkStatusTable);

  it('编辑中 / 缺少草稿 / 状态无法确认 / 待首次发布 / 未上传文件', () => {
    expect(renderWith({id: 23, my_roles: ['edit'], work_status: {
      status: 'editing', total_files: 2, modified: 0, added: 0, removed: 0,
      renamed: 0, reordered: false, no_draft: 0, unconfirmed: 1,
      session_busy: 1, has_current_version: true, current_version_no: 2,
      has_pending_changes: false, determinable: false, consistent: false}}))
      .toContain('1 份编辑中（暂不能确认）');
    expect(renderWith({id: 24, my_roles: ['edit'], work_status: {
      status: 'missing_draft', total_files: 2, no_draft: 1, unconfirmed: 0,
      session_busy: 0, has_current_version: true, current_version_no: 2,
      has_pending_changes: false, determinable: true, consistent: false}}))
      .toContain('1 份缺草稿');
    expect(renderWith({id: 25, my_roles: ['edit'], work_status: {
      status: 'unverifiable', total_files: 2, no_draft: 0, unconfirmed: 1,
      session_busy: 0, has_current_version: true, current_version_no: 2,
      has_pending_changes: false, determinable: false, consistent: false}}))
      .toContain('1 份暂不能确认');
    expect(renderWith({id: 26, my_roles: ['edit'], work_status: {
      status: 'awaiting_first_publish', total_files: 2, no_draft: 0,
      unconfirmed: 0, session_busy: 0, has_current_version: false,
      current_version_no: null, has_pending_changes: true,
      determinable: true, consistent: false}}))
      .toContain('2 份文件待发布');
    expect(renderWith({id: 27, my_roles: ['edit'], work_status: {
      status: 'no_files', total_files: 0, no_draft: 0, unconfirmed: 0,
      session_busy: 0, has_current_version: false, current_version_no: null,
      has_pending_changes: false, determinable: true, consistent: false}}))
      .toContain('未上传文件');
  });

  it('仅查看角色 work_status=null 显示 -，不出现任何草稿状态语义', () => {
    const text = renderWith({id: 28, my_roles: ['view'], work_status: null});
    expect(text).toContain('部门管理手册');
    expect(text).not.toContain('已生效');
    expect(text).not.toContain('待发布变化');
    expect(text).not.toContain('编辑中');
  });

  it('工作状态列不泄露给无草稿访问权的行（含统计明细）', () => {
    // 同页两行：管理者行有状态，查看行无状态
    store.records = [
      makeRecord({id: 31, name: '甲册', my_roles: ['publish'], work_status: {
        status: 'pending_changes', total_files: 2, modified: 1, added: 0,
        removed: 0, renamed: 0, reordered: false, no_draft: 0, unconfirmed: 0,
        session_busy: 0, has_current_version: true, current_version_no: 1,
        has_pending_changes: true, determinable: true, consistent: false}}),
      makeRecord({id: 32, name: '乙册', my_roles: ['view'], work_status: null}),
    ];
    act(() => {
      ReactDOM.render(<TableComp/>, wsContainer);
    });
    const rows = Array.from(wsContainer.querySelectorAll('.ant-table-row'));
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('待发布变化');
    expect(rows[0].textContent).toContain('1 份修改');
    expect(rows[1].textContent).not.toContain('待发布变化');
  });
});

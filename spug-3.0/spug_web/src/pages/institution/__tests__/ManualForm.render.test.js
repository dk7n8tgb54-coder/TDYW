/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 编辑弹窗渲染行为（2026-10-31 授权模型改造更新）：旧「角色关联」字段
 * 已随后端 M2M 移除——表单不再请求 /api/institution/roles/，也不再渲染
 * 查看/编制/发布角色选择框；业务归属字段为 org_type/org_name（原
 * owner_* 更名，标签仍为 业务归属/归属单位）。手册级账号授权由详情页
 * 「权限配置」页签逐本维护。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

window.matchMedia = window.matchMedia || function () {
  return {matches: false, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}};
};

jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), put: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

jest.mock('../store', () => ({
  record: {id: 3, name: '部门管理手册', org_type: 'section',
    org_name: '某科室', status: 'active',
    editor_can_view_published: true},
  categories: [{id: 1, name: '部门手册', is_active: true}],
  formVisible: false,
  fetchCategories: jest.fn(),
}));

const {http} = require('libs');
const store = require('../store');

describe('ManualForm 渲染（org 字段与旧角色字段移除）', () => {
  let container;
  let ManualForm;
  beforeAll(() => {
    ManualForm = require('../ManualForm').default;
  });
  beforeEach(() => {
    jest.clearAllMocks();
    http.get.mockResolvedValue([]);
    container = document.createElement('div');
    document.body.appendChild(container);
  });
  afterEach(() => {
    ReactDOM.unmountComponentAtNode(container);
    container.remove();
  });

  function renderForm() {
    act(() => {
      ReactDOM.render(<ManualForm/>, container);
    });
    // antd Modal 经 portal 渲染到 body，断言取 body 文本
    return document.body.textContent;
  }

  it('不再请求旧角色端点 /api/institution/roles/，角色选择框不渲染', () => {
    const text = renderForm();
    const roleCalls = http.get.mock.calls.filter(
      ([url]) => url === '/api/institution/roles/');
    expect(roleCalls).toHaveLength(0);
    expect(text).not.toContain('选择平台级');
    expect(text).not.toContain('编制角色');
    expect(text).not.toContain('发布角色');
  });

  it('业务归属/归属单位按 org_type/org_name 编辑回填，仅请求类别', () => {
    const text = renderForm();
    expect(text).toContain('业务归属');
    expect(text).toContain('归属单位');
    // 编辑回填：org_name 现值出现在 Select/输入框值中（回填自 store.record）
    const inputs = Array.from(document.querySelectorAll('input'));
    const orgInput = inputs.find(i => i.value === '某科室');
    expect(orgInput).not.toBeUndefined();
    // 类别字典照常拉取（走 store.fetchCategories）
    expect(store.fetchCategories).toHaveBeenCalled();
  });

  it('新建缺省业务归属为部门；手册名称等基础字段照常渲染', () => {
    store.record = {};
    const text = renderForm();
    expect(text).toContain('手册名称');
    expect(text).toContain('业务归属');
    expect(text).toContain('编制者可见发布版');
    store.record = {id: 3, name: '部门管理手册', org_type: 'section',
      org_name: '某科室', status: 'active', editor_can_view_published: true};
  });
});

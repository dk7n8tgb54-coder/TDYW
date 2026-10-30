/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 编辑弹窗权限门控行为：角色可选项端点以 institution.manual.config 门控，
 * 无 config 权限的 add/edit 用户打开弹窗不得触发该请求（拦截器会弹
 * 权限拒绝），角色选择框隐藏而非恒空展示。
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
  record: {id: 3, name: '部门管理手册', owner_type: 'department', status: 'active',
    editor_can_view_published: true,
    view_roles: [{id: 1, name: '查看角色'}],
    edit_roles: [], publish_roles: []},
  categories: [],
  formVisible: false,
  fetchCategories: jest.fn(),
}));

const {http, hasPermission} = require('libs');

describe('ManualForm 角色请求门控', () => {
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

  it('config 权限用户：请求角色可选项并渲染三个角色选择框', () => {
    hasPermission.mockImplementation(() => true);
    const text = renderForm();
    expect(http.get).toHaveBeenCalledWith('/api/institution/roles/');
    expect(text).toContain('查看角色');
    expect(text).toContain('编制角色');
    expect(text).toContain('发布角色');
  });

  it('无 config 权限：不请求角色、角色选择框隐藏（不恒空展示）', () => {
    hasPermission.mockImplementation(
      code => code !== 'institution.manual.config');
    const text = renderForm();
    const roleCalls = http.get.mock.calls.filter(
      ([url]) => url === '/api/institution/roles/');
    expect(roleCalls).toHaveLength(0);
    // 「查看角色」等词被"编制者可见发布版"的说明文案包含，用隐藏字段
    // 特有的标签/占位文案断言
    expect(text).not.toContain('选择平台级');
    expect(text).not.toContain('编制角色');
    expect(text).not.toContain('发布角色');
    // 其余表单字段不受影响
    expect(text).toContain('手册名称');
    expect(text).toContain('业务归属');
  });
});

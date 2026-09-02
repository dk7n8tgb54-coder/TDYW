/**
 * 台站频率批复 Table 权限与操作行为测试（上线门禁）。
 *
 * 真实渲染 Table（ReactDOM + jsdom），mock store 与 libs.http.delete，
 * 验证：
 * - 操作列按 permission 门控：超管显示 查看/编辑/删除
 * - 仅查看用户：操作列不渲染（双击行仍可进详情）——记录与执照表的差异
 * - 删除确认流程：Modal.confirm 确认后调用 DELETE 并刷新列表
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {updatePermissions} from 'libs';
import {http} from 'libs';
import {message} from 'antd';

jest.mock('../store', () => ({
  records: [{
    id: 1,
    name: 'RG-批复甲',
    doc_no: 'RG-DOC-A',
    frequency_text: '88-108 MHz',
    valid_from: '2026-01-01',
    valid_to: '2026-09-30',
    days_left: 10,
    computed_status: 'expiring',
    responsible_user_name: 'RG-责任人',
    attachment_count: 1,
    created_by_name: 'RG-创建人',
    created_at: '2026-08-01 10:00:00',
  }],
  isFetching: false,
  pageNum: 1,
  pageSize: 20,
  total: 1,
  fetchRecords: jest.fn(),
  showDetail: jest.fn(),
  showForm: jest.fn(),
}));

const ComTable = require('../Table').default;
const store = require('../store');

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  });
}
if (!global.ResizeObserver) {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

let container = null;

function renderTable() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ComTable/>, container);
  });
}

function grantPermissions(perms) {
  sessionStorage.setItem('is_supper', 'false');
  sessionStorage.setItem('permissions', JSON.stringify(perms));
  updatePermissions();
}

function actionButtons() {
  return Array.from(container.querySelectorAll('.ant-table-tbody button'))
    .map(btn => btn.textContent.trim());
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
});

afterEach(() => {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
  document.querySelectorAll('.ant-modal-confirm, .ant-modal-root').forEach(n => n.remove());
  sessionStorage.clear();
});

describe('批复 Table 权限门控', () => {
  it('超管渲染完整操作列：查看/编辑/删除', () => {
    sessionStorage.setItem('is_supper', 'true');
    updatePermissions();
    renderTable();
    expect(actionButtons()).toEqual(['查看', '编辑', '删除']);
    // 新建按钮可见
    const newBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('新建'));
    expect(newBtn).toBeTruthy();
  });

  it('仅查看权限用户不渲染操作列（与执照表行为不一致，双击行进详情）', () => {
    grantPermissions(['radio_license.approval.view']);
    renderTable();
    const headerTexts = Array.from(container.querySelectorAll('.ant-table-thead th'))
      .map(th => th.textContent.trim());
    expect(headerTexts).not.toContain('操作');
    expect(actionButtons()).toEqual([]);
    // 双击行仍可进详情
    const row = container.querySelector('.ant-table-tbody tr');
    act(() => {
      row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
    });
    expect(store.showDetail).toHaveBeenCalled();
  });

  it('无权限用户不渲染操作列与新建按钮', () => {
    grantPermissions([]);
    renderTable();
    const newBtn = Array.from(container.querySelectorAll('button'))
      .find(btn => btn.textContent.includes('新建'));
    expect(newBtn).toBeFalsy();
  });
});

describe('批复 Table 删除确认流程', () => {
  it('确认删除后调用 DELETE 接口并刷新列表', async () => {
    sessionStorage.setItem('is_supper', 'true');
    updatePermissions();
    const deleteSpy = jest.spyOn(http, 'delete').mockResolvedValue({});
    renderTable();
    const delBtn = actionButtons().indexOf('删除');
    act(() => {
      container.querySelectorAll('.ant-table-tbody button')[delBtn]
        .dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    // Modal.confirm 弹出
    const confirmOk = document.querySelector('.ant-modal-confirm-btns .ant-btn-primary');
    expect(confirmOk).toBeTruthy();
    await act(async () => {
      confirmOk.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(deleteSpy).toHaveBeenCalledWith(
      '/api/radio-license/approvals/', {params: {id: 1}});
    expect(store.fetchRecords).toHaveBeenCalled();
  });
});

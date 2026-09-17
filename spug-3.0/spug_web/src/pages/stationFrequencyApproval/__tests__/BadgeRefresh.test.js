/**
 * 台站频率批复 CRUD 成功后立即刷新全局红点行为测试（2026-09 第二轮）。
 *
 * 真实渲染 Form / Table 与真实 MobX store 单例（ReactDOM + jsdom），
 * mock libs.http（按 URL 分流），使用真实 ApprovalBadgeStore（其请求走
 * mock http），验证：
 * - 新增/编辑提交成功（后端真实成功）后立即调用批复 badge 刷新
 * - 删除确认成功后立即调用批复 badge 刷新
 * - 业务请求失败（HTTP 200 + error 被拦截器转 reject）时不刷新红点
 * - 红点刷新失败（badge 接口网络失败）不影响已成功的业务操作与成功提示
 * - 成功提示发生在后端真实成功之后（先 message.success 后红点请求）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHttpPost = jest.fn();
const mockHttpDelete = jest.fn();
const mockHttpGet = jest.fn().mockResolvedValue([]);

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  X_TOKEN: 'test-token',
  syncAttachmentCount: jest.fn(),
}));

// components 使用真实实现（与既有 Table/Form 测试一致）：
// Form 表单态不渲染 AttachmentManager，Table 依赖真实 TableCard 渲染行与操作列

const ComForm = require('../Form').default;
const ComTable = require('../Table').default;
const S = require('../store').default;

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

const BADGE_URL = '/api/radio-license/approvals/badge/';
const LIST_URL = '/api/radio-license/approvals/';
const FULL_RECORD = {
  id: 8,
  name: 'RG-批复表单',
  doc_no: 'RG-FORM-DOC',
  frequency_text: '88-108 MHz',
  valid_from: '2026-01-01',
  valid_to: '2027-01-01',
};

const TABLE_RECORD = {
  id: 1,
  name: 'RG-批复甲',
  doc_no: 'RG-DOC-A',
  frequency_text: '88-108 MHz',
  valid_from: '2026-01-01',
  valid_to: '2026-09-30',
  days_left: 10,
  computed_status: 'expiring',
  attachment_count: 1,
  created_by_name: 'RG-创建人',
  created_at: '2026-08-01 10:00:00',
};

let container = null;
let messageSuccessSpy;

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function mount(node) {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(node, container);
  });
}

function unmountAll() {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
  document.querySelectorAll('.ant-modal-root').forEach(n => n.remove());
}

function badgeGetCalls() {
  return mockHttpGet.mock.calls.filter(([url]) => String(url) === BADGE_URL);
}

beforeEach(() => {
  jest.clearAllMocks();
  // 默认分流：列表返回一条记录，badge 返回全局统计
  mockHttpGet.mockImplementation(url => {
    if (String(url) === LIST_URL) {
      return Promise.resolve({records: [TABLE_RECORD], total: 1, page: 1, page_size: 20});
    }
    if (String(url) === BADGE_URL) {
      return Promise.resolve({count: 1, expiring_count: 1, expired_count: 0});
    }
    return Promise.resolve([]);
  });
  mockHttpPost.mockResolvedValue({});
  mockHttpDelete.mockResolvedValue({});
  messageSuccessSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  jest.spyOn(message, 'error').mockImplementation(() => {});
  sessionStorage.setItem('token', 'rg-test-token');
  sessionStorage.setItem('is_supper', 'true');
  S.setActive(true);
  S.formVisible = true;
  S.detailVisible = false;
  S.record = {};
});

afterEach(() => {
  unmountAll();
  S.setActive(true);
  S.formVisible = false;
  S.detailVisible = false;
  S.record = {};
  sessionStorage.clear();
});

async function submitForm(record) {
  S.record = record;
  mount(<ComForm/>);
  const okBtn = document.querySelectorAll('.ant-modal-footer .ant-btn-primary')[0];
  await act(async () => {
    okBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    await flush();
  });
}

describe('批复 Form 提交与红点刷新', () => {
  it('编辑提交成功后立即刷新批复红点，且成功提示先于红点请求', async () => {
    await submitForm({...FULL_RECORD});
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    expect(messageSuccessSpy).toHaveBeenCalledWith('操作成功');
    expect(badgeGetCalls()).toHaveLength(1);
    // 成功提示发生在后端真实成功之后（同一 then 链内先提示后刷新红点）
    const badgeCallIndex = mockHttpGet.mock.calls.findIndex(
      ([url]) => String(url) === BADGE_URL);
    expect(mockHttpGet.mock.invocationCallOrder[badgeCallIndex])
      .toBeGreaterThan(messageSuccessSpy.mock.invocationCallOrder[0]);
    expect(S.formVisible).toBe(false);
  });

  it('新增（无 id）提交成功后同样立即刷新批复红点', async () => {
    await submitForm({...FULL_RECORD, id: undefined});
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    expect(badgeGetCalls()).toHaveLength(1);
  });

  it('提交失败（HTTP 200 + error）不刷新红点且弹窗保持打开', async () => {
    mockHttpPost.mockRejectedValue('权限拒绝：缺少编辑批复权限');
    await submitForm({...FULL_RECORD});
    expect(messageSuccessSpy).not.toHaveBeenCalled();
    expect(badgeGetCalls()).toHaveLength(0);
    expect(S.formVisible).toBe(true);
  });

  it('红点刷新失败不影响已成功的业务操作与成功提示', async () => {
    // 仅 badge 接口失败，业务列表接口正常
    mockHttpGet.mockImplementation(url => {
      if (String(url) === BADGE_URL) {
        return Promise.reject(new Error('badge 网络错误'));
      }
      if (String(url) === LIST_URL) {
        return Promise.resolve({records: [TABLE_RECORD], total: 1, page: 1, page_size: 20});
      }
      return Promise.resolve([]);
    });
    await submitForm({...FULL_RECORD});
    expect(messageSuccessSpy).toHaveBeenCalledWith('操作成功');
    expect(S.formVisible).toBe(false);
    expect(badgeGetCalls()).toHaveLength(1);
  });
});

describe('批复 Table 删除与红点刷新', () => {
  it('删除成功后立即刷新批复红点', async () => {
    mount(<ComTable/>);
    await act(async () => {
      await flush();
    });
    const delBtn = Array.from(container.querySelectorAll('.ant-table-tbody button'))
      .find(btn => btn.textContent.trim() === '删除');
    expect(delBtn).toBeTruthy();
    await act(async () => {
      delBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    // 批复删除确认按钮为 danger 样式（okType: 'danger'）
    const confirmOk = document.querySelector('.ant-modal-confirm-btns .ant-btn-dangerous');
    expect(confirmOk).toBeTruthy();
    await act(async () => {
      confirmOk.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpDelete).toHaveBeenCalledWith(
      '/api/radio-license/approvals/', {params: {id: 1}});
    expect(messageSuccessSpy).toHaveBeenCalledWith('删除成功');
    expect(badgeGetCalls()).toHaveLength(1);
  });

  it('删除失败（HTTP 200 + error）不刷新红点也不提示成功', async () => {
    mockHttpDelete.mockRejectedValue('删除失败：记录不存在或无权限删除');
    mount(<ComTable/>);
    await act(async () => {
      await flush();
    });
    const delBtn = Array.from(container.querySelectorAll('.ant-table-tbody button'))
      .find(btn => btn.textContent.trim() === '删除');
    await act(async () => {
      delBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    const confirmOk = document.querySelector('.ant-modal-confirm-btns .ant-btn-dangerous');
    await act(async () => {
      confirmOk.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(messageSuccessSpy).not.toHaveBeenCalled();
    expect(badgeGetCalls()).toHaveLength(0);
  });
});

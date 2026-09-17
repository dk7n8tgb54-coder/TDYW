/**
 * 合同协议 CRUD 成功后立即刷新菜单红点行为测试（2026-09 第二轮）。
 *
 * 真实渲染 Form / Table 与真实 MobX store 单例（ReactDOM + jsdom），
 * mock libs.http（按 URL 分流），使用真实 ContractAgreementBadgeStore
 * （其请求走 mock http），验证：
 * - 新增/编辑提交成功（后端真实成功）后立即调用合同 badge 刷新
 * - 删除确认成功后立即调用合同 badge 刷新
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

const BADGE_URL = '/api/contract-agreement/badge/';
const LIST_URL = '/api/contract-agreement/';
const FULL_RECORD = {
  id: 9,
  contract_name: '设备采购合同A',
  contract_no: 'HT-2026-001',
  contract_type: 'device_purchase',
  valid_start_date: '2026-01-01',
  valid_end_date: '2026-12-31',
  responsible_user_id: 11,
  responsible_user_name: '用户甲',
  signing_party: '某科技公司',
  has_fee: false,
  fee_amount: '',
  fee_detail: '',
  remark: '',
};

const TABLE_RECORD = {
  id: 1,
  contract_name: '设备采购合同B',
  contract_no: 'HT-2026-002',
  contract_type: 'device_purchase',
  valid_start_date: '2026-01-01',
  valid_end_date: '2026-09-30',
  validity_type: 'fixed',
  days_left: 10,
  computed_status: 'expiring',
  attachment_count: 0,
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
  S.formVisible = true;
  S.detailVisible = false;
  S.record = {};
});

afterEach(() => {
  unmountAll();
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

describe('合同 Form 提交与红点刷新', () => {
  it('编辑提交成功后立即刷新合同红点，且成功提示先于红点请求', async () => {
    await submitForm({...FULL_RECORD});
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    expect(messageSuccessSpy).toHaveBeenCalledWith('操作成功');
    expect(badgeGetCalls()).toHaveLength(1);
    const badgeCallIndex = mockHttpGet.mock.calls.findIndex(
      ([url]) => String(url) === BADGE_URL);
    expect(mockHttpGet.mock.invocationCallOrder[badgeCallIndex])
      .toBeGreaterThan(messageSuccessSpy.mock.invocationCallOrder[0]);
    expect(S.formVisible).toBe(false);
  });

  it('新增（无 id）提交成功后同样立即刷新合同红点', async () => {
    await submitForm({...FULL_RECORD, id: undefined});
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    expect(badgeGetCalls()).toHaveLength(1);
  });

  it('提交失败（HTTP 200 + error）不刷新红点且弹窗保持打开', async () => {
    mockHttpPost.mockRejectedValue('权限拒绝');
    await submitForm({...FULL_RECORD});
    expect(messageSuccessSpy).not.toHaveBeenCalled();
    expect(badgeGetCalls()).toHaveLength(0);
    expect(S.formVisible).toBe(true);
  });

  it('红点刷新失败不影响已成功的业务操作与成功提示', async () => {
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

describe('合同 Table 删除与红点刷新', () => {
  it('删除成功后立即刷新合同红点', async () => {
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
    // 合同删除确认按钮为默认 primary 样式
    const confirmOk = document.querySelector('.ant-modal-confirm-btns .ant-btn-primary');
    expect(confirmOk).toBeTruthy();
    await act(async () => {
      confirmOk.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(mockHttpDelete).toHaveBeenCalledWith(
      '/api/contract-agreement/', {params: {id: 1}});
    expect(messageSuccessSpy).toHaveBeenCalledWith('删除成功');
    expect(badgeGetCalls()).toHaveLength(1);
  });

  it('删除失败（HTTP 200 + error）不刷新红点也不提示成功', async () => {
    mockHttpDelete.mockRejectedValue('删除失败');
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
    const confirmOk = document.querySelector('.ant-modal-confirm-btns .ant-btn-primary');
    await act(async () => {
      confirmOk.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      await flush();
    });
    expect(messageSuccessSpy).not.toHaveBeenCalled();
    expect(badgeGetCalls()).toHaveLength(0);
  });
});

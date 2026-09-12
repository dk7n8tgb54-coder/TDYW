/**
 * 合同协议 Form 测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例，无 @testing-library），mock libs.http 与
 * components.AttachmentManager，验证：
 * - 编辑提交：载荷携带 id，日期格式化 YYYY-MM-DD
 * - has_fee 为否时费用金额置 null、费用明细清空（隐藏字段的显式清空语义）
 * - 详情态：标题、剩余天数（负数 → 已关闭）、费用渲染
 * - 详情态点击"编辑"切换回编辑态
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import ComForm from '../Form';
import S from '../store';
import { http } from 'libs';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => Promise.resolve([])),
    post: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
  hasPermission: jest.fn(() => true),
  syncAttachmentCount: jest.fn(),
}));

jest.mock('components', () => ({
  AttachmentManager: () => null,
}));

// jsdom 未实现 matchMedia，antd Modal 渲染需要（经典 CRA/antd 测试补丁）
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const EDIT_RECORD = {
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
  fee_amount: 100,
  fee_detail: '旧费用明细',
  remark: '备注信息',
};

let container = null;

function renderForm(record, detailMode = false) {
  S.record = record || {};
  S.formVisible = !detailMode;
  S.detailVisible = detailMode;
  act(() => {
    ReactDOM.render(<ComForm />, container);
  });
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

async function clickOk() {
  const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary');
  expect(okBtn).toBeTruthy();
  await click(okBtn);
  await act(async () => {});
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  http.get.mockImplementation(() => Promise.resolve([]));
  http.post.mockImplementation(() => Promise.resolve());
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
  S.record = {};
  S.formVisible = false;
  S.detailVisible = false;
  S.responsibleUsers = [];
  S.responsibleUsersLoaded = false;
});

describe('合同协议编辑提交', () => {
  it('载荷携带 id，日期格式化 YYYY-MM-DD', async () => {
    renderForm(EDIT_RECORD);
    await clickOk();
    expect(http.post).toHaveBeenCalledTimes(1);
    const [url, payload] = http.post.mock.calls[0];
    expect(url).toBe('/api/contract-agreement/');
    expect(payload.id).toBe(9);
    expect(payload.contract_name).toBe('设备采购合同A');
    expect(payload.contract_type).toBe('device_purchase');
    expect(payload.valid_start_date).toBe('2026-01-01');
    expect(payload.valid_end_date).toBe('2026-12-31');
    expect(payload.responsible_user_id).toBe(11);
  });

  it('has_fee 为否时费用金额置 null、费用明细清空', async () => {
    renderForm({...EDIT_RECORD, has_fee: false, fee_amount: 100, fee_detail: '旧费用明细'});
    await clickOk();
    const [, payload] = http.post.mock.calls[0];
    expect(payload.has_fee).toBe(false);
    expect(payload.fee_amount).toBeNull();
    expect(payload.fee_detail).toBe('');
  });

  it('has_fee 为真时费用字段保留', async () => {
    renderForm({...EDIT_RECORD, has_fee: true, fee_amount: 100, fee_detail: '明细'});
    // has_fee 为真时费用字段才注册渲染，fee_amount 需回填后再提交
    await clickOk();
    const [, payload] = http.post.mock.calls[0];
    expect(payload.has_fee).toBe(true);
  });
});

describe('合同协议详情态', () => {
  it('渲染详情字段：剩余天数与费用', () => {
    renderForm({
      id: 9, contract_name: '设备采购合同A', computed_status: 'expired',
      days_left: -5, has_fee: false, fee_detail: '', remark: '',
    }, true);
    expect(document.querySelector('.ant-modal-title').textContent).toBe('合同协议详情');
    const body = document.querySelector('.ant-modal-body').textContent;
    expect(body).toContain('设备采购合同A');
    // days_left < 0 → 已关闭
    expect(body).toContain('已关闭');
    // has_fee false → 无
    expect(body).toContain('无');
  });

  it('详情态点击"编辑"切换回编辑态', async () => {
    renderForm(EDIT_RECORD, true);
    expect(S.detailVisible).toBe(true);
    // antd 对两字中文按钮自动插入空格，文本为"编 辑"
    const editBtn = Array.from(document.querySelectorAll('.ant-modal-footer .ant-btn'))
      .find(b => b.textContent.replace(/\s/g, '') === '编辑');
    expect(editBtn).toBeTruthy();
    await click(editBtn);
    expect(S.detailVisible).toBe(false);
    expect(S.formVisible).toBe(true);
  });
});

/**
 * 合同协议 Form 测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例，无 @testing-library），mock libs.http 与
 * components.AttachmentManager，验证：
 * - 编辑提交：载荷携带 id，日期格式化 YYYY-MM-DD
 * - has_fee 为否时费用内容与明细提交空串（服务端强制清空语义）
 * - 费用内容为普通文本输入框：可输入中文/带单位费用并原样提交
 * - 详情态：标题、剩余天数（负数 → 已关闭）、费用原样显示（无人民币拼接）
 * - 详情态点击"编辑"切换回编辑态
 * - 后端业务错误：弹窗保持打开、不重复提示
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
  fee_amount: '',
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

function setInputValue(input, value) {
  // React 17 受控输入：需借用原生 value setter 触发 onChange
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  setter.call(input, value);
  input.dispatchEvent(new Event('input', {bubbles: true}));
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

  it('has_fee 为否时费用内容与明细提交空串', async () => {
    renderForm({...EDIT_RECORD, has_fee: false, fee_amount: '残留费用', fee_detail: '旧费用明细'});
    await clickOk();
    const [, payload] = http.post.mock.calls[0];
    expect(payload.has_fee).toBe(false);
    expect(payload.fee_amount).toBe('');
    expect(payload.fee_detail).toBe('');
  });

  it('has_fee 为真时费用文本原样保留在载荷中', async () => {
    renderForm({...EDIT_RECORD, has_fee: true, fee_amount: '8888.66元/年', fee_detail: '明细'});
    await clickOk();
    const [, payload] = http.post.mock.calls[0];
    expect(payload.has_fee).toBe(true);
    expect(payload.fee_amount).toBe('8888.66元/年');
  });

  it('费用内容为普通文本输入框（非 InputNumber，无人民币前缀）', () => {
    renderForm({...EDIT_RECORD, has_fee: true, fee_amount: '12000元/年'});
    const input = document.getElementById('fee_amount');
    expect(input).toBeTruthy();
    expect(input.tagName).toBe('INPUT');
    // antd InputNumber 的类名为 ant-input-number，普通 Input 为 ant-input
    expect(input.className).toContain('ant-input');
    expect(input.className).not.toContain('ant-input-number');
    expect(input.maxLength).toBe(200);
    expect(document.body.textContent).not.toContain('人民币');
  });

  it('可以输入中文和带单位的费用并保留在提交载荷中', async () => {
    renderForm({...EDIT_RECORD, has_fee: true, fee_amount: ''});
    const input = document.getElementById('fee_amount');
    setInputValue(input, '按实际使用量结算');
    await clickOk();
    const [, payload] = http.post.mock.calls[0];
    expect(payload.fee_amount).toBe('按实际使用量结算');
  });

  it('有费用但未填写内容时拦截提交', async () => {
    renderForm({...EDIT_RECORD, has_fee: true, fee_amount: ''});
    await clickOk();
    expect(http.post).not.toHaveBeenCalled();
  });

  it('费用内容全为空格时拦截提交', async () => {
    renderForm({...EDIT_RECORD, has_fee: true, fee_amount: ''});
    setInputValue(document.getElementById('fee_amount'), '   ');
    await clickOk();
    expect(http.post).not.toHaveBeenCalled();
  });

  it('后端业务错误时表单保持打开且不重复提示', async () => {
    http.post.mockImplementation(() => Promise.reject(new Error('费用内容格式不正确')));
    renderForm({...EDIT_RECORD, has_fee: true, fee_amount: '8888元/年'});
    await clickOk();
    expect(S.formVisible).toBe(true);
    expect(S.detailVisible).toBe(false);
    // 成功提示不出现（错误由 http 拦截器统一提示，业务代码不重复弹窗）
    expect(document.body.textContent).not.toContain('操作成功');
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

  it('详情费用原样显示文本、不拼接人民币', () => {
    renderForm({
      id: 9, contract_name: '费用详情合同', has_fee: true,
      fee_amount: '约30万元', fee_detail: '分两期', remark: '',
    }, true);
    const body = document.querySelector('.ant-modal-body').textContent;
    expect(body).toContain('约30万元');
    expect(body).not.toContain('人民币');
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

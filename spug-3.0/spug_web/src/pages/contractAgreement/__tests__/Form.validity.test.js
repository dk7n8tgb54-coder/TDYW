/**
 * 合同协议 Form 期限类型（长期有效）测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例，无 @testing-library），mock libs.http 与
 * components.AttachmentManager，验证：
 * - 新建表单默认选中「固定期限」
 * - 固定期限缺截止日期时提交被校验拦截（http.post 不发出）
 * - 切换「长期有效」后截止日期控件隐藏
 * - 切换长期有效后旧截止日期不进请求（payload.valid_end_date=null）
 * - 编辑长期合同时「长期有效」正确回显
 * - 详情态长期合同：截止日期显示「长期有效」、蓝色 Tag、剩余天数「-」
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

const FIXED_RECORD = {
  id: 9,
  contract_name: '设备采购合同A',
  contract_no: 'HT-2026-001',
  contract_type: 'device_purchase',
  validity_type: 'fixed',
  valid_start_date: '2026-01-01',
  valid_end_date: '2026-12-31',
  responsible_user_id: 11,
  responsible_user_name: '用户甲',
  signing_party: '某科技公司',
  has_fee: false,
  remark: '',
};

const LONG_TERM_RECORD = {
  id: 10,
  contract_name: '场地租赁长期合同',
  contract_type: 'service_guarantee',
  validity_type: 'long_term',
  valid_start_date: '2026-01-01',
  valid_end_date: null,
  responsible_user_id: 11,
  responsible_user_name: '用户甲',
  signing_party: '某服务中心',
  has_fee: false,
  remark: '',
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
    node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
}

function getRadioInput(label) {
  // React 对 radio 的 value 只设 DOM 属性不设 attribute，不能按 value 选择器找；
  // 按用户可见的选项文本定位（antd Radio 外层为 label.ant-radio-wrapper）。
  // Modal 渲染在 document.body 的 portal 中，不在测试 container 节点内
  const wrapper = Array.from(document.querySelectorAll('label.ant-radio-wrapper'))
    .find(l => l.textContent.replace(/\s/g, '') === label);
  return wrapper ? wrapper.querySelector('input[type="radio"]') : null;
}

async function chooseValidityType(label) {
  const input = getRadioInput(label);
  expect(input).toBeTruthy();
  await act(async () => {
    // jsdom 的 input.click() 触发单选激活行为并派发 change，antd Radio.Group 据此更新
    input.click();
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

describe('合同协议期限类型表单', () => {
  it('新建表单默认选中固定期限', () => {
    renderForm({});
    expect(getRadioInput('固定期限').checked).toBe(true);
    expect(getRadioInput('长期有效').checked).toBe(false);
    // 固定期限下截止日期控件可见
    expect(document.querySelector('#valid_end_date')).toBeTruthy();
  });

  it('未提交 validity_type 的既有记录编辑时按固定期限回显并提交 fixed', async () => {
    const legacy = {...FIXED_RECORD};
    delete legacy.validity_type;
    renderForm(legacy);
    expect(getRadioInput('固定期限').checked).toBe(true);
    await clickOk();
    const [, payload] = http.post.mock.calls[0];
    expect(payload.validity_type).toBe('fixed');
    expect(payload.valid_end_date).toBe('2026-12-31');
  });

  it('固定期限缺截止日期时提交被校验拦截', async () => {
    renderForm({...FIXED_RECORD, valid_end_date: undefined});
    await clickOk();
    expect(http.post).not.toHaveBeenCalled();
    const errors = Array.from(
      document.querySelectorAll('.ant-form-item-explain-error')).map(n => n.textContent);
    expect(errors).toContain('请选择截止日期');
  });

  it('选择长期有效后截止日期控件隐藏', async () => {
    renderForm(FIXED_RECORD);
    expect(document.querySelector('#valid_end_date')).toBeTruthy();
    await chooseValidityType('长期有效');
    expect(getRadioInput('长期有效').checked).toBe(true);
    // 截止日期控件随期限类型切换而隐藏（起始日期控件不受影响）
    expect(document.querySelector('#valid_end_date')).toBeNull();
    expect(document.querySelector('#valid_start_date')).toBeTruthy();
  });

  it('切换长期有效后旧截止日期不进请求（valid_end_date=null）', async () => {
    renderForm(FIXED_RECORD);
    await chooseValidityType('长期有效');
    await clickOk();
    expect(http.post).toHaveBeenCalledTimes(1);
    const [, payload] = http.post.mock.calls[0];
    expect(payload.validity_type).toBe('long_term');
    expect(payload.valid_end_date).toBeNull();
    expect(payload.valid_start_date).toBe('2026-01-01');
    expect(payload.id).toBe(9);
  });

  it('编辑长期合同时正确回显并可原样保存', async () => {
    renderForm(LONG_TERM_RECORD);
    expect(getRadioInput('长期有效').checked).toBe(true);
    expect(document.querySelector('#valid_end_date')).toBeNull();
    await clickOk();
    const [, payload] = http.post.mock.calls[0];
    expect(payload.validity_type).toBe('long_term');
    expect(payload.valid_end_date).toBeNull();
  });
});

describe('合同协议详情态（长期有效）', () => {
  it('截止日期显示长期有效并渲染蓝色 Tag', () => {
    renderForm({
      ...LONG_TERM_RECORD,
      computed_status: 'long_term',
      status: 'long_term',
      days_left: null,
    }, true);
    const body = document.querySelector('.ant-modal-body').textContent;
    expect(body).toContain('场地租赁长期合同');
    expect(body).toContain('长期有效');
    const tag = document.querySelector('.ant-tag-blue');
    expect(tag).toBeTruthy();
    expect(tag.textContent).toBe('长期有效');
    // 绿色「正常」等旧状态标签不得出现
    expect(document.querySelector('.ant-tag-green')).toBeNull();
    expect(body).not.toContain('undefined');
    expect(body).not.toContain('null');
  });

  it('长期合同剩余天数显示「-」', () => {
    renderForm({
      ...LONG_TERM_RECORD,
      computed_status: 'long_term',
      status: 'long_term',
      days_left: null,
    }, true);
    const body = document.querySelector('.ant-modal-body').textContent;
    expect(body).toMatch(/剩余天数-/);
    expect(body).not.toContain('undefined');
  });
});

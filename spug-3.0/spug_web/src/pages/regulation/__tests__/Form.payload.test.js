/**
 * 规章管理 Form 提交载荷测试（defect_reproduction）
 *
 * B5：编辑弹窗清空日期/分类后保存无效。
 * antd 清空 DatePicker/Select 后 getFieldsValue() 取值为 undefined，
 * JSON.stringify 会直接丢弃这些键，后端 PUT 无法区分"未提供"与"清空"，
 * 用户清空字段保存后重新打开，旧值依旧保留。
 *
 * 期望（修复后）：载荷对清空的日期/分类显式携带空字符串，
 * 后端将空字符串解释为清空（日期 -> None，分类 -> None）。
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import moment from 'moment';
import ComForm, { buildRegulationPayload } from '../Form';
import S from '../store';
import { http } from 'libs';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => Promise.resolve({})),
    post: jest.fn(() => Promise.resolve()),
    put: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
  hasPermission: () => true,
}));

jest.mock('components', () => ({
  AttachmentManager: () => null,
}));

// jsdom 未实现 matchMedia，antd 弹窗链渲染需要（经典 CRA/antd 测试补丁）
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
  id: 1,
  title: '测试规章',
  rule_no: 'R-001',
  category_id: 5,
  category_name: '叶子分类',
  issuing_authority: '某单位',
  biz_type: '空管',
  publish_date: '2026-01-01',
  effective_date: '2026-02-01',
  status: 'active',
};

let container = null;

function renderEditForm() {
  S.record = EDIT_RECORD;
  S.detailVisible = false;
  S.formVisible = true;
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
  // 冲刷 validateFields -> http.put 的微任务链
  await act(async () => {});
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
  S.record = {};
  S.detailVisible = false;
  S.formVisible = false;
});

describe('buildRegulationPayload 单元行为', () => {
  test('清空的日期/分类以空字符串显式提交', () => {
    const payload = buildRegulationPayload({
      title: 't',
      rule_no: 'R',
      status: 'active',
      publish_date: undefined,
      effective_date: undefined,
      category_id: undefined,
    });
    expect(payload.publish_date).toBe('');
    expect(payload.effective_date).toBe('');
    expect(payload.category_id).toBe('');
  });

  test('日期 moment 格式化、分类数值保留', () => {
    const payload = buildRegulationPayload({
      publish_date: moment('2026-01-01'),
      effective_date: moment('2026-02-01'),
      category_id: 5,
    });
    expect(payload.publish_date).toBe('2026-01-01');
    expect(payload.effective_date).toBe('2026-02-01');
    expect(payload.category_id).toBe(5);
  });
});

describe('编辑弹窗提交载荷', () => {
  test('未清空字段时载荷完整（回归对照）', async () => {
    renderEditForm();
    await clickOk();
    expect(http.put).toHaveBeenCalledTimes(1);
    const [url, payload] = http.put.mock.calls[0];
    expect(url).toBe('/api/regulation/1/');
    expect(payload).toEqual(expect.objectContaining({
      title: '测试规章',
      rule_no: 'R-001',
      category_id: 5,
      publish_date: '2026-01-01',
      effective_date: '2026-02-01',
      status: 'active',
    }));
  });

  test('B5：清空日期与分类后载荷显式携带空字符串', async () => {
    renderEditForm();

    // 点击两个 DatePicker 的清空图标与分类 Select 的清空图标。
    // antd 4 DatePicker 的清空图标是 .ant-picker-clear，动作绑定在 mouseup；
    // Select 的清空是 .ant-select-clear，动作绑定在 mousedown。
    // 每次派发后 React 会重渲染替换节点，必须逐个重新查询。
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        const pickerClear = document.querySelector('.ant-picker-clear');
        if (pickerClear) {
          pickerClear.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
          return;
        }
        const selectClear = document.querySelector('.ant-select-clear');
        if (selectClear) {
          selectClear.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        }
      });
    }

    await clickOk();
    expect(http.put).toHaveBeenCalledTimes(1);
    const [url, payload] = http.put.mock.calls[0];
    expect(url).toBe('/api/regulation/1/');
    expect(payload.publish_date).toBe('');
    expect(payload.effective_date).toBe('');
    expect(payload.category_id).toBe('');
  });
});

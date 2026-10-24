/**
 * 合同协议附件上传上限契约测试
 *
 * 真实渲染详情态 Form（ReactDOM + jsdom，仓库惯例，无 @testing-library），用捕获
 * props 的替身组件接收 AttachmentManager 的实际入参，验证页面下发的单文件上传
 * 上限为 100MB。前端大小校验与「单文件最大 100MB」提示由共享 AttachmentManager
 * 组件按该 prop 执行/渲染，页面只负责传入限额。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import ComForm from '../Form';
import S from '../store';
import { http } from 'libs';

const mockManagerProps = {current: null};

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
  AttachmentManager: props => {
    mockManagerProps.current = props;
    return null;
  },
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

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  http.get.mockImplementation(() => Promise.resolve([]));
  mockManagerProps.current = null;
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

describe('合同协议附件上传上限', () => {
  it('详情态附件管理器单文件上限为 100MB', () => {
    S.record = {
      id: 21,
      contract_name: '附件上限契约合同',
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
    S.formVisible = false;
    S.detailVisible = true;
    act(() => {
      ReactDOM.render(<ComForm />, container);
    });
    expect(mockManagerProps.current).toBeTruthy();
    expect(mockManagerProps.current.module).toBe('contract_agreement');
    expect(mockManagerProps.current.maxFileSize).toBe(100);
  });
});

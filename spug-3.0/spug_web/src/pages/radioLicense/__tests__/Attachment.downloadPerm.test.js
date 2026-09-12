/**
 * F-16 缺陷验证用例：执照详情附件下载按钮无权限门控（上线门禁复验）。
 *
 * 真实渲染执照 Form（ReactDOM + jsdom），mock libs（http.get 返回附件列表，
 * hasPermission 按真实 & / | 语义实现），**不 mock components**——走真实
 * AttachmentManager 的 canDownload 门控逻辑。
 *
 * 场景：用户无 radio_license.attachment.download 权限（其余权限齐全）。
 * 规格（六.7）：下载按钮不得显示。
 * 对照组：批复 Form 正确传了 downloadPerm，同样权限下按钮应隐藏。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: jest.fn(),
    delete: jest.fn(),
  },
  // 按真实 functools.hasPermission 语义实现（| 分组 OR，组内 & AND）
  hasPermission: (code) => {
    if (!code) return true;
    const denied = ['radio_license.attachment.download'];
    return code.split('|').some(
      orItem => orItem.split('&').every(c => !denied.includes(c.trim()))
    );
  },
  X_TOKEN: 'test-token',
}));

const ComForm = require('../Form').default;
const S = require('../store').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {},
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

const ATTACHMENTS = [{
  id: 91, file_name: 'RG-权限验证.pdf', file_size: 1024,
  file_ext: '.pdf', previewable: true,
  uploaded_by_name: 'RG-上传人', created_at: '2026-09-01 10:00:00',
}];

let container = null;

function renderForm() {
  container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<ComForm/>, container);
  });
}

function unmountForm() {
  if (container) {
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    container.remove();
    container = null;
  }
}

// 附件操作列按钮文案（按钮渲染在 document.body 的 Modal portal 中）
function attachmentActionButtons() {
  return Array.from(document.querySelectorAll('.ant-table-tbody button'))
    .map(btn => btn.textContent.trim());
}

beforeEach(() => {
  jest.clearAllMocks();
  mockHttpGet.mockResolvedValue(ATTACHMENTS);
  sessionStorage.setItem('token', 'rg-test-token');
  S.responsibleUsers = [];
  S.responsibleUsersLoaded = true;
  S._responsibleUsersToken = 'rg-test-token';
  S.formVisible = false;
  S.detailVisible = true;
  S.record = {
    id: 5,
    station_name: 'RG-下载权限台站',
    purpose: 'x',
    valid_from: '2026-01-01',
    valid_to: '2027-01-01',
    responsible_user_name: 'RG-责任人',
    computed_status: 'normal',
    days_left: 100,
    frequencies: [],
    created_by_name: 'RG-创建人',
    created_at: '2026-08-01 10:00:00',
  };
});

afterEach(() => {
  unmountForm();
  document.querySelectorAll('.ant-modal-root').forEach(n => n.remove());
  S.detailVisible = false;
  S.record = {};
  sessionStorage.removeItem('token');
});

describe('F-16 验证：无下载权限用户在执照详情附件区的按钮显示', () => {
  it('无 radio_license.attachment.download 权限时不应显示下载按钮', async () => {
    renderForm();
    // 等待附件列表请求完成并渲染
    await act(async () => {
      await mockHttpGet.mock.results[0].value;
      await new Promise(r => setTimeout(r, 0));
    });
    const buttons = attachmentActionButtons();
    // 规格：无下载权限 → 不显示「下载」
    expect(buttons).not.toContain('下载');
  });

  it('对照组：文件名/预览/删除按钮不受影响（其余权限齐全）', async () => {
    renderForm();
    await act(async () => {
      await mockHttpGet.mock.results[0].value;
      await new Promise(r => setTimeout(r, 0));
    });
    const rowText = document.querySelector('.ant-table-tbody').textContent;
    expect(rowText).toContain('RG-权限验证.pdf');
    const buttons = attachmentActionButtons();
    expect(buttons).toContain('预览');
    expect(buttons).toContain('删除');
  });
});

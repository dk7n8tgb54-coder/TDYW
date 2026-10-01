/**
 * 巡检中心（前端融合外壳）测试。
 *
 * 真实渲染组件（ReactDOM + jsdom + MemoryRouter，仓库惯例），mock libs，
 * 验证外壳职责，不重复覆盖三个页签页面的业务逻辑（各有独立测试）：
 * - 页签按权限显示：巡检业务权限 → 今日巡检/巡检记录；模板权限 → 巡检模板；
 *   仅有模板权限时默认打开"巡检模板"，有巡检权限时默认打开"今日巡检"；
 * - URL ?tab= 恢复页签；无权限页签回退默认；
 * - ?tab=history&detail=<id> 打开巡检记录页签并经既有挂载逻辑打开详情抽屉；
 * - 页签切换只挂载当前页签页面；今日巡检切走再切回，草稿按既有
 *   localStorage 暂存机制恢复；
 * - 切换页签清理记录页遗留详情抽屉（防止隐藏的 browse detail 覆盖
 *   工作台草稿单），并把页签状态写入 URL；
 * - 旧路径重定向组件替换到巡检中心对应页签并保留 detail 参数。
 *
 * 注意：巡检 store 为模块级单例，每个用例后必须重置弹层与列表状态。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {MemoryRouter} from 'react-router-dom';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();
const mockHistoryReplace = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {replace: mockHistoryReplace, push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;
let store = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  sessionStorage.setItem('nickname', 'admin');
  localStorage.clear();
  store = require('../../inspection/store').default;
  store.resetDetail();
  store.browseVisible = false;
  store.tplFormVisible = false;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  store = null;
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete, mockHistoryReplace]
    .forEach(fn => fn.mockReset());
  localStorage.clear();
  sessionStorage.removeItem('nickname');
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const TEMPLATE_TREE = {
  id: 7, name: '机房巡检模板', description: '', is_active: true,
  devices: [
    {id: 11, device_name: '1号收发信机', display_order: 0, is_active: true, items: [
      {id: 21, name: '面板指示灯', input_type: 'choice',
        choices: ['正常', '不正常'], is_required: true, display_order: 0},
    ]},
  ],
};

const SUBMITTED_SHEET = {
  id: 5, sheet_no: 'XJ20260925-0005', duty_date: '2026-09-25',
  template: 7, template_name: '机房巡检模板', status: 'submitted',
  status_text: '已提交', version: 2, abnormal_count: 0,
  recorded_rounds: ['r1'], persons: [], records: [],
};

// http.get 按 URL 分发；巡检页签挂载时的各类列表请求都返回空数据
function mockListResponses({templates = [TEMPLATE_TREE]} = {}) {
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/candidate-users/')) {
      return Promise.resolve({data: []});
    }
    if (url.includes('/inspection-templates/available/')) {
      return Promise.resolve({data: templates});
    }
    if (url.includes('/inspection-templates/')) {
      return Promise.resolve({data: [], total: 0});
    }
    if (url.endsWith('/inspection-sheets/5/')) {
      return Promise.resolve(SUBMITTED_SHEET);
    }
    if (url.includes('/inspection-sheets/')) {
      return Promise.resolve({data: [], total: 0});
    }
    return Promise.resolve({data: [], total: 0});
  });
}

function renderCenter(search) {
  const InspectionCenter = require('../index').default;
  ReactDOM.render(
    <MemoryRouter initialEntries={[`/el/inspection-center${search || ''}`]}>
      <InspectionCenter/>
    </MemoryRouter>,
    container);
}

function activeTabLabel() {
  const node = container.querySelector('.ant-tabs-tab-active');
  return node ? node.textContent : '';
}

function tabNode(label) {
  return Array.from(container.querySelectorAll('.ant-tabs-tab'))
    .find(node => node.textContent === label);
}

// 权限白名单驱动的 hasPermission mock（code 支持 | 组合）
function mockPermissions(codes) {
  const allowed = new Set(codes);
  require('libs').hasPermission.mockImplementation(
    code => String(code).split('|').some(c => allowed.has(c)));
}

describe('巡检中心页签与权限', () => {
  beforeEach(() => {
    mockListResponses();
  });

  it('有巡检业务权限：显示三个页签，默认打开今日巡检', async () => {
    mockPermissions([
      'equipment_lifecycle.inspection.view',
      'equipment_lifecycle.inspection_template.view',
    ]);
    await act(async () => {
      renderCenter('');
      await flush();
    });
    const labels = Array.from(container.querySelectorAll('.ant-tabs-tab'))
      .map(node => node.textContent);
    expect(labels).toEqual(['今日巡检', '巡检记录', '巡检模板']);
    expect(activeTabLabel()).toBe('今日巡检');
    // 今日巡检工作台真实挂载：发起模板/账号请求
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    expect(called.some(u => u.includes('/inspection-templates/available/'))).toBe(true);
    expect(called.some(u => u.includes('/candidate-users/'))).toBe(true);
  });

  it('仅有模板权限：只显示巡检模板页签并默认打开', async () => {
    mockPermissions(['equipment_lifecycle.inspection_template.view']);
    await act(async () => {
      renderCenter('');
      await flush();
    });
    const labels = Array.from(container.querySelectorAll('.ant-tabs-tab'))
      .map(node => node.textContent);
    expect(labels).toEqual(['巡检模板']);
    expect(activeTabLabel()).toBe('巡检模板');
    // 模板管理列表真实挂载请求
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    expect(called.some(u => u.endsWith('/inspection-templates/'))).toBe(true);
  });

  it('URL ?tab=templates 恢复模板页签', async () => {
    mockPermissions([
      'equipment_lifecycle.inspection.view',
      'equipment_lifecycle.inspection_template.view',
    ]);
    await act(async () => {
      renderCenter('?tab=templates');
      await flush();
    });
    expect(activeTabLabel()).toBe('巡检模板');
  });

  it('URL 指定无权限页签时回退默认页签', async () => {
    mockPermissions(['equipment_lifecycle.inspection.view']);
    await act(async () => {
      renderCenter('?tab=templates');
      await flush();
    });
    expect(activeTabLabel()).toBe('今日巡检');
  });

  it('无任何巡检权限：展示无权限提示（路由层已拦截，此处兜底）', async () => {
    mockPermissions([]);
    await act(async () => {
      renderCenter('');
      await flush();
    });
    expect(container.textContent).toContain('您没有巡检业务的访问权限');
  });
});

describe('巡检中心页签切换与状态', () => {
  beforeEach(() => {
    mockListResponses();
  });

  it('?tab=history&detail=<id> 打开巡检记录页签并打开详情抽屉', async () => {
    mockPermissions([
      'equipment_lifecycle.inspection.view',
      'equipment_lifecycle.inspection_template.view',
    ]);
    await act(async () => {
      renderCenter('?tab=history&detail=5');
      await flush();
    });
    expect(activeTabLabel()).toBe('巡检记录');
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    // 列表与详情均走既有请求路径
    expect(called.some(u => u.endsWith('/inspection-sheets/'))).toBe(true);
    expect(called.some(u => u.endsWith('/inspection-sheets/5/'))).toBe(true);
    expect(store.browseVisible).toBe(true);
    // 详情抽屉渲染在 body Portal：标题带单号
    expect(document.body.textContent).toContain('巡检单详情 - XJ20260925-0005');
  });

  it('页签切换只挂载当前页签页面，切回后今日巡检草稿恢复', async () => {
    mockPermissions([
      'equipment_lifecycle.inspection.view',
      'equipment_lifecycle.inspection_template.view',
    ]);
    localStorage.setItem('el_insp_ws_admin', JSON.stringify({
      duty_date: '2026-09-25', template_id: 7, persons: [],
      values: {r1: {t_21: {value_text: '正常', onsite_action: ''}}},
      saved_at: Date.now(),
    }));
    await act(async () => {
      renderCenter('');
      await flush();
    });
    // 草稿恢复提示出现（今日巡检既有暂存机制）
    expect(container.textContent).toContain('已恢复上次未提交的填写内容');

    // 切到巡检模板：工作台卸载，模板列表请求发出
    await act(async () => {
      tabNode('巡检模板').click();
      await flush();
    });
    expect(activeTabLabel()).toBe('巡检模板');
    expect(container.textContent).not.toContain('已恢复上次未提交的填写内容');
    const called = mockHttpGet.mock.calls.map(c => c[0]);
    expect(called.some(u => u.endsWith('/inspection-templates/'))).toBe(true);
    // 页签状态写入 URL
    expect(mockHistoryReplace).toHaveBeenCalledWith('/el/inspection-center?tab=templates');

    // 切回今日巡检：重新挂载并从 localStorage 恢复草稿
    await act(async () => {
      tabNode('今日巡检').click();
      await flush();
    });
    expect(activeTabLabel()).toBe('今日巡检');
    expect(container.textContent).toContain('已恢复上次未提交的填写内容');
    // 草稿未被清空
    expect(localStorage.getItem('el_insp_ws_admin')).not.toBeNull();
  });

  it('从巡检记录切走时清理遗留详情抽屉，避免覆盖工作台草稿单', async () => {
    mockPermissions([
      'equipment_lifecycle.inspection.view',
      'equipment_lifecycle.inspection_template.view',
    ]);
    await act(async () => {
      renderCenter('?tab=history&detail=5');
      await flush();
    });
    expect(store.browseVisible).toBe(true);
    expect(store.detail.id).toBe(5);

    await act(async () => {
      tabNode('今日巡检').click();
      await flush();
    });
    // 切换清理：browseVisible 复位、detail 清空（工作台挂载不受遗留单影响）
    expect(store.browseVisible).toBe(false);
    expect(store.detail).toBeNull();
  });

  it('离开巡检中心时同样清理遗留详情抽屉', async () => {
    mockPermissions([
      'equipment_lifecycle.inspection.view',
      'equipment_lifecycle.inspection_template.view',
    ]);
    await act(async () => {
      renderCenter('?tab=history&detail=5');
      await flush();
    });
    expect(store.browseVisible).toBe(true);
    await act(async () => {
      ReactDOM.unmountComponentAtNode(container);
      await flush();
    });
    expect(store.browseVisible).toBe(false);
    expect(store.detail).toBeNull();
  });
});

describe('旧巡检路径重定向', () => {
  it('跳到巡检中心对应页签并保留 detail 参数', async () => {
    const InspectionCenterRedirect = require('../LegacyRedirect').default;
    await act(async () => {
      ReactDOM.render(
        <InspectionCenterRedirect tab="history" location={{search: '?detail=9'}}/>,
        container);
      await flush();
    });
    expect(mockHistoryReplace).toHaveBeenCalledWith(
      '/el/inspection-center?detail=9&tab=history');
  });

  it('无附加参数时跳到对应页签', async () => {
    const InspectionCenterRedirect = require('../LegacyRedirect').default;
    await act(async () => {
      ReactDOM.render(
        <InspectionCenterRedirect tab="templates" location={{search: ''}}/>,
        container);
      await flush();
    });
    expect(mockHistoryReplace).toHaveBeenCalledWith('/el/inspection-center?tab=templates');
  });
});

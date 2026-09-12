/**
 * 提醒事项管理页面测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例，无 @testing-library），mock libs.http 与
 * components 公共组件，验证：
 * - 挂载即拉取规则列表与用户列表
 * - 重复列格式化：不重复 / 每天 / 每2周（formatRepeat 经真实表格渲染验证）
 * - 已停用规则显示"已停用"标签、接收人数量渲染
 * - 启用开关切换 → http.patch 载荷（enabled 翻转、默认值兜底、recipient_users JSON 字符串）
 * - 删除 → Popconfirm 确认 → http.delete 后刷新列表
 * - 编辑弹窗提交 → http.patch 载荷（日期格式化、接收人解析 nickname、JSON 字符串化）
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import ReminderAdmin from '../index';
import { http } from 'libs';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(),
    post: jest.fn(() => Promise.resolve()),
    patch: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
  hasPermission: () => true,
}));

jest.mock('components', () => {
  const BreadcrumbMock = ({children}) => <div>{children}</div>;
  BreadcrumbMock.Item = ({children}) => <span>{children}</span>;
  return {
    Breadcrumb: BreadcrumbMock,
    AuthDiv: ({children}) => <div>{children}</div>,
  };
});

// jsdom 环境垫片：antd Modal/弹窗链需要 matchMedia，rc-table 测量需要 ResizeObserver
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
if (!global.ResizeObserver) {
  // eslint-disable-next-line no-empty-function
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

const RULES = [
  {id: 1, name: '日报提醒', target_date: '2026-10-01', enabled: true, repeat_type: 'none', repeat_interval: 1, content: '记得日报', recipient_users: [{id: 11, nickname: '用户甲'}]},
  {id: 2, name: '周报提醒', target_date: '2026-10-02', enabled: false, repeat_type: 'weekly', repeat_interval: 2, content: '', recipient_users: [{id: 11, nickname: '用户甲'}, {id: 12, nickname: '用户乙'}]},
  {id: 3, name: '日常巡检', target_date: '2026-10-03', enabled: true, repeat_type: 'daily', repeat_interval: 1, content: '', recipient_users: []},
];
const USERS = [{id: 11, nickname: '用户甲'}, {id: 12, nickname: '用户乙'}];

let container = null;

async function renderPage() {
  await act(async () => {
    ReactDOM.render(<ReminderAdmin />, container);
  });
  await act(async () => {});
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

function findRow(name) {
  return Array.from(document.querySelectorAll('tbody tr'))
    .find(tr => tr.textContent.includes(name));
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  http.get.mockReset();
  http.patch.mockReset();
  http.delete.mockReset();
  http.get.mockImplementation((url) => Promise.resolve(
    String(url).includes('users') ? USERS : RULES
  ));
  http.patch.mockImplementation(() => Promise.resolve());
  http.delete.mockImplementation(() => Promise.resolve());
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
});

describe('提醒事项列表', () => {
  it('挂载即拉取规则列表与用户列表', async () => {
    await renderPage();
    expect(http.get).toHaveBeenCalledWith('/api/reminder/');
    expect(http.get).toHaveBeenCalledWith('/api/reminder/users/');
    expect(findRow('日报提醒')).toBeTruthy();
  });

  it('重复列格式化：不重复 / 每2周 / 每天', async () => {
    await renderPage();
    expect(findRow('日报提醒').textContent).toContain('不重复');
    expect(findRow('周报提醒').textContent).toContain('每2周');
    expect(findRow('日常巡检').textContent).toContain('每天');
  });

  it('停用规则显示"已停用"标签，接收人数量渲染', async () => {
    await renderPage();
    const disabledRow = findRow('周报提醒');
    expect(disabledRow.textContent).toContain('已停用');
    expect(disabledRow.textContent).toContain('2 人');
    expect(findRow('日报提醒').textContent).toContain('1 人');
    expect(findRow('日报提醒').textContent).not.toContain('已停用');
  });
});

describe('提醒事项启用开关', () => {
  it('切换开关 → http.patch 携带翻转的 enabled 与兜底默认值', async () => {
    await renderPage();
    const row = findRow('日报提醒');
    const switchBtn = row.querySelector('.ant-switch');
    expect(switchBtn).toBeTruthy();
    await click(switchBtn);
    await act(async () => {});
    expect(http.patch).toHaveBeenCalledTimes(1);
    const [url, payload] = http.patch.mock.calls[0];
    expect(url).toBe('/api/reminder/1/');
    expect(payload).toEqual({
      name: '日报提醒',
      enabled: false,
      target_date: '2026-10-01',
      repeat_type: 'none',
      repeat_interval: 1,
      content: '记得日报',
      recipient_users: JSON.stringify([{id: 11, nickname: '用户甲'}]),
    });
    // 切换成功后刷新列表
    expect(http.get).toHaveBeenCalledWith('/api/reminder/');
  });
});

describe('提醒事项删除', () => {
  it('Popconfirm 确认后 http.delete 并刷新列表', async () => {
    await renderPage();
    const row = findRow('日常巡检');
    const deleteLink = Array.from(row.querySelectorAll('a'))
      .find(a => a.textContent === '删除');
    expect(deleteLink).toBeTruthy();
    await click(deleteLink);
    await act(async () => {});
    // Popconfirm 弹出，点击确认按钮
    const confirmBtn = document.querySelector('.ant-popover .ant-btn-primary');
    expect(confirmBtn).toBeTruthy();
    await click(confirmBtn);
    await act(async () => {});
    expect(http.delete).toHaveBeenCalledWith('/api/reminder/3/');
    expect(http.get).toHaveBeenCalledWith('/api/reminder/');
  });
});

describe('提醒规则弹窗', () => {
  it('编辑规则：提交载荷日期格式化、接收人解析 nickname 并 JSON 字符串化', async () => {
    await renderPage();
    const row = findRow('日报提醒');
    const editLink = Array.from(row.querySelectorAll('a'))
      .find(a => a.textContent === '编辑');
    expect(editLink).toBeTruthy();
    await click(editLink);
    await act(async () => {});

    // 编辑弹窗打开
    const titles = Array.from(document.querySelectorAll('.ant-modal-title'));
    expect(titles.some(t => t.textContent === '编辑提醒规则')).toBe(true);

    const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary');
    expect(okBtn).toBeTruthy();
    await click(okBtn);
    await act(async () => {});

    expect(http.patch).toHaveBeenCalledTimes(1);
    const [url, payload] = http.patch.mock.calls[0];
    expect(url).toBe('/api/reminder/1/');
    expect(payload.name).toBe('日报提醒');
    expect(payload.enabled).toBe(true);
    expect(payload.target_date).toBe('2026-10-01');
    expect(payload.repeat_type).toBe('none');
    expect(payload.repeat_interval).toBe(1);
    expect(payload.content).toBe('记得日报');
    expect(JSON.parse(payload.recipient_users)).toEqual([{id: 11, nickname: '用户甲'}]);
  });

  it('新建按钮打开"新建提醒规则"弹窗', async () => {
    await renderPage();
    const createBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.includes('新建提醒规则'));
    expect(createBtn).toBeTruthy();
    await click(createBtn);
    await act(async () => {});
    const titles = Array.from(document.querySelectorAll('.ant-modal-title'));
    expect(titles.some(t => t.textContent === '新建提醒规则')).toBe(true);
  });
});

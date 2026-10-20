/**
 * 工作页签条组件行为测试（2026-10-19 导航改造）。
 *
 * 真实渲染 WorkTabs（antd Tabs editable-card + 真实 workTabStore），验证：
 * - 页签标题渲染、固定工作台页签无关闭图标
 * - 点击页签跳转该页签记住的完整 URL
 * - 点击关闭图标移除页签，关闭激活页签跳转邻页
 * - history.listen 回调（模拟真实导航）驱动开页签/去重与激活
 * - 组件内导航会写入 sessionStorage 持久化
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {message} from 'antd';

const mockHistoryPush = jest.fn();
let historyListener = null;
let blockCallback = null;
const mockUnlisten = jest.fn();
const mockUnblock = jest.fn();

jest.mock('libs', () => ({
  hasPermission: jest.fn(() => true),
  history: {
    push: mockHistoryPush,
    listen: jest.fn(cb => {
      historyListener = cb;
      return mockUnlisten;
    }),
    // 真实 history.block：登记导航拦截回调，返回解除函数
    block: jest.fn(cb => {
      blockCallback = cb;
      return mockUnblock;
    }),
    location: {pathname: '/home', search: ''},
  },
}));

jest.mock('../../routes', () => [
  {icon: 'home', title: '工作台', auth: 'dashboard.dashboard.view', path: '/home', component: 'Home'},
  {icon: 'el', title: '设备管理', child: [
    {title: '系统档案', auth: 'el.system.view', path: '/el/systems', component: 'Systems'},
    {title: '维护台账', child: [
      {title: '周月维护台账', auth: 'el.ledger.view', path: '/el/week-month-ledgers', component: 'W'},
      {title: 'Excel台账模板', auth: 'el.template.view', path: '/el/excel-ledger-templates', component: 'ET'},
      {title: '原生台账模板', auth: 'el.template.view', path: '/el/native-ledger-templates', component: 'NT'},
    ]},
    {title: '运行处置记录', auth: 'el.record.view', path: '/el/records', component: 'R'},
  ]},
  {icon: 'data', title: '数据分析', auth: 'data.view', path: '/data-analysis', component: 'D'},
  {path: '/upgrade/workbench/:id', component: 'WB', tabTitle: '升级工作台', tabCrumbs: ['设备管理']},
  {path: '/el/excel-ledgers', auth: 'el.ledger.view', component: 'Redirect', hideInTab: true},
]);

const store = require('../workTabStore').default;
const WorkTabs = require('../WorkTabs').default;

if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
  });
}

let container = null;
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function tabNodes() {
  return Array.from(container.querySelectorAll('.ant-tabs-tab'));
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  sessionStorage.clear();
  jest.clearAllMocks();
  historyListener = null;
  blockCallback = null;
  jest.spyOn(message, 'warning').mockImplementation(() => {});
  store.restore({pathname: '/home', search: ''});
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  document.body.removeChild(container);
  message.warning.mockRestore();
  container = null;
});

function renderTabs() {
  act(() => {
    ReactDOM.render(<WorkTabs/>, container);
  });
}

describe('WorkTabs 渲染与切换', () => {
  it('渲染页签标题，固定工作台页签无关闭图标，其余页签有关闭图标', async () => {
    store.syncLocation({pathname: '/el/systems', search: ''});
    renderTabs();
    await act(async () => {
      await flush();
    });
    const tabs = tabNodes();
    expect(tabs.map(t => t.textContent.replace(/×|关闭图标/g, ''))).toEqual(['工作台', '系统档案']);
    expect(tabs[0].querySelector('.ant-tabs-tab-remove')).toBe(null);
    expect(tabs[1].querySelector('.ant-tabs-tab-remove')).not.toBe(null);
  });

  it('点击页签跳转该页签记住的完整 URL（含查询参数）', () => {
    store.syncLocation({pathname: '/el/systems', search: '?detail=3'});
    renderTabs();
    const target = tabNodes().find(t => t.textContent.includes('系统档案'));
    act(() => {
      target.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(mockHistoryPush).toHaveBeenCalledWith('/el/systems?detail=3');
  });

  it('点击关闭图标移除页签；关闭激活页签时跳转左侧邻页签', async () => {
    renderTabs();
    await act(async () => {
      await flush();
    });
    // 以真实导航链路打开两个页面并激活最后一个
    act(() => {
      historyListener({pathname: '/el/systems', search: ''});
      historyListener({pathname: '/el/week-month-ledgers', search: ''});
    });
    expect(store.activeKey).toBe('/el/week-month-ledgers');
    const closing = tabNodes().find(t => t.textContent.includes('周月维护台账'));
    act(() => {
      closing.querySelector('.ant-tabs-tab-remove').dispatchEvent(
        new MouseEvent('click', {bubbles: true}));
    });
    expect(store.tabs.map(t => t.key)).toEqual(['/home', '/el/systems']);
    expect(store.activeKey).toBe('/el/systems');
    expect(mockHistoryPush).toHaveBeenCalledWith('/el/systems');
  });

  it('固定工作台页签点击关闭图标不生效', () => {
    renderTabs();
    const home = tabNodes()[0];
    expect(home.querySelector('.ant-tabs-tab-remove')).toBe(null);
    store.closeTab('/home');
    expect(store.tabs.map(t => t.key)).toEqual(['/home']);
  });

  it('history.listen 导航回调驱动开页签/去重并写入 sessionStorage', async () => {
    renderTabs();
    await act(async () => {
      await flush();
    });
    expect(historyListener).not.toBe(null);
    act(() => {
      historyListener({pathname: '/el/systems', search: '?detail=3'});
    });
    expect(store.tabs.map(t => t.key)).toEqual(['/home', '/el/systems']);
    expect(store.activeKey).toBe('/el/systems');
    // 同一路由再次导航不重复开页签，仅更新 URL
    act(() => {
      historyListener({pathname: '/el/systems', search: '?detail=5'});
    });
    expect(store.tabs.filter(t => t.key === '/el/systems')).toHaveLength(1);
    expect(store.tabs.find(t => t.key === '/el/systems').url).toBe('/el/systems?detail=5');
    const saved = JSON.parse(sessionStorage.getItem('spug.workTabs'));
    expect(saved).toEqual([
      {key: '/home', url: '/home', ts: expect.any(Number)},
      {key: '/el/systems', url: '/el/systems?detail=5', ts: expect.any(Number)},
    ]);
  });
});

describe('WorkTabs 数量上限与导航拦截', () => {
  it('挂载时登记导航拦截回调，卸载时解除', async () => {
    renderTabs();
    await act(async () => {
      await flush();
    });
    expect(blockCallback).not.toBe(null);
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    expect(mockUnblock).toHaveBeenCalled();
  });

  it('全部候选页签均有未保存内容时阻止开新页签并提示', async () => {
    renderTabs();
    await act(async () => {
      await flush();
    });
    // 以真实导航链路开满 6 个非固定页签，并全部登记未保存内容
    act(() => {
      ['/el/systems', '/el/week-month-ledgers', '/el/excel-ledger-templates',
        '/el/native-ledger-templates', '/el/records', '/data-analysis'].forEach(
        path => historyListener({pathname: path, search: ''}));
    });
    expect(store.tabs).toHaveLength(7);
    store.tabs.filter(tab => tab.closable !== false).forEach(tab => {
      store.addUnsavedSource(tab.key);
    });
    // 导航到第 7 个页签：block 回调返回 false（history 取消跳转），不进入 listen
    let verdict;
    act(() => {
      verdict = blockCallback({pathname: '/upgrade/workbench/99', search: ''});
    });
    expect(verdict).toBe(false);
    expect(message.warning).toHaveBeenCalledTimes(1);
    expect(message.warning.mock.calls[0][0]).toContain('未保存');
    expect(store.tabs).toHaveLength(7);
    // 目标为已开页签时放行（返回 undefined，不阻止）
    let allowed;
    act(() => {
      allowed = blockCallback({pathname: '/el/systems', search: ''});
    });
    expect(allowed).toBe(undefined);
    expect(message.warning).toHaveBeenCalledTimes(1);
  });

  it('存在可淘汰页签时放行导航，listen 随后淘汰最久未使用者并加入新页签', async () => {
    renderTabs();
    await act(async () => {
      await flush();
    });
    act(() => {
      ['/el/systems', '/el/week-month-ledgers', '/el/excel-ledger-templates',
        '/el/native-ledger-templates', '/el/records', '/data-analysis'].forEach(
        path => historyListener({pathname: path, search: ''}));
    });
    // 只有系统档案登记未保存，其余 5 个均为可淘汰候选
    store.addUnsavedSource('/el/systems');
    const oldest = store.tabs.find(tab => tab.key === '/el/week-month-ledgers');
    store.tabs.forEach(tab => {
      if (tab.closable !== false && tab.key !== oldest.key) tab.ts = oldest.ts + 1000;
    });
    // 放行（返回 undefined），随后真实 history 触发 listen 完成淘汰
    let verdict;
    act(() => {
      verdict = blockCallback({pathname: '/upgrade/workbench/99', search: ''});
    });
    expect(verdict).toBe(undefined);
    act(() => {
      historyListener({pathname: '/upgrade/workbench/99', search: ''});
    });
    expect(store.tabs.map(t => t.key)).not.toContain('/el/week-month-ledgers');
    expect(store.tabs.map(t => t.key)).toContain('/upgrade/workbench/99');
    expect(store.tabs.map(t => t.key)).toContain('/el/systems');
    expect(store.tabs.filter(t => t.closable !== false)).toHaveLength(6);
  });

  it('卸载时取消 history 订阅与容器滚动监听', async () => {
    renderTabs();
    await act(async () => {
      await flush();
    });
    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    expect(mockUnlisten).toHaveBeenCalled();
  });
});

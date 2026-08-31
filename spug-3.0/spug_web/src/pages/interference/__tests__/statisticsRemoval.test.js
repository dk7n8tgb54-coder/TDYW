/**
 * 干扰统计页面下线后的前端契约测试
 *
 * 验证：
 * 1. 干扰管理菜单只剩两个业务入口（地面无线电通信异常/干扰、空中干扰），
 *    不再包含「干扰统计」；
 * 2. 整个前端路由表中不再引用 /interference/statistics；
 * 3. 数据分析仍提供「干扰分析」Tab（统计能力迁移目标）；
 * 4. 首页干扰概览卡片的跳转目标改为 数据分析 - 干扰分析，不再指向失效地址。
 *
 * 环境说明：沿用本仓库惯例使用 ReactDOM + react-dom/test-utils + jsdom 真实渲染；
 * 路由表通过真实 import 执行 routes.js 后断言导出的配置对象，不读取源码文本。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => Promise.resolve({
      today_total: 3,
      bridge_today_total: 2,
      air_today_total: 1,
    })),
  },
  history: { push: jest.fn() },
  hasPermission: () => true,
}));

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

const REMOVED_PATH = '/interference/statistics';

const findMenu = (routes, title) => routes.find(item => item.title === title);

describe('干扰管理菜单', () => {
  let routes;
  let interferenceMenu;

  beforeAll(() => {
    routes = require('../../../routes').default;
    interferenceMenu = findMenu(routes, '干扰管理');
  });

  test('只保留两个业务入口', () => {
    expect(interferenceMenu).toBeTruthy();
    expect(interferenceMenu.child).toHaveLength(2);
    expect(interferenceMenu.child.map(c => c.title)).toEqual([
      '地面无线电通信异常/干扰',
      '空中干扰',
    ]);
    expect(interferenceMenu.child.map(c => c.path)).toEqual([
      '/interference/bridge',
      '/interference/air',
    ]);
  });

  test('不再显示干扰统计入口', () => {
    const titles = interferenceMenu.child.map(c => c.title);
    expect(titles).not.toContain('干扰统计');
    expect(interferenceMenu.auth).not.toContain('interference.statistics.view');
  });

  test('路由表中不再引用 /interference/statistics', () => {
    const paths = [];
    const walk = (items) => {
      items.forEach(item => {
        if (item.path) paths.push(item.path);
        if (item.child) walk(item.child);
      });
    };
    walk(routes);
    expect(paths).not.toContain(REMOVED_PATH);
  });
});

describe('数据分析 - 干扰分析', () => {
  test('Tab 配置仍然存在且指向数据分析接口', () => {
    const { TABS } = require('../../../pages/dataAnalysis/store');
    const interferenceTab = TABS.find(tab => tab.key === 'interference');
    expect(interferenceTab).toBeTruthy();
    expect(interferenceTab.label).toBe('干扰分析');
    expect(interferenceTab.perm).toBe('data_analysis.interference.view');
    expect(interferenceTab.endpoint).toBe('/api/data-analysis/interference/');
  });
});

describe('首页干扰概览卡片跳转', () => {
  let container;
  let history;
  let http;

  beforeEach(() => {
    const libs = require('libs');
    history = libs.history;
    http = libs.http;
    history.push.mockClear();
    http.get.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    ReactDOM.unmountComponentAtNode(container);
    container.remove();
  });

  test('点击卡片跳转到数据分析干扰分析页，而不是已删除的统计页', async () => {
    const InterferenceOverview = require('../../../pages/home/InterferenceOverview').default;

    await act(async () => {
      ReactDOM.render(<InterferenceOverview />, container);
    });

    expect(http.get).toHaveBeenCalledWith('/api/home/statistic/');

    await act(async () => {
      container.querySelector('.ant-card').click();
    });

    expect(history.push).toHaveBeenCalledTimes(1);
    const target = history.push.mock.calls[0][0];
    expect(target).not.toBe(REMOVED_PATH);
    expect(target).toBe('/data-analysis?tab=interference');
  });
});

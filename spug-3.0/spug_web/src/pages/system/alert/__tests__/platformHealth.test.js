/**
 * 平台健康页组件渲染测试
 *
 * 真实渲染 PlatformHealth（mobx + antd），mock bizcharts 捕获 Chart/Axis
 * props，验证：图表数据使用 formatAxisTime 生成、横轴 label.formatter
 * 只在抽样刻度上返回标签（其余为空串）、无数据时不渲染图表。
 *
 * 注意：组件测试不能用 jest.resetModules（会产生双 React 实例导致
 * Invalid hook call），改为顶层 require 一次，并在 beforeEach 重置
 * store 单例状态。
 */
const mockHttpGet = jest.fn();
const mockHistoryPush = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  history: {push: mockHistoryPush},
}));

jest.mock('bizcharts', () => {
  const captures = {Chart: [], Axis: []};
  const capture = key => props => {
    captures[key].push(props);
    return null;
  };
  return {
    Chart: props => {
      captures.Chart.push(props);
      return props.children || null;
    },
    Axis: capture('Axis'),
    Geom: () => null,
    Tooltip: () => null,
    Legend: () => null,
    __captures: captures,
  };
});

import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import {formatAxisTime} from '../chartAxis';

const Page = require('../PlatformHealth').default;
const store = require('../healthStore').default;
const {__captures: captures} = require('bizcharts');

const BUCKET = '2026-09-13 18:00:00';
// 12 个 5 分钟窗口：抽样步长 ceil(12/10)=2，应有 6 个刻度标签、6 个空标签
const ITEMS = Array.from({length: 12}, (_, i) => ({
  bucket_start: bucketString(i),
  request_count: 10 + i,
  app_server_error_count: 0,
  gateway_error_count: 0,
}));

function bucketString(offsetMinutes) {
  const d = new Date(new Date(BUCKET.replace(' ', 'T')).getTime() + offsetMinutes * 60000);
  const pad = n => String(n).padStart(2, '0');
  // 后端 DateTimeEncoder 输出 "YYYY-MM-DD HH:mm:ss"
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

function polyfillJsdom() {
  if (!window.matchMedia) {
    window.matchMedia = query => ({
      matches: false, media: query,
      addListener: jest.fn(), removeListener: jest.fn(),
      addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn(),
    });
  }
  if (!window.ResizeObserver) {
    window.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
}

const flushPromises = () => new Promise(resolve => setTimeout(resolve, 0));

async function renderPage() {
  const div = document.createElement('div');
  await act(async () => {
    ReactDOM.render(<Page/>, div);
    await flushPromises();
  });
  return div;
}

beforeEach(() => {
  polyfillJsdom();
  captures.Chart.length = 0;
  captures.Axis.length = 0;
  store.loading = false;
  store.hours = 48;
  store.items = [];
  store.summary = [];
  store.state = 'unknown';
});

afterEach(() => {
  mockHttpGet.mockReset();
  mockHistoryPush.mockReset();
});

describe('平台健康图表', () => {
  it('图表数据用 formatAxisTime 生成，横轴仅在抽样刻度上输出标签', async () => {
    mockHttpGet.mockImplementation(url => Promise.resolve(
      String(url).includes('summary') ? {items: []} : {items: ITEMS, state: 'healthy'}
    ));
    const div = await renderPage();

    const chart = captures.Chart[captures.Chart.length - 1];
    expect(chart.data.map(d => d.time)).toEqual(
      ITEMS.map(item => formatAxisTime(new Date(item.bucket_start)))
    );

    const timeAxis = captures.Axis.find(props => props.name === 'time');
    expect(timeAxis).toBeDefined();
    expect(timeAxis.label.formatter).toBeInstanceOf(Function);
    expect(timeAxis.label.autoRotate).toBe(false);
    expect(chart.forceFit).toBe(true);

    const labels = chart.data.map(d => timeAxis.label.formatter(d.time));
    const nonEmpty = labels.filter(Boolean);
    expect(nonEmpty).toHaveLength(6);
    // 默认 48h 跨度：刻度格式为 MM-DD HH:mm
    nonEmpty.forEach(label => expect(label).toMatch(/^\d{2}-\d{2} \d{2}:\d{2}$/));
    // 步长 2：偶数索引有标签，奇数索引为空
    labels.forEach((label, i) => expect(Boolean(label)).toBe(i % 2 === 0));
    ReactDOM.unmountComponentAtNode(div);
  });

  it('数据为空时不渲染图表', async () => {
    mockHttpGet.mockResolvedValue({});
    const div = await renderPage();
    expect(captures.Chart).toHaveLength(0);
    ReactDOM.unmountComponentAtNode(div);
  });

  it('点击查看系统告警后跳转到告警 Tab', async () => {
    mockHttpGet.mockImplementation(url => Promise.resolve(
      String(url).includes('summary') ? {items: []} : {items: ITEMS, state: 'healthy'}
    ));
    const div = await renderPage();
    const button = Array.from(div.querySelectorAll('button')).find(item => item.textContent.includes('查看系统告警'));
    expect(button).toBeDefined();
    await act(async () => {
      Simulate.click(button);
    });
    expect(mockHistoryPush).toHaveBeenCalledWith('/maintenance/alert?tab=alerts');
    ReactDOM.unmountComponentAtNode(div);
  });
});

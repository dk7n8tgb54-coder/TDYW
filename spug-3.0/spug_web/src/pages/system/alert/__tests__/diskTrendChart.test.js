/**
 * 系统告警磁盘使用趋势图组件渲染测试
 *
 * 真实渲染 AlertIndex（embedded）中的 DiskTrendChart（mobx + antd），
 * mock bizcharts 捕获 Chart/Axis props，验证多序列展平后横轴刻度按
 * 时间跨度抽样合并、formatter 对非刻度点返回空串、数值换算为 GB。
 *
 * 注意：组件测试不能用 jest.resetModules（双 React 实例会导致
 * Invalid hook call），顶层 require 一次并在 beforeEach 重置 store。
 */
const mockHttpGet = jest.fn();

jest.mock('libs', () => ({
  http: {get: mockHttpGet, post: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => {
  const SearchForm = () => null;
  SearchForm.Item = () => null;
  return {
    AuthDiv: () => null,
    AuthFragment: () => null,
    Breadcrumb: () => null,
    SearchForm,
    TableCard: () => null,
  };
});

jest.mock('bizcharts', () => {
  const captures = {Chart: [], Axis: [], Geom: [], Legend: []};
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
    Geom: capture('Geom'),
    Tooltip: () => null,
    Legend: capture('Legend'),
    __captures: captures,
  };
});

import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {formatAxisTime} from '../chartAxis';

const Index = require('../index').default;
const store = require('../store').default;
const {__captures: captures} = require('bizcharts');

const t0 = Math.floor(Date.now() / 1000) - 1200;
const t1 = t0 + 600;
const SERIES = [
  {name: 'documents', label: '文档存储', points: [{time: t0, value: 1e9}, {time: t1, value: 2e9}]},
  {name: 'chunks', label: '分片存储', points: [{time: t0, value: 5e8}, {time: t1, value: 6e8}]},
];

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

async function renderIndex() {
  const div = document.createElement('div');
  await act(async () => {
    ReactDOM.render(<Index embedded/>, div);
    await flushPromises();
  });
  return div;
}

beforeEach(() => {
  polyfillJsdom();
  captures.Chart.length = 0;
  captures.Axis.length = 0;
  captures.Geom.length = 0;
  captures.Legend.length = 0;
  store.records = [];
  store.trendData = [];
  store.trendLoading = false;
  store.trendHours = 24;
});

afterEach(() => {
  mockHttpGet.mockReset();
});

describe('磁盘使用趋势图', () => {
  it('多序列展平渲染，横轴刻度合并抽样，数值换算为 GB', async () => {
    mockHttpGet.mockImplementation(url => Promise.resolve(
      String(url).includes('trend') ? {series: SERIES} : {items: [], total: 0, summary: {}}
    ));
    const div = await renderIndex();

    const chart = captures.Chart[captures.Chart.length - 1];
    expect(chart.forceFit).toBe(true);
    expect(chart.data).toHaveLength(4);
    expect(chart.data.map(d => d.type)).toEqual(['文档存储', '文档存储', '分片存储', '分片存储']);
    expect(chart.data[0].time).toBe(formatAxisTime(new Date(t0 * 1000)));
    expect(chart.data[0].value).toBe(+(1e9 / 1024 / 1024 / 1024).toFixed(2));

    const timeAxis = captures.Axis.find(props => props.name === 'time');
    expect(timeAxis).toBeDefined();
    expect(timeAxis.label.autoRotate).toBe(false);
    // 两个序列时间点一致：同一时间跨序列查表结果一致（合并生效）
    const label0 = timeAxis.label.formatter(chart.data[0].time);
    expect(label0).toMatch(/^\d{2}:\d{2}$/);
    expect(timeAxis.label.formatter(chart.data[2].time)).toBe(label0);
    // 相邻时刻（相差 10 分钟）刻度标签不同
    const label1 = timeAxis.label.formatter(chart.data[1].time);
    expect(label1).toMatch(/^\d{2}:\d{2}$/);
    expect(label1).not.toBe(label0);
    ReactDOM.unmountComponentAtNode(div);
  });

  it('切换时间跨度后刻度格式随跨度变化（7 天为 MM-DD）', async () => {
    mockHttpGet.mockImplementation(url => Promise.resolve(
      String(url).includes('trend') ? {series: SERIES} : {items: [], total: 0, summary: {}}
    ));
    const div = await renderIndex();
    await act(async () => {
      await store.setTrendHours(168);
      await flushPromises();
    });

    const chart = captures.Chart[captures.Chart.length - 1];
    const timeAxis = captures.Axis.filter(props => props.name === 'time').pop();
    const label = timeAxis.label.formatter(chart.data[0].time);
    expect(label).toMatch(/^\d{2}-\d{2}$/);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/alert/trend/', {params: {hours: 168}});
    ReactDOM.unmountComponentAtNode(div);
  });

  it('四条曲线渲染：图例四项、总计与分类明显区分、GB 换算正确', async () => {
    // disk:total 为后端同一轮采集计算的精确总和（1e9+5e8+3e8=1.8e9），前端不重复相加
    const t2 = t1 + 600;
    const series4 = [
      {name: 'disk:documents', label: '文档存储', points: [{time: t0, value: 1e9}, {time: t1, value: 2e9}, {time: t2, value: 3e9}]},
      {name: 'disk:chunks', label: '分片存储', points: [{time: t0, value: 5e8}, {time: t1, value: 6e8}, {time: t2, value: 7e8}]},
      {name: 'disk:media', label: '媒体存储', points: [{time: t0, value: 3e8}, {time: t1, value: 4e8}, {time: t2, value: 5e8}]},
      {name: 'disk:total', label: '三类存储总计', points: [{time: t0, value: 18e8}, {time: t1, value: 3e9}, {time: t2, value: 42e8}]},
    ];
    mockHttpGet.mockImplementation(url => Promise.resolve(
      String(url).includes('trend') ? {series: series4} : {items: [], total: 0, summary: {}}
    ));
    const div = await renderIndex();

    const chart = captures.Chart[captures.Chart.length - 1];
    // 四组数据、四个图例（图例项由数据 type 派生）
    const types = [...new Set(chart.data.map(d => d.type))];
    expect(types).toEqual(['文档存储', '分片存储', '媒体存储', '三类存储总计']);
    const legend = captures.Legend[captures.Legend.length - 1];
    expect(legend.name).toBe('type');
    expect(legend.position).toBe('top');

    // 总计曲线 GB 换算正确：1.8e9 bytes -> 1.68 GB
    const totalPoint = chart.data.find(
      d => d.type === '三类存储总计' && d.time === formatAxisTime(new Date(t0 * 1000))
    );
    expect(totalPoint.value).toBe(+(18e8 / 1024 / 1024 / 1024).toFixed(2));

    // 总计曲线样式明显区分：虚线、加粗、独立颜色；三类存储保持平滑实线
    const lineGeom = captures.Geom.filter(props => props.type === 'line').pop();
    expect(lineGeom.shape[1]('三类存储总计')).toBe('dash');
    expect(lineGeom.shape[1]('文档存储')).toBe('smooth');
    expect(lineGeom.size[1]('三类存储总计')).toBe(3);
    expect(lineGeom.size[1]('文档存储')).toBe(2);
    const totalColor = lineGeom.color[1]('三类存储总计');
    expect(totalColor).not.toBe(lineGeom.color[1]('文档存储'));
    expect(totalColor).not.toBe(lineGeom.color[1]('分片存储'));
    expect(totalColor).not.toBe(lineGeom.color[1]('媒体存储'));
    ReactDOM.unmountComponentAtNode(div);
  });
});

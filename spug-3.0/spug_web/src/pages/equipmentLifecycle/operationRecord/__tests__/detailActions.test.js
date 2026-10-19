/**
 * 运行处置记录——详情顶部动作按钮样式契约测试（2026-10-18 样式统一）。
 * 与 detailWindow.test.js 不同：这里不 mock components，使用真实 AuthButton
 * （底层 antd Button）渲染各动作组件，断言 antd 样式类：
 * - 添加跟进/补充/处置记录与异常事件已完成的"重新跟进" = 蓝色实心主按钮
 *   （ant-btn-primary，且非危险/链接、默认尺寸）；
 * - 编辑/完成跟进/认定设备故障/确认恢复并结案 = 普通描边（非主色/危险/链接）；
 * - 删除/撤销故障登记 = 红色描边（ant-btn-dangerous，不再是链接或实心）；
 * - 无权限时按钮不渲染（不留空白节点）；确认恢复并结案须同时具备 recover
 *   与 close 双权限（auth 以 & 组合，缺一即隐藏）。
 * antd 对两字中文按钮自动插空格（"编 辑"），匹配前去除空白。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: (...args) => mockHttpGet(...args),
    post: (...args) => mockHttpPost(...args),
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {push: jest.fn()},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

import {
  AuthAddProgressButton, AuthEditButton, AuthDeleteButton,
  AuthCompleteButton, AuthIdentifyFaultButton, AuthRecoverAndCloseButton,
  AuthCancelButton,
} from '../RecordDetailActions';
import store from '../store';
import {PERM} from '../../constants';

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  const libs = require('libs');
  libs.Permission.isSuper = true;
  libs.hasPermission.mockReset();
  libs.hasPermission.mockReturnValue(true);
  store.detail = {};
});

afterEach(() => {
  try {
    ReactDOM.unmountComponentAtNode(container);
  } catch (e) {
    // ignore
  }
  document.body.removeChild(container);
  document.querySelectorAll('.ant-modal, .ant-message').forEach(
    node => node.parentNode && node.parentNode.removeChild(node));
});

async function renderAction(element) {
  await act(async () => {
    ReactDOM.render(element, container);
  });
}

// 按钮文本匹配（去除 antd 两字中文按钮自动插入的空格）
function actionButton(label) {
  return Array.from(container.querySelectorAll('button'))
    .find(btn => (btn.textContent || '').replace(/\s/g, '') === label);
}

function expectDefaultSize(btn) {
  expect(btn.className).not.toMatch(/ant-btn-(sm|lg)/);
}

function assertPrimary(btn) {
  expect(btn).toBeTruthy();
  expect(btn.className).toContain('ant-btn-primary');
  expect(btn.className).not.toContain('ant-btn-dangerous');
  expect(btn.className).not.toContain('ant-btn-link');
  expectDefaultSize(btn);
}

function assertOutline(btn) {
  expect(btn).toBeTruthy();
  expect(btn.className).not.toContain('ant-btn-primary');
  expect(btn.className).not.toContain('ant-btn-dangerous');
  expect(btn.className).not.toContain('ant-btn-link');
  expectDefaultSize(btn);
}

function assertDangerOutline(btn) {
  expect(btn).toBeTruthy();
  expect(btn.className).toContain('ant-btn-dangerous');
  expect(btn.className).not.toContain('ant-btn-primary');
  expect(btn.className).not.toContain('ant-btn-link');
  expectDefaultSize(btn);
}

describe('主按钮样式（真实 AuthButton 渲染）', () => {
  const cases = [
    ['routine', 'recorded', '添加补充记录'],
    ['abnormal', 'recorded', '添加跟进记录'],
    ['fault', 'handling', '添加处置记录'],
    ['abnormal', 'completed', '重新跟进'],
  ];
  cases.forEach(([type, status, label]) => {
    it(`${type}/${status}："${label}"为蓝色实心主按钮`, async () => {
      store.detail = {record_type: type, status};
      await renderAction(<AuthAddProgressButton/>);
      assertPrimary(actionButton(label));
    });
  });
});

describe('常规操作与危险操作样式（真实 AuthButton 渲染）', () => {
  it('编辑/完成跟进/认定设备故障/确认恢复并结案均为普通描边', async () => {
    store.detail = {record_type: 'routine', status: 'recorded'};
    await renderAction(<AuthEditButton/>);
    assertOutline(actionButton('编辑'));

    store.detail = {record_type: 'abnormal', status: 'following_up'};
    await renderAction(<AuthCompleteButton/>);
    assertOutline(actionButton('完成跟进'));

    await renderAction(<AuthIdentifyFaultButton/>);
    assertOutline(actionButton('认定设备故障'));

    await renderAction(
      <AuthRecoverAndCloseButton record={{record_no: 'JL20261018-0001'}}/>);
    assertOutline(actionButton('确认恢复并结案'));
  });

  it('删除为红色描边（不再是链接或实心）', async () => {
    store.detail = {record_type: 'routine', status: 'recorded'};
    await renderAction(<AuthDeleteButton/>);
    assertDangerOutline(actionButton('删除'));
  });

  it('撤销故障登记为红色描边（不再是链接或实心）', async () => {
    store.detail = {record_type: 'fault', status: 'handling'};
    await renderAction(
      <AuthCancelButton record={{record_no: 'JL20261018-0002'}}/>);
    assertDangerOutline(actionButton('撤销故障登记'));
  });
});

describe('权限隐藏后不留空白节点', () => {
  it('无权限时各动作按钮均不渲染', async () => {
    const libs = require('libs');
    libs.Permission.isSuper = false;
    libs.hasPermission.mockReturnValue(false);
    store.detail = {record_type: 'routine', status: 'recorded'};
    await renderAction(
      <span>
        <AuthAddProgressButton/>
        <AuthEditButton/>
        <AuthDeleteButton/>
      </span>);
    expect(container.querySelectorAll('button')).toHaveLength(0);
  });

  it('确认恢复并结案须同时具备 recover 与 close 权限（缺一即隐藏）', async () => {
    const libs = require('libs');
    libs.Permission.isSuper = false;
    const owned = new Set([PERM.OP_RECOVER]);
    libs.hasPermission.mockImplementation(
      code => String(code).split('&').every(c => owned.has(c)));
    store.detail = {record_type: 'fault', status: 'handling'};
    await renderAction(
      <AuthRecoverAndCloseButton record={{record_no: 'JL20261018-0003'}}/>);
    expect(actionButton('确认恢复并结案')).toBeUndefined();
    owned.add(PERM.OP_CLOSE);
    await renderAction(
      <AuthRecoverAndCloseButton record={{record_no: 'JL20261018-0003'}}/>);
    assertOutline(actionButton('确认恢复并结案'));
  });
});

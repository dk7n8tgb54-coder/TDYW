/**
 * 干扰管理 Excel 导入弹窗（ImportModal）行为测试
 *
 * 验证：
 * 1. 未选文件/未预校验时「开始预校验」「确认导入」禁用；
 * 2. 选择文件并预校验通过 → 统计展示、确认导入启用、提交携带 validate_token、
 *    成功后回调 onSuccess（由页面刷新列表）；
 * 3. 预校验存在错误 → 错误表展示（Excel行号/字段/错误原因/原始值）、
 *    确认导入禁用、「下载错误报告」可用且指向 error-report 接口；
 * 4. 非法扩展名文件被拒绝；
 * 5. business="air" 时使用空中干扰的接口地址。
 *
 * 文件选择通过组件的 beforeUpload 入口注入（antd Upload 在 jsdom 下的
 * 原生 input 事件不稳定），其余交互均通过真实按钮点击触发。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import ImportModal from '../ImportModal';
import {http, exportFile} from 'libs';

jest.mock('libs', () => ({
  http: {post: jest.fn(), get: jest.fn(), delete: jest.fn()},
  exportFile: jest.fn(() => Promise.resolve()),
}));

// jsdom 环境垫片：antd Modal/Descriptions 响应式监听需要 matchMedia
/* eslint-disable no-empty-function */
if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {},
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
/* eslint-enable no-empty-function */

const OK_RESULT = {
  total_rows: 2, valid_count: 2, error_count: 0, warning_count: 0,
  errors: [], warnings: [], validate_token: 'token-ok',
};
const ERR_RESULT = {
  total_rows: 2, valid_count: 1, error_count: 1, warning_count: 1,
  errors: [{
    row: 3, field: '日期时间',
    message: '日期时间格式必须为 YYYY-MM-DD HH:MM:SS',
    value: '2026/08/01',
  }],
  warnings: [{row: null, field: '', message: '未识别的列「填表人」（第 10 列），该列内容不会导入', value: ''}],
  validate_token: 'token-err',
};

let container = null;

function makeFile(name = '导入.xlsx') {
  const file = new Blob(['xlsx-bytes']);
  file.name = name;
  return file;
}

function renderModal(props = {}) {
  container = document.createElement('div');
  document.body.appendChild(container);
  const instance = ReactDOM.render(
    <ImportModal business="bridge" visible onClose={jest.fn()} onSuccess={jest.fn()} {...props}/>,
    container);
  return instance;
}

function findButton(text) {
  return Array.from(document.querySelectorAll('button'))
    .find(btn => btn.textContent.includes(text));
}

function chooseFile(instance, name) {
  act(() => {
    instance.handleBeforeUpload(makeFile(name));
  });
}

async function flush() {
  await act(async () => {});
}

beforeEach(() => {
  http.post.mockReset();
  exportFile.mockClear();
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
});

describe('导入弹窗基础状态', () => {
  test('未选择文件时预校验与确认导入均禁用', () => {
    renderModal();
    expect(findButton('开始预校验').disabled).toBe(true);
    expect(findButton('确认导入').disabled).toBe(true);
    expect(document.querySelector('.ant-modal-title').textContent)
      .toContain('地面无线电通信异常/干扰');
  });

  test('选择非法扩展名文件被拒绝', () => {
    const instance = renderModal();
    chooseFile(instance, '导入.xls');
    expect(instance.state.file).toBeNull();
    expect(findButton('开始预校验').disabled).toBe(true);
  });
});

describe('预校验与确认导入', () => {
  test('预校验通过后确认导入启用并携带 validate_token 提交', async () => {
    const onSuccess = jest.fn();
    const instance = renderModal({onSuccess});
    chooseFile(instance);
    expect(findButton('开始预校验').disabled).toBe(false);

    http.post.mockResolvedValueOnce(OK_RESULT);
    act(() => {
      findButton('开始预校验').click();
    });
    await flush();

    const [validateUrl, validateBody] = http.post.mock.calls[0];
    expect(validateUrl).toBe('/api/interference/bridge/import/validate/');
    expect(validateBody.get('file')).toBeTruthy();

    // 统计信息展示
    const statsText = document.querySelector('.import-stats').textContent;
    expect(statsText).toContain('总行数2');
    expect(statsText).toContain('可导入2');
    expect(statsText).toContain('错误0');

    // 预校验通过后确认按钮启用
    const confirmBtn = findButton('确认导入');
    expect(confirmBtn.disabled).toBe(false);

    http.post.mockResolvedValueOnce({imported_count: 2});
    act(() => {
      confirmBtn.click();
    });
    await flush();

    const [commitUrl, commitBody] = http.post.mock.calls[1];
    expect(commitUrl).toBe('/api/interference/bridge/import/commit/');
    expect(commitBody.get('validate_token')).toBe('token-ok');
    expect(onSuccess).toHaveBeenCalledWith(2);
  });

  test('预校验存在错误时展示错误明细、确认禁用、可下载错误报告', async () => {
    const instance = renderModal();
    chooseFile(instance);

    http.post.mockResolvedValueOnce(ERR_RESULT);
    act(() => {
      findButton('开始预校验').click();
    });
    await flush();

    // 错误表至少包含 Excel 行号/字段/错误原因/原始值摘要
    const tableText = document.querySelector('.import-result .ant-table').textContent;
    expect(tableText).toContain('3');
    expect(tableText).toContain('日期时间');
    expect(tableText).toContain('YYYY-MM-DD HH:MM:SS');
    expect(tableText).toContain('2026/08/01');
    // 警告展示
    expect(document.querySelector('.import-result').textContent).toContain('填表人');
    // 确认导入禁用
    expect(findButton('确认导入').disabled).toBe(true);
    // 下载错误报告
    const reportBtn = findButton('下载错误报告');
    expect(reportBtn).toBeTruthy();
    act(() => {
      reportBtn.click();
    });
    await flush();
    expect(exportFile).toHaveBeenCalledWith(expect.objectContaining({
      url: '/api/interference/bridge/import/error-report/',
      method: 'post',
    }));
  });

  test('business=air 时使用空中干扰接口与标题', async () => {
    const instance = renderModal({business: 'air'});
    expect(document.querySelector('.ant-modal-title').textContent).toContain('空中干扰');
    chooseFile(instance);
    http.post.mockResolvedValueOnce(OK_RESULT);
    act(() => {
      findButton('开始预校验').click();
    });
    await flush();
    expect(http.post.mock.calls[0][0]).toBe('/api/interference/air/import/validate/');
  });
});

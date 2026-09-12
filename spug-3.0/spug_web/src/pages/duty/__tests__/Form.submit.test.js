/**
 * 值班日志 Form 提交测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例，无 @testing-library），mock libs.http，验证：
 * - 编辑模式：duty_date 以 YYYY-MM-DD 提交，载荷携带 id
 * - 新建模式：reporter 自动取 sessionStorage.nickname，report_time 默认当前时间（moment）
 * - 保存成功后关闭弹窗并刷新列表（store.fetchRecords）
 * - 引入当日记录：按模块分组拼接进 duty_situation，已有内容时追加不覆盖
 *
 * 环境说明：项目无 @testing-library，沿用本仓库惯例使用
 * ReactDOM + react-dom/test-utils + jsdom 真实渲染组件。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import moment from 'moment';
import ComForm from '../Form';
import S from '../store';
import { http } from 'libs';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: () => true,
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

const EDIT_RECORD = {
  id: 7,
  duty_person: '张三',
  reporter: '填报人甲',
  department: '运维部',
  duty_date: '2026-09-01',
  report_time: '2026-09-01 09:00',
  duty_situation: '值班正常',
};

let container = null;

function renderForm(record = null) {
  S.record = record || {};
  S.formVisible = true;
  act(() => {
    ReactDOM.render(<ComForm />, container);
  });
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

async function clickSave() {
  // Modal footer 的保存按钮；antd 对两字中文按钮自动插入空格，文本为"保 存"
  const btns = document.querySelectorAll('.ant-modal-footer .ant-btn');
  const saveBtn = Array.from(btns).find(b => b.textContent.replace(/\s/g, '') === '保存');
  expect(saveBtn).toBeTruthy();
  await click(saveBtn);
  // 冲刷 validateFields -> http.post 的微任务链
  await act(async () => {});
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  http.get.mockReset();
  http.post.mockReset();
  http.get.mockImplementation(() => Promise.resolve({records: [], duty_persons: [], departments: []}));
  http.post.mockImplementation(() => Promise.resolve());
  sessionStorage.setItem('nickname', '当前登录人');
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  document.body.innerHTML = '';
  S.record = {};
  S.formVisible = false;
  S.detailVisible = false;
  sessionStorage.removeItem('nickname');
});

describe('值班日志 Form 提交', () => {
  it('编辑模式：载荷携带 id，duty_date 格式化为 YYYY-MM-DD', async () => {
    renderForm(EDIT_RECORD);
    await clickSave();
    expect(http.post).toHaveBeenCalledTimes(1);
    const [url, payload] = http.post.mock.calls[0];
    expect(url).toBe('/api/duty/duty/');
    expect(payload.id).toBe(7);
    expect(payload.duty_person).toBe('张三');
    expect(payload.department).toBe('运维部');
    expect(payload.duty_date).toBe('2026-09-01');
  });

  it('编辑保存成功后关闭弹窗并刷新列表', async () => {
    renderForm(EDIT_RECORD);
    await clickSave();
    expect(http.post).toHaveBeenCalledTimes(1);
    // fetchRecords 被触发（GET 列表接口被调用）
    expect(http.get).toHaveBeenCalledWith('/api/duty/duty/');
    expect(S.formVisible).toBe(false);
  });

  it('新建模式：reporter 自动取 sessionStorage.nickname，report_time 默认当前时间', () => {
    renderForm(null);
    // 必填项为空时不做提交（validateFields 会拒绝），改为断言默认值填充
    expect(document.querySelector('.ant-modal-title').textContent).toBe('新建值班日志');
    const reporterInput = document.querySelector('input[placeholder="自动填入登录账号姓名"]');
    expect(reporterInput.value).toBe('当前登录人');
    // 两个 DatePicker：第一个是 duty_date（空），第二个是 disabled 的 report_time（默认当前时间）
    const pickerInputs = document.querySelectorAll('.ant-picker input');
    expect(pickerInputs.length).toBe(2);
    expect(pickerInputs[0].value).toBe('');
    expect(moment(pickerInputs[1].value, 'YYYY-MM-DD HH:mm:ss').isSame(moment(), 'minute')).toBe(true);
  });
});

describe('值班日志 Form 引入当日记录', () => {
  it('选中记录按模块分组拼接进 duty_situation，已有内容追加不覆盖', async () => {
    renderForm(EDIT_RECORD);

    // 引入数据接口在打开弹窗时即请求，必须先设置 mock 再点击
    http.get.mockImplementationOnce(() => Promise.resolve({
      runlog: [{id: 101, source: 'runlog', title: '跨日事项A', content: '事项内容A', recorder: '记录人A', sequence: 2}],
      interference: [{id: 201, source: 'interference', title: '干扰B', content: '干扰内容B'}],
      upgrade: [],
    }));

    const importBtn = Array.from(document.querySelectorAll('button'))
      .find(b => b.textContent.includes('引入当日记录'));
    expect(importBtn).toBeTruthy();
    await click(importBtn);
    await act(async () => {});

    // 默认 Tab 是跨日事项跟踪，勾选其中的记录
    // （antd 默认不销毁非活动 TabPane，必须限定活动面板内的 checkbox）
    const runlogCheckbox = document.querySelector('.ant-tabs-tabpane-active .ant-checkbox-input');
    expect(runlogCheckbox).toBeTruthy();
    await click(runlogCheckbox);

    // 切到干扰记录 Tab 勾选另一条
    const interferenceTab = Array.from(document.querySelectorAll('.ant-tabs-tab'))
      .find(t => t.textContent.includes('干扰记录'));
    expect(interferenceTab).toBeTruthy();
    await click(interferenceTab);
    await act(async () => {});
    const interferenceCheckbox = document.querySelector('.ant-tabs-tabpane-active .ant-checkbox-input');
    expect(interferenceCheckbox).toBeTruthy();
    await click(interferenceCheckbox);

    // 确认引入
    const confirmBtn = Array.from(document.querySelectorAll('.ant-modal-footer .ant-btn-primary'))
      .find(b => b.textContent.includes('确认引入'));
    expect(confirmBtn).toBeTruthy();
    await act(async () => {
      confirmBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await act(async () => {});

    // 验证拼接结果：原内容保留 + 分组头 + 序号/记录人
    const textarea = document.querySelector('textarea');
    const value = textarea.value;
    expect(value).toContain('值班正常');
    expect(value).toContain('--- 引入跨日事项跟踪 ---');
    expect(value).toContain('--- 引入干扰记录 ---');
    expect(value).toContain('【跨日事项A - 序号2 - 记录人A】');
    expect(value).toContain('事项内容A');
    expect(value).toContain('【干扰B】');
    expect(value).toContain('干扰内容B');
  });
});

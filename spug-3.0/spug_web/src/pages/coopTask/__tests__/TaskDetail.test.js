/**
 * 协作任务详情（TaskDetail）组件行为测试
 *
 * 真实渲染组件（react-dom + act），验证：
 * - 挂载即发起详情请求，加载态与成功渲染
 * - 请求失败不崩溃、加载态恢复
 * - 组件卸载后未完成请求的回调不再回写状态（issue：卸载后 setState）
 * - taskId 切换后旧请求响应不得覆盖新任务数据（issue：旧请求覆盖新状态）
 * - 催办成功后刷新详情
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';
import {notification} from 'antd';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHasPermission = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: mockHasPermission,
  X_TOKEN: 'test-token',
}));

jest.mock('components/AttachmentManager', () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock('../TemplateManageModal', () => ({
  __esModule: true,
  default: () => null,
}));

// 用 require 而非 import：import 会被提升到 mock 变量声明之前，
// 触发 "Cannot access before initialization"（与既有 coopTaskUtils.test.js 一致）
const TaskDetail = require('../Detail').default;

// jsdom 无 matchMedia，antd 响应式组件需要
if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    },
  });
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return {promise, resolve, reject};
}

function buildTask(taskId, title) {
  return {
    id: taskId,
    title,
    description: '',
    deadline: '2026-09-30 18:00',
    is_overdue: false,
    status: 'in_progress',
    completed_at: '',
    created_by_name: '张三',
    created_at: '2026-08-30 10:00',
    items: [{id: 1, name: '材料A', remark: '', templates: []}],
    assignments: [
      {
        id: 10,
        target_tenant_id: 't_b',
        target_tenant_name: '二科',
        contact_user_id: 0,
        contact_user_name: '李四',
        aggregate_status: 'pending',
        urge_count: 0,
        last_urged_at: '',
        deliveries: [
          {
            id: 100,
            item_id: 1,
            item_name: '材料A',
            item_remark: '',
            status: 'pending',
            attachment_count: 0,
            submitted_at: '',
            submitter_name: '',
            reject_reason: '',
          },
        ],
      },
    ],
  };
}

function renderModal(element) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(element, container);
  });
  return container;
}

async function flush() {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

function findButton(text) {
  // antd 4 对两个汉字按钮自动插入空格（"催 办"），匹配前归一化空白
  return [...document.body.querySelectorAll('button')].find(
    b => b.textContent.replace(/\s+/g, '') === text);
}

const unmountedWarnings = () =>
  console.error.mock.calls.filter(call =>
    /unmounted component/i.test(String(call[0])));

describe('TaskDetail 组件行为', () => {
  let containers;
  let onChanged;
  let onClose;

  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(console, 'error').mockImplementation(() => {});
    jest.spyOn(notification, 'success').mockImplementation(() => {});
    jest.spyOn(notification, 'error').mockImplementation(() => {});
    mockHasPermission.mockReturnValue(true);
    containers = [];
    onChanged = jest.fn();
    onClose = jest.fn();
  });

  afterEach(() => {
    containers.forEach(c => {
      ReactDOM.unmountComponentAtNode(c);
      c.remove();
    });
    console.error.mockRestore();
    notification.success.mockRestore();
    notification.error.mockRestore();
  });

  const mount = taskId => {
    const c = renderModal(
      <TaskDetail taskId={taskId} onClose={onClose} onChanged={onChanged} />);
    containers.push(c);
    return c;
  };

  test('挂载即请求详情，加载中无数据，成功后渲染任务标题', async () => {
    const d = deferred();
    mockHttpGet.mockImplementation(() => d.promise);
    mount(5);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/coop-task/tasks/5/');
    expect(document.body.textContent).not.toContain('任务甲'); // 数据未到不渲染

    d.resolve(buildTask(5, '任务甲'));
    await flush();
    expect(document.body.textContent).toContain('任务甲');
  });

  test('刷新期间展示加载态，完成后恢复并渲染新数据', async () => {
    const d1 = deferred();
    mockHttpGet.mockImplementationOnce(() => d1.promise);
    mount(5);
    d1.resolve(buildTask(5, '任务甲'));
    await flush();
    expect(document.body.textContent).toContain('任务甲');
    expect(document.querySelector('.ant-spin-spinning')).toBeNull();

    // taskId 变化触发重新请求，表格仍在（旧数据保留）且进入加载态
    const d2 = deferred();
    mockHttpGet.mockImplementationOnce(() => d2.promise);
    act(() => {
      ReactDOM.render(
        <TaskDetail taskId={6} onClose={onClose} onChanged={onChanged}/>,
        containers[0]);
    });
    expect(document.querySelector('.ant-spin-spinning')).toBeTruthy();
    d2.resolve(buildTask(6, '任务乙'));
    await flush();
    expect(document.querySelector('.ant-spin-spinning')).toBeNull();
    expect(document.body.textContent).toContain('任务乙');
  });

  test('请求失败不崩溃且加载态恢复', async () => {
    mockHttpGet.mockRejectedValueOnce(new Error('network down'));
    mount(5);
    await flush();
    expect(document.body.textContent).not.toContain('任务甲');
    expect(document.querySelector('.ant-spin-spinning')).toBeNull();
    expect(unmountedWarnings()).toHaveLength(0);
  });

  test('卸载后未完成请求的回调不再 setState', async () => {
    const d = deferred();
    mockHttpGet.mockImplementation(() => d.promise);
    const container = renderModal(
      <TaskDetail taskId={5} onClose={onClose} onChanged={onChanged} />);
    containers.push(container);

    act(() => {
      ReactDOM.unmountComponentAtNode(container);
    });
    containers = containers.filter(c => c !== container);

    d.resolve(buildTask(5, '任务甲'));
    await flush();
    expect(unmountedWarnings()).toHaveLength(0);
    expect(mockHttpGet).toHaveBeenCalledTimes(1); // 卸载后不追加刷新请求
    expect(onChanged).not.toHaveBeenCalled();
  });

  test('taskId 切换后旧请求响应不覆盖新任务数据', async () => {
    const d5 = deferred();
    const d6 = deferred();
    mockHttpGet.mockImplementationOnce(() => d5.promise)
      .mockImplementationOnce(() => d6.promise);
    mount(5);
    expect(mockHttpGet).toHaveBeenCalledWith('/api/coop-task/tasks/5/');

    act(() => {
      ReactDOM.render(
        <TaskDetail taskId={6} onClose={onClose} onChanged={onChanged}/>,
        containers[0]);
    });
    expect(mockHttpGet).toHaveBeenCalledWith('/api/coop-task/tasks/6/');

    d6.resolve(buildTask(6, '任务乙'));
    await flush();
    expect(document.body.textContent).toContain('任务乙');

    d5.resolve(buildTask(5, '任务甲')); // 旧请求迟到
    await flush();
    expect(document.body.textContent).toContain('任务乙');
    expect(document.body.textContent).not.toContain('任务甲');
  });

  test('催办成功后刷新详情并提示成功', async () => {
    mockHttpGet.mockResolvedValue(buildTask(5, '任务甲')); // 催办成功后的刷新也有响应
    const d = deferred();
    mockHttpGet.mockImplementationOnce(() => d.promise);
    mount(5);
    d.resolve(buildTask(5, '任务甲'));
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(1);

    const urgeBtn = findButton('催办');
    expect(urgeBtn).toBeTruthy();
    const sd = deferred();
    mockHttpPost.mockImplementationOnce(() => sd.promise);
    act(() => {
      urgeBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    expect(mockHttpPost).toHaveBeenCalledWith(
      '/api/coop-task/tasks/5/urge/', {assignment_id: 10});

    sd.resolve(undefined);
    await flush();
    expect(mockHttpGet).toHaveBeenCalledTimes(2); // 催办成功后刷新
    expect(notification.success).toHaveBeenCalled();
  });
});

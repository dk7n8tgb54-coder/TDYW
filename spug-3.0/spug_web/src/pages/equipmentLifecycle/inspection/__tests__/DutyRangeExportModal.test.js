/**
 * 巡检单导出日期范围弹窗测试（DutyRangeExportModal）：
 * - 确认时校验日期完整性：未选择完整范围、起始日期晚于截止日期均提示且
 *   不触发 onConfirm；
 * - 校验通过时 onConfirm 收到所选范围；取消仅回调 onCancel；
 * - RangePicker 日期变更经组件统一入口转发（清空归一化为空数组），
 *   且不回写列表筛选 store.f_duty_range；
 * - 导出进行中（exporting）确认被忽略。
 * 说明：jsdom 无法完整驱动 antd 4 RangePicker 的面板交互，日期变更通过
 * ref 调用组件真实的 onChange 入口模拟选择器回调；确认/取消按钮均为真实
 * DOM 点击。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import moment from 'moment';
import {act} from 'react-dom/test-utils';

const onConfirm = jest.fn();
const onCancel = jest.fn();
const onChange = jest.fn();

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
  onConfirm.mockClear();
  onCancel.mockClear();
  onChange.mockClear();
  store = require('../store').default;
  store.f_duty_range = [];
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
});

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function findButton(root, label) {
  const target = label.replace(/\s+/g, '');
  return [...root.querySelectorAll('button')]
    .find(btn => btn.textContent.replace(/\s+/g, '') === target);
}

function renderModal(value, exporting = false, extraProps = {}) {
  const DutyRangeExportModal = require('../DutyRangeExportModal').default;
  const ref = React.createRef();
  act(() => {
    ReactDOM.render(
      <DutyRangeExportModal
        ref={ref}
        visible
        value={value}
        exporting={exporting}
        count={extraProps.count}
        countLoading={extraProps.countLoading}
        onChange={onChange}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
      container,
    );
  });
  return ref.current;
}

describe('巡检单导出日期范围弹窗', () => {
  it('确认后 onConfirm 收到所选日期范围', async () => {
    const range = [moment('2026-09-01'), moment('2026-09-15')];
    renderModal(range);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0]).toBe(range);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('未选择完整日期范围时确认不触发导出并给出提示', async () => {
    renderModal(null);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('请选择起始日期和截止日期');

    // 空数组（清空后的归一化值）同样视为未选择完整范围
    renderModal([]);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('起始日期晚于截止日期时确认不触发导出并给出提示', async () => {
    renderModal([moment('2026-09-10'), moment('2026-09-01')]);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('起始日期不能晚于截止日期');
  });

  it('导出进行中确认被忽略（防重复提交）', async () => {
    const modalRef = renderModal(
      [moment('2026-09-01'), moment('2026-09-15')], true);
    await act(async () => {
      findButton(document.body, '确认').click();
    });
    await act(flush);
    expect(onConfirm).not.toHaveBeenCalled();
    // 组件内部守卫兜底（antd confirmLoading 之外的防线）
    act(() => {modalRef.handleOk();});
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('取消仅回调 onCancel，不触发导出', async () => {
    renderModal([moment('2026-09-01'), moment('2026-09-15')]);
    await act(async () => {
      findButton(document.body, '取消').click();
    });
    await act(flush);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('展示统计中/可导出条数/无数据提示，无统计结果时不显示', async () => {
    const range = [moment('2026-09-01'), moment('2026-09-15')];
    renderModal(range, false, {countLoading: true});
    expect(document.body.querySelector('.ant-modal').textContent)
      .toContain('正在统计所选日期范围内可导出的条数');

    renderModal(range, false, {count: 12});
    expect(document.body.querySelector('.ant-modal').textContent)
      .toContain('共可导出 12 条巡检单记录');

    renderModal(range, false, {count: 0});
    expect(document.body.querySelector('.ant-modal').textContent)
      .toContain('没有可导出的数据');

    renderModal(range, false, {});
    expect(document.body.querySelector('.ant-modal').textContent)
      .not.toContain('共可导出');
  });

  it('RangePicker 日期变更经统一入口转发，清空归一化为空数组', () => {
    const modalRef = renderModal([moment('2026-09-01'), moment('2026-09-15')]);
    act(() => {modalRef.handleRangeChange(null);});
    expect(onChange).toHaveBeenCalledWith([]);
    const range = [moment('2026-08-01'), moment('2026-08-15')];
    act(() => {modalRef.handleRangeChange(range);});
    expect(onChange).toHaveBeenLastCalledWith(range);
  });

  it('弹窗内修改日期不回写列表筛选 store.f_duty_range', () => {
    store.f_duty_range = [moment('2026-09-01'), moment('2026-09-30')];
    const modalRef = renderModal(store.f_duty_range.slice());
    const picked = [moment('2026-08-01'), moment('2026-08-15')];
    act(() => {modalRef.handleRangeChange(picked);});
    expect(store.f_duty_range.map(m => m.format('YYYY-MM-DD')))
      .toEqual(['2026-09-01', '2026-09-30']);
  });
});

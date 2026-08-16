/**
 * FileNameText 组件测试（2026-08-16 交互收敛）
 *
 * 契约：
 * 1. 仅当名称真实被截断（scrollWidth > clientWidth）时悬停才产生 Tooltip 内容；
 *    完整可见/未悬停时无任何提示（避免扫视列表时提示闪烁）
 * 2. Tooltip 传参：placement=top、mouseEnterDelay=0.3（抑制划过误触发）
 * 3. 截断时 Tooltip 含完整名称与复制按钮；复制成功/失败提示正确
 * 4. 展示 span 保留单行省略样式，且不挂原生 title
 *
 * 实现说明：antd Tooltip 用"属性记录型桩"替换（渲染 title 内容便于断言），
 * 其余 antd（message 等）为真实实现；jsdom 无布局，截断检测所需的
 * scrollWidth/clientWidth 在元素实例上打桩后由真实 onMouseEnter 逻辑读取。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act, Simulate } from 'react-dom/test-utils';
import { message } from 'antd';
import FileNameText from '../FileNameText';
import { copyToClipboard } from '@/utils/common';

jest.mock('@/utils/common', () => ({ copyToClipboard: jest.fn() }));

// Tooltip 桩：记录最近一次收到的 props，并把 title 内容渲染进 DOM 便于断言
jest.mock('antd', () => {
  const ReactActual = require('react');
  const actual = jest.requireActual('antd');
  const TooltipMock = ({ title, children, ...rest }) => {
    TooltipMock.lastProps = { title, ...rest };
    return (
      <span className="tooltip-mock" data-has-title={title ? 'yes' : 'no'}>
        {title}
        {children}
      </span>
    );
  };
  TooltipMock.lastProps = null;
  return { ...actual, Tooltip: TooltipMock };
});

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

const LONG_NAME = '关于开展2026年无线电管理专项行动的阶段性总结报告（附件3-修订版）.docx';

let container = null;
let successSpy = null;
let errorSpy = null;

function tooltipMock() {
  // eslint-disable-next-line global-require
  const { Tooltip } = require('antd');
  return Tooltip;
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  copyToClipboard.mockReset();
  successSpy = jest.spyOn(message, 'success').mockImplementation(() => {});
  errorSpy = jest.spyOn(message, 'error').mockImplementation(() => {});
  tooltipMock().lastProps = null;
});

afterEach(() => {
  act(() => {
    ReactDOM.unmountComponentAtNode(container);
  });
  container.remove();
  container = null;
  successSpy.mockRestore();
  errorSpy.mockRestore();
});

function renderName(name = LONG_NAME) {
  act(() => {
    ReactDOM.render(<FileNameText name={name} />, container);
  });
  return container.querySelector('span[data-has-title] > span') || container.querySelector('span');
}

/** 桩掉 jsdom 缺失的布局测量，驱动真实 onMouseEnter 截断检测 */
function setSpanSize(span, scrollWidth, clientWidth) {
  Object.defineProperty(span, 'scrollWidth', { configurable: true, get: () => scrollWidth });
  Object.defineProperty(span, 'clientWidth', { configurable: true, get: () => clientWidth });
}

function hover(span) {
  act(() => {
    Simulate.mouseEnter(span);
  });
}

const flushMicrotasks = () => act(async () => {});

describe('截断门槛（核心契约）', () => {
  it('未悬停时不产生任何 Tooltip 内容', () => {
    renderName();
    expect(container.querySelector('.tooltip-mock').getAttribute('data-has-title')).toBe('no');
  });

  it('名称完整可见（scrollWidth <= clientWidth）：悬停后仍不产生 Tooltip 内容', () => {
    const span = renderName();
    setSpanSize(span, 300, 400); // 名称放得下
    hover(span);
    expect(container.querySelector('.tooltip-mock').getAttribute('data-has-title')).toBe('no');
  });

  it('名称被截断（scrollWidth > clientWidth）：悬停后 Tooltip 出现完整名称与复制按钮', () => {
    const span = renderName();
    setSpanSize(span, 900, 300); // 名称被截断
    hover(span);

    const tooltipEl = container.querySelector('.tooltip-mock');
    expect(tooltipEl.getAttribute('data-has-title')).toBe('yes');
    expect(tooltipEl.textContent).toContain(LONG_NAME);
    expect(tooltipEl.querySelector('.anticon-copy')).toBeTruthy();
  });

  it('Tooltip 传参：placement=top 且 mouseEnterDelay=0.3（抑制划过误触发）', () => {
    const span = renderName();
    setSpanSize(span, 900, 300);
    hover(span);

    const lastProps = tooltipMock().lastProps;
    expect(lastProps.placement).toBe('top');
    expect(lastProps.mouseEnterDelay).toBe(0.3);
  });
});

describe('展示样式与复制行为', () => {
  it('展示 span 保留单行省略样式，且不挂原生 title', () => {
    const span = renderName();
    expect(span.style.overflow).toBe('hidden');
    expect(span.style.textOverflow).toBe('ellipsis');
    expect(span.style.whiteSpace).toBe('nowrap');
    expect(span.getAttribute('title')).toBeNull();
    expect(span.textContent).toBe(LONG_NAME);
  });

  it('复制按钮：复制完整文件名并提示成功', async () => {
    copyToClipboard.mockResolvedValueOnce(true);
    const span = renderName();
    setSpanSize(span, 900, 300);
    hover(span);

    act(() => {
      container.querySelector('.tooltip-mock .anticon-copy')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flushMicrotasks();

    expect(copyToClipboard).toHaveBeenCalledWith(LONG_NAME);
    expect(successSpy).toHaveBeenCalledWith('文件名已复制');
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it('复制失败：提示失败且不弹成功', async () => {
    copyToClipboard.mockResolvedValueOnce(false);
    const span = renderName();
    setSpanSize(span, 900, 300);
    hover(span);

    act(() => {
      container.querySelector('.tooltip-mock .anticon-copy')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flushMicrotasks();

    expect(errorSpy).toHaveBeenCalledWith('复制失败，请手动复制');
    expect(successSpy).not.toHaveBeenCalled();
  });
});

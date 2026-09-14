/**
 * PreviewShell 统一预览外壳测试
 *
 * 真实渲染 antd Modal 外壳（项目无 @testing-library，沿用 ReactDOM + test-utils 惯例），验证：
 * - 默认大窗：96vw 宽、14px 顶距、默认外壳类（正文高度由 module.less 提供，jsdom 不加载 CSS）
 * - 点击标题栏图标进入/退出铺满视口，children（iframe 探针）不重挂载
 * - Esc（rc-dialog wrap onKeyDown）与关闭图标都能关闭
 * - 长文件名单行省略并以 title 暴露全名，操作按钮完整保留
 * - 窄屏自动全屏，resize 回桌面尺寸后还原
 * - 关闭后最大化状态重置
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act, Simulate} from 'react-dom/test-utils';
import PreviewShell from '../PreviewShell';

function mountShell({fileName = 'demo.pdf', visible = true} = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const ref = {visible, fileName, onClose: jest.fn()};
  const render = () => act(() => {
    ReactDOM.render(
      <PreviewShell visible={ref.visible} fileName={ref.fileName} onClose={ref.onClose}>
        <iframe title="probe" data-testid="probe"/>
      </PreviewShell>,
      container
    );
  });
  render();
  return {container, ref, render};
}

function modalEl() {
  return document.querySelector('.ant-modal');
}

function actionBtn(label) {
  return document.querySelector(`button[aria-label="${label}"]`);
}

function clickBtn(label) {
  act(() => {
    Simulate.click(actionBtn(label));
  });
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('PreviewShell 默认大窗', () => {
  it('宽 96vw、顶距 14px、应用默认外壳类且未进入铺满类', () => {
    mountShell();
    const modal = modalEl();
    expect(modal).toBeTruthy();
    expect(modal.style.width).toBe('96vw');
    expect(modal.style.top).toBe('14px');
    expect(modal.className).toContain('modal');
    expect(modal.className).not.toContain('modalMax');
  });

  it('标题栏含文件名与铺满/关闭两个图标按钮', () => {
    mountShell({fileName: '设计说明书.pdf'});
    expect(document.querySelector('.titleText').textContent).toBe('设计说明书.pdf');
    expect(actionBtn('铺满视口')).toBeTruthy();
    expect(actionBtn('关闭')).toBeTruthy();
  });

  it('长文件名通过 title 暴露全名且操作按钮不被挤压', () => {
    const longName = '超长文件名'.repeat(60) + '.pdf';
    mountShell({fileName: longName});
    const title = document.querySelector('.titleText');
    expect(title.textContent).toBe(longName);
    expect(title.title).toBe(longName);
    // 省略与布局由 CSS 承担，这里验证两个操作按钮仍完整渲染在标题栏内
    expect(actionBtn('铺满视口')).toBeTruthy();
    expect(actionBtn('关闭')).toBeTruthy();
  });
});

describe('PreviewShell 铺满视口切换', () => {
  it('点击图标进入铺满：100vw、顶距 0、应用铺满类，且 children 不重挂载', () => {
    const {ref} = mountShell();
    const iframeBefore = document.querySelector('iframe[data-testid="probe"]');

    clickBtn('铺满视口');

    const modal = modalEl();
    expect(modal.style.width).toBe('100vw');
    expect(modal.style.top).toBe('0px');
    expect(modal.className).toContain('modalMax');
    const iframeAfter = document.querySelector('iframe[data-testid="probe"]');
    expect(iframeAfter).toBe(iframeBefore);
    expect(ref.onClose).not.toHaveBeenCalled();
  });

  it('再次点击还原为默认大窗，iframe 仍是同一节点', () => {
    mountShell();
    const iframeBefore = document.querySelector('iframe[data-testid="probe"]');

    clickBtn('铺满视口');
    expect(actionBtn('还原')).toBeTruthy();
    clickBtn('还原');

    const modal = modalEl();
    expect(modal.style.width).toBe('96vw');
    expect(modal.style.top).toBe('14px');
    expect(document.querySelector('iframe[data-testid="probe"]')).toBe(iframeBefore);
  });

  it('关闭后重置最大化状态，重新打开回到默认大窗', () => {
    const {ref, render} = mountShell();
    clickBtn('铺满视口');
    expect(modalEl().style.width).toBe('100vw');

    ref.visible = false;
    render();
    ref.visible = true;
    render();

    expect(modalEl().style.width).toBe('96vw');
    expect(modalEl().style.top).toBe('14px');
  });
});

describe('PreviewShell 关闭交互', () => {
  it('Esc 关闭', () => {
    const {ref} = mountShell();
    const wrap = document.querySelector('.ant-modal-wrap');
    act(() => {
      Simulate.keyDown(wrap, {keyCode: 27, key: 'Escape'});
    });
    expect(ref.onClose).toHaveBeenCalledTimes(1);
  });

  it('点击关闭图标关闭', () => {
    const {ref} = mountShell();
    clickBtn('关闭');
    expect(ref.onClose).toHaveBeenCalledTimes(1);
  });
});

describe('PreviewShell 窄屏适配', () => {
  const originalInnerWidth = window.innerWidth;

  afterEach(() => {
    window.innerWidth = originalInnerWidth;
  });

  it('窄屏挂载即全屏，resize 回桌面宽度后还原', () => {
    window.innerWidth = 375;
    const {render} = mountShell();
    expect(modalEl().style.width).toBe('100vw');
    expect(modalEl().style.top).toBe('0px');

    act(() => {
      window.innerWidth = 1280;
      window.dispatchEvent(new Event('resize'));
    });
    render();

    expect(modalEl().style.width).toBe('96vw');
    expect(modalEl().style.top).toBe('14px');
  });
});

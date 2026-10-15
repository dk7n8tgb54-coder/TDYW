/**
 * AttachmentManager 预览窗口集成测试
 *
 * 真实渲染 AttachmentManager（含 antd Table 与共享 PreviewShell），走真实 handlePreview
 * 链路，验证：
 * - previewRequest 适配器：image 类型居中 contain 展示；kkfileview 渲染 iframe
 * - 铺满/还原切换不重挂载 iframe
 * - 旧链路（无 previewRequest）保持不变：图片/PDF 走 downloadUrlPrefix inline+x-token，
 *   其他类型走 preview-url 接口
 * - 关闭时组件自建的 Blob URL 被 revokeObjectURL 清理
 */
jest.mock('libs', () => ({
  http: {get: jest.fn(), post: jest.fn(), delete: jest.fn()},
  hasPermission: jest.fn(() => true),
  X_TOKEN: 'test-token',
}));

const React = require('react');
const ReactDOM = require('react-dom');
const {act, Simulate} = require('react-dom/test-utils');
const AttachmentManager = require('../AttachmentManager').default;
const {http} = require('libs');

// jsdom 环境垫片：antd Table 的 useBreakpoint/responsiveObserve 需要（仅补 API 形状）
/* eslint-disable no-empty-function */
if (!window.matchMedia) {
  window.matchMedia = query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
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
if (typeof URL.revokeObjectURL !== 'function') {
  URL.revokeObjectURL = () => {};
}
/* eslint-enable no-empty-function */

const BASE_ATTACHMENT = {
  id: 7,
  file_name: 'a.png',
  file_size: 1024,
  uploaded_by_name: 'u1',
  uploaded_at: '2026-09-14',
};

// 各用例通过替换 currentRecord 决定列表返回的附件（扩展名决定旧链路分支）
let currentRecord = BASE_ATTACHMENT;

const listRequest = () => Promise.resolve([currentRecord]);

function renderManager(extraProps = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(
      <AttachmentManager
        module="test"
        recordId="r1"
        listRequest={listRequest}
        readOnly
        {...extraProps}
      />,
      container
    );
  });
  return container;
}

async function flush() {
  await act(async () => {});
}

function clickPreviewButton(container) {
  const btn = Array.from(container.querySelectorAll('button'))
    .find(b => b.textContent.includes('预览'));
  act(() => {
    Simulate.click(btn);
  });
}

function modalImg() {
  return document.querySelector('.ant-modal img');
}

function modalIframe() {
  return document.querySelector('.ant-modal iframe');
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
  http.get.mockReset();
});

describe('AttachmentManager previewRequest 适配器预览', () => {
  it('image 类型在弹窗中居中 contain 展示，默认 96vw 大窗', async () => {
    renderManager({
      previewRequest: () => Promise.resolve({
        preview_url: 'blob:http://localhost/aa-1',
        file_name: 'a.png',
        preview_type: 'image',
      }),
    });
    await flush();

    const container = document.querySelector('.ant-table');
    clickPreviewButton(container);
    await flush();

    const img = modalImg();
    expect(img).toBeTruthy();
    expect(img.src).toBe('blob:http://localhost/aa-1');
    expect(img.style.objectFit).toBe('contain');
    // 居中视口容器
    expect(img.parentElement.style.display).toBe('flex');
    expect(img.parentElement.style.justifyContent).toBe('center');
    expect(document.querySelector('.ant-modal').style.width).toBe('96vw');
  });

  it('kkfileview 渲染 iframe，铺满/还原不重挂载 iframe', async () => {
    renderManager({
      previewRequest: () => Promise.resolve({
        preview_url: 'https://kkfileview.example/onlinePreview?u=enc',
        preview_type: 'kkfileview',
      }),
    });
    await flush();

    clickPreviewButton(document.querySelector('.ant-table'));
    await flush();

    const iframeBefore = modalIframe();
    expect(iframeBefore).toBeTruthy();
    expect(iframeBefore.src).toBe('https://kkfileview.example/onlinePreview?u=enc');

    clickBtn('铺满视口');
    expect(document.querySelector('.ant-modal').style.width).toBe('100vw');
    expect(modalIframe()).toBe(iframeBefore);

    clickBtn('还原');
    expect(document.querySelector('.ant-modal').style.width).toBe('96vw');
    expect(modalIframe()).toBe(iframeBefore);
  });

  it('关闭预览时清理组件自建的 Blob URL', async () => {
    const revokeSpy = jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    renderManager({
      previewRequest: () => Promise.resolve({
        preview_url: 'blob:http://localhost/aa-2',
        preview_type: 'image',
      }),
    });
    await flush();

    clickPreviewButton(document.querySelector('.ant-table'));
    await flush();
    expect(modalImg()).toBeTruthy();

    clickBtn('关闭');
    expect(revokeSpy).toHaveBeenCalledWith('blob:http://localhost/aa-2');
    revokeSpy.mockRestore();
  });
});

describe('AttachmentManager 旧链路预览（无 previewRequest）', () => {
  it('图片走下载接口 inline 模式并携带 x-token', async () => {
    renderManager({downloadUrlPrefix: '/api/test/attachments/'});
    await flush();

    clickPreviewButton(document.querySelector('.ant-table'));
    await flush();

    const img = modalImg();
    expect(img).toBeTruthy();
    expect(img.src).toContain('/api/test/attachments/7/download/');
    expect(img.src).toContain('x-token=test-token');
    expect(img.src).toContain('inline=1');
    expect(http.get).not.toHaveBeenCalled();
  });

  it('PDF 走下载接口 inline 模式渲染 iframe', async () => {
    currentRecord = {...BASE_ATTACHMENT, file_name: 'b.pdf'};
    renderManager({downloadUrlPrefix: '/api/test/attachments/'});
    await flush();

    clickPreviewButton(document.querySelector('.ant-table'));
    await flush();

    const iframe = modalIframe();
    expect(iframe).toBeTruthy();
    expect(iframe.src).toContain('/api/test/attachments/7/download/');
    expect(iframe.src).toContain('inline=1');
    expect(iframe.src).toContain('x-token=test-token');
    currentRecord = BASE_ATTACHMENT;
  });

  it('其他类型请求 preview-url 接口后渲染 kkFileView iframe', async () => {
    http.get.mockResolvedValue({
      preview_url: 'https://kkfileview.example/onlinePreview?u=doc',
      file_name: 'c.docx',
    });
    currentRecord = {...BASE_ATTACHMENT, file_name: 'c.docx'};
    renderManager({previewUrlPrefix: '/api/test/attachments/'});
    await flush();

    clickPreviewButton(document.querySelector('.ant-table'));
    await flush();

    expect(http.get).toHaveBeenCalledWith('/api/test/attachments/7/preview-url/');
    const iframe = modalIframe();
    expect(iframe).toBeTruthy();
    expect(iframe.src).toBe('https://kkfileview.example/onlinePreview?u=doc');
    currentRecord = BASE_ATTACHMENT;
  });
});

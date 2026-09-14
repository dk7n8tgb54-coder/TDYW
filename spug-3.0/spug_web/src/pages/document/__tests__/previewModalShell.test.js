/**
 * document/PreviewModal 预览弹窗与共享 PreviewShell 集成测试
 *
 * 真实渲染 PreviewModal + 真实 uploadUIStore / navigationStore（MobX 装饰器经 jest babel
 * 编译），验证 openPreview 触发的各文件类型分支与外壳行为：
 * - 代码/文本：text_content 接口 → Ace 内容渲染
 * - PDF / 图片：preview_token 接口 → 带 preview_token 的预览 URL
 * - Office：office_preview_url 接口 → kkFileView iframe
 * - 默认 96vw 大窗；铺满/还原不重挂载 iframe；关闭按钮走 closePreview
 *
 * 垫片说明：ace-builds 各 mode/theme 以副作用导入且引用全局 ace，此处先垫极简 ace
 * 全局（仅注册行为），并以 stub 替换 react-ace / react-player 重型渲染；
 * libs/http 整体 mock，其余走真实代码路径。
 */
global.ace = {define: () => {}, require: () => ({})};

jest.mock('react-ace', () => ({
  __esModule: true,
  default: ({value}) => {
    const React = require('react');
    return React.createElement('div', {'data-testid': 'ace-stub'}, value);
  },
}));

jest.mock('react-player', () => ({
  __esModule: true,
  default: () => {
    const React = require('react');
    return React.createElement('div', {'data-testid': 'video-stub'});
  },
}));

jest.mock('libs/http', () => ({
  __esModule: true,
  default: {get: jest.fn()},
}));

const React = require('react');
const ReactDOM = require('react-dom');
const {act, Simulate} = require('react-dom/test-utils');
const PreviewModal = require('../PreviewModal').default;
const http = require('libs/http').default;

// uploadUIStore / navigationStore 的 default 导出是延迟绑定 Proxy（应用启动时由
// RootStore 绑定实例），测试环境自行绑定独立实例后才能访问其属性与方法
const uiStoreModule = require('../stores/upload/ui');
const navStoreModule = require('../stores/navigation');
uiStoreModule._bindUploadUIStore(new uiStoreModule.UploadUIStore());
navStoreModule._bindNavigationStore(new navStoreModule.NavigationStore());
const uploadUIStore = uiStoreModule.default;

let currentContainer = null;

function mountModal() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  act(() => {
    ReactDOM.render(<PreviewModal/>, container);
  });
  currentContainer = container;
  return container;
}

async function openFile(file) {
  const container = mountModal();
  act(() => {
    uploadUIStore.handlePreview(file);
  });
  // 让 componentDidUpdate 内发出的 http.get 返回并完成 setState
  await act(async () => {});
  return container;
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
  // 先卸载组件再重置 store：store 直接关闭会让已挂载的 observer 重渲染，
  // 走到组件既有代码 file.id 的裸引用（生产环境关闭都经由组件 handleClose，无此路径）
  if (currentContainer) {
    act(() => {
      ReactDOM.unmountComponentAtNode(currentContainer);
    });
    currentContainer = null;
  }
  act(() => {
    uploadUIStore.closePreview();
  });
  document.body.innerHTML = '';
  http.get.mockReset();
});

describe('PreviewModal 各文件类型渲染', () => {
  it('代码文件请求 text_content 并渲染内容，默认 96vw 大窗', async () => {
    http.get.mockResolvedValue({content: 'print(1)', language: 'python'});
    await openFile({id: 1, display_name: 'a.py', file_type: ''});

    expect(http.get).toHaveBeenCalledWith('/api/document/text_content/?id=1&is_public=true');
    const ace = document.querySelector('[data-testid="ace-stub"]');
    expect(ace).toBeTruthy();
    expect(ace.textContent).toBe('print(1)');
    expect(modalEl().style.width).toBe('96vw');
  });

  it('PDF 请求 preview_token 后渲染带令牌的 iframe', async () => {
    http.get.mockResolvedValue({preview_token: 'tk-2'});
    await openFile({
      id: 2,
      display_name: 'b.pdf',
      file_type: 'application/pdf',
    });

    expect(http.get).toHaveBeenCalledWith('/api/document/preview_token/?id=2&is_public=true');
    const iframe = document.querySelector('.ant-modal iframe');
    expect(iframe).toBeTruthy();
    expect(iframe.src).toContain('/api/document/preview/?id=2');
    expect(iframe.src).toContain('preview_token=tk-2');
  });

  it('Office 文件请求 office_preview_url 后渲染 kkFileView iframe', async () => {
    http.get.mockResolvedValue({preview_url: 'https://kkfileview.example/onlinePreview?u=doc'});
    await openFile({
      id: 3,
      display_name: 'c.docx',
      file_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });

    expect(http.get).toHaveBeenCalledWith('/api/document/office_preview_url/?id=3&is_public=true');
    const iframe = document.querySelector('.ant-modal iframe');
    expect(iframe).toBeTruthy();
    expect(iframe.src).toBe('https://kkfileview.example/onlinePreview?u=doc');
  });

  it('图片请求 preview_token 后 contain 居中展示', async () => {
    http.get.mockResolvedValue({preview_token: 'tk-4'});
    await openFile({id: 4, display_name: 'd.png', file_type: 'image/png'});

    expect(http.get).toHaveBeenCalledWith('/api/document/preview_token/?id=4&is_public=true');
    const img = document.querySelector('.ant-modal img');
    expect(img).toBeTruthy();
    expect(img.src).toContain('/api/document/preview/?id=4');
    expect(img.src).toContain('preview_token=tk-4');
    expect(img.style.objectFit).toBe('contain');
  });

  it('视频请求 preview_token 后渲染播放器', async () => {
    http.get.mockResolvedValue({preview_token: 'tk-5'});
    await openFile({id: 5, display_name: 'e.mp4', file_type: 'video/mp4'});

    expect(http.get).toHaveBeenCalledWith('/api/document/preview_token/?id=5&is_public=true');
    expect(document.querySelector('[data-testid="video-stub"]')).toBeTruthy();
  });
});

describe('PreviewModal 外壳交互', () => {
  it('铺满/还原不重挂载 iframe', async () => {
    http.get.mockResolvedValue({preview_token: 'tk-6'});
    await openFile({id: 6, display_name: 'f.pdf', file_type: 'application/pdf'});
    const iframeBefore = document.querySelector('.ant-modal iframe');

    act(() => {
      Simulate.click(actionBtn('铺满视口'));
    });
    expect(modalEl().style.width).toBe('100vw');
    expect(document.querySelector('.ant-modal iframe')).toBe(iframeBefore);

    act(() => {
      Simulate.click(actionBtn('还原'));
    });
    expect(modalEl().style.width).toBe('96vw');
    expect(document.querySelector('.ant-modal iframe')).toBe(iframeBefore);
  });

  it('关闭按钮走 closePreview 清空弹窗状态', async () => {
    http.get.mockResolvedValue({preview_token: 'tk-7'});
    await openFile({id: 7, display_name: 'g.pdf', file_type: 'application/pdf'});
    expect(uploadUIStore.previewVisible).toBe(true);

    clickBtn('关闭');

    expect(uploadUIStore.previewVisible).toBe(false);
    expect(uploadUIStore.previewFile).toBe(null);
  });

  it('Esc 关闭并清空弹窗状态', async () => {
    http.get.mockResolvedValue({preview_token: 'tk-8'});
    await openFile({id: 8, display_name: 'h.pdf', file_type: 'application/pdf'});

    act(() => {
      Simulate.keyDown(document.querySelector('.ant-modal-wrap'), {keyCode: 27, key: 'Escape'});
    });

    expect(uploadUIStore.previewVisible).toBe(false);
  });
});

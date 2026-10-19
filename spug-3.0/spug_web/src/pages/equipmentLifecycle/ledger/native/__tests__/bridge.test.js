/**
 * 原生台账编辑器消息桥（宿主侧）行为测试。
 *
 * 覆盖（真实事件循环 + jsdom postMessage）：
 * - listenEditor：origin 与 source 双重校验（不符来源/来源缺失的消息忽略）；
 * - postToEditor：消息信封形态（source/type/payload/requestId）；
 * - useEditorChannel：nl-ready 置就绪并递增 readySeq（重挂载重新注入）、
 *   推送消息分发、collect 应答与超时失败、iframe 加载超时置 loadFailed
 *   并可 retry 重置。
 */
import React from 'react';
import ReactDOM from 'react-dom';
import {act} from 'react-dom/test-utils';

const {listenEditor, postToEditor, MSG, EDITOR_SOURCE, HOST_SOURCE,
  originAllowed, useEditorChannel}
  = require('../bridge');

const ORIGIN = window.location.origin;

function postFromEditor(data) {
  window.postMessage({...data, source: EDITOR_SOURCE}, ORIGIN);
}

function flushMessageEvents(ms = 20) {
  return act(async () => {
    await new Promise(resolve => setTimeout(resolve, ms));
  });
}

describe('origin 白名单判定', () => {
  test('匹配来源放行、不匹配与空串（跨来源配置）拒绝', () => {
    expect(originAllowed(ORIGIN, ORIGIN)).toBe(true);
    expect(originAllowed(ORIGIN, 'https://evil.example')).toBe(false);
    // 空串仅在"允许来源=本页 origin"（同源部署）时兼容（jsdom 测试环境）
    expect(originAllowed(ORIGIN, '')).toBe(true);
    expect(originAllowed('https://editor.example', '')).toBe(false);
  });
});

describe('bridge 协议', () => {
  test('listenEditor 过滤 source 不符的消息（同源投递）', async () => {
    const received = [];
    const off = listenEditor(ORIGIN, msg => received.push(msg));
    postFromEditor({type: MSG.READY, payload: {}});
    // 缺 source / 错误 source / 非字符串类型 一律忽略
    window.postMessage({type: MSG.READY}, ORIGIN);
    window.postMessage({source: 'someone-else', type: MSG.READY}, ORIGIN);
    window.postMessage({source: EDITOR_SOURCE, type: 42}, ORIGIN);
    await flushMessageEvents();
    off();
    expect(received).toHaveLength(1);
    expect(received[0].type).toBe(MSG.READY);
  });

  test('postToEditor 发送宿主信封（无 contentWindow 静默忽略）', () => {
    const fakeWin = {postMessage: jest.fn()};
    postToEditor(fakeWin, MSG.INIT, {mode: 'template'}, 'req-1');
    expect(fakeWin.postMessage).toHaveBeenCalledWith(
      {source: HOST_SOURCE, type: MSG.INIT, payload: {mode: 'template'}, requestId: 'req-1'},
      '*');
    expect(() => postToEditor(null, MSG.INIT)).not.toThrow();
  });
});

function renderHarnessIn(container, handlers = {}) {
  const iframeRef = React.createRef();
  function Harness() {
    const channel = useEditorChannel(iframeRef, handlers);
    Harness.last = channel;
    return React.createElement('iframe', {ref: iframeRef, title: 't', src: 'about:blank'});
  }
  act(() => {
    ReactDOM.render(React.createElement(Harness), container);
  });
  Harness.iframeRef = iframeRef;
  return Harness;
}

describe('useEditorChannel', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    act(() => ReactDOM.unmountComponentAtNode(container));
    container.remove();
    jest.useRealTimers();
  });

  function renderHarness(handlers = {}) {
    return renderHarnessIn(container, handlers);
  }

  test('nl-ready 置就绪并递增 readySeq；推送消息分发到 handlers', async () => {
    const onValues = jest.fn();
    const onDraftMeta = jest.fn();
    const onExportPdf = jest.fn();
    const harness = renderHarness({onValues, onDraftMeta, onExportPdf});
    expect(harness.last.ready).toBe(false);
    await flushMessageEvents();
    await act(async () => {
      postFromEditor({type: MSG.READY, payload: {}});
      await flushMessageEvents(30);
    });
    expect(harness.last.ready).toBe(true);
    expect(harness.last.readySeq).toBe(1);
    await act(async () => {
      postFromEditor({type: MSG.READY, payload: {}});
      await flushMessageEvents(30);
    });
    // 重挂载（第二次 READY）递增序号：宿主据此重新注入 nl-init
    expect(harness.last.readySeq).toBe(2);
    await act(async () => {
      postFromEditor({type: MSG.VALUES, payload: {values: {a: '1'}}});
      postFromEditor({type: MSG.DRAFT_META, payload: {dirty: true}});
      postFromEditor({type: MSG.EXPORT_PDF, payload: {}});
      await flushMessageEvents(30);
    });
    expect(onValues).toHaveBeenCalledWith({values: {a: '1'}});
    expect(onDraftMeta).toHaveBeenCalledWith({dirty: true});
    expect(onExportPdf).toHaveBeenCalled();
  });

});

describe('useEditorChannel collect 与加载失败', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    act(() => ReactDOM.unmountComponentAtNode(container));
    container.remove();
    jest.useRealTimers();
  });

  test('collect 应答路径：requestId 匹配才 resolve', async () => {
    const harness = renderHarnessIn(container, {});
    await flushMessageEvents();
    await act(async () => {
      postFromEditor({type: MSG.READY, payload: {}});
      await flushMessageEvents(30);
    });
    // 监听 iframe 收到的宿主消息（jsdom 父子窗口 postMessage 真实投递）
    const iframeWin = harness.iframeRef.current.contentWindow;
    let sentEnvelope = null;
    iframeWin.addEventListener('message', event => {
      if (event.data && event.data.source === HOST_SOURCE
          && event.data.type === MSG.COLLECT) {
        sentEnvelope = event.data;
      }
    });
    let resolved;
    await act(async () => {
      const promise = harness.last.collect(3000).then(v => {
        resolved = true;
        return v;
      });
      await new Promise(resolve => setTimeout(resolve, 30));
      expect(sentEnvelope).not.toBeNull();
      postFromEditor({
        type: MSG.COLLECT_RESULT,
        payload: {values: {x: '2'}},
        requestId: sentEnvelope.requestId,
      });
      await promise;
    });
    expect(resolved).toBe(true);
  });

  test('collect 超时路径与未就绪失败', async () => {
    const harness = renderHarnessIn(container, {});
    let rejected;
    await harness.last.collect().catch(e => {
      rejected = e;
    });
    expect(rejected.message).toContain('尚未就绪');

    await flushMessageEvents();
    await act(async () => {
      postFromEditor({type: MSG.READY, payload: {}});
      await flushMessageEvents(30);
    });
    await act(async () => {
      await harness.last.collect(30).catch(e => {
        rejected = e;
      });
      await new Promise(resolve => setTimeout(resolve, 60));
    });
    expect(rejected.message).toContain('超时');
  });

  test('加载超时置 loadFailed 且 retry 重置', async () => {
    jest.useFakeTimers();
    const harness = renderHarnessIn(container, {});
    await act(async () => {
      jest.advanceTimersByTime(12500);
      await Promise.resolve();
    });
    expect(harness.last.loadFailed).toBe(true);
    await act(async () => {
      harness.last.retry();
      await Promise.resolve();
    });
    expect(harness.last.loadFailed).toBe(false);
    // retry 后重新进入 12s 等待窗
    await act(async () => {
      jest.advanceTimersByTime(12500);
      await Promise.resolve();
    });
    expect(harness.last.loadFailed).toBe(true);
  });
});

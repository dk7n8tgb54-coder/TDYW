/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生台账编辑器消息桥（宿主侧，正式页面 → iframe 编辑器）。
 *
 * 协议与编辑器侧（spug_web/native-editor/src/bridge.js）保持一致：
 * - 全部消息带 source 标识与类型白名单，不识别的消息一律忽略；
 * - 宿主校验 event.origin（同源部署为 location.origin，允许
 *   REACT_APP_NATIVE_LEDGER_URL 指向的独立来源用于本地联调）；
 * - 消息内容只有模板数据与填写值，不传递任何凭据（认证由宿主页面
 *   的 /api 请求统一承载）；
 * - 需要应答的消息（nl-collect）带 requestId，超时按失败处理。
 */
import {useEffect, useRef, useState} from 'react';

export const HOST_SOURCE = 'native-ledger-host';
export const EDITOR_SOURCE = 'native-ledger-editor';

export const MSG = {
  READY: 'nl-ready',
  INIT: 'nl-init',
  VALUES: 'nl-values',
  DRAFT_META: 'nl-draft-meta',
  COLLECT: 'nl-collect',
  COLLECT_RESULT: 'nl-collect-result',
  EXPORT_PDF: 'nl-export-pdf',
  SAVED: 'nl-saved',
};

/** 编辑器 iframe 地址：生产为 /native-ledger/index.html（CRA public/ 产物），
 * 本地联调可用 REACT_APP_NATIVE_LEDGER_URL 指向编辑器 dev server。 */
export function editorUrl() {
  return process.env.REACT_APP_NATIVE_LEDGER_URL
    || `${process.env.PUBLIC_URL || ''}/native-ledger/index.html`;
}

/** iframe 允许的消息来源 origin。 */
export function resolveEditorOrigin() {
  const url = editorUrl();
  try {
    return new URL(url, window.location.href).origin;
  } catch (e) {
    return window.location.origin;
  }
}

/** 宿主监听编辑器消息（origin + source 双重校验），返回解绑函数。 */
export function listenEditor(allowedOrigin, onMessage) {
  const handler = event => {
    if (!originAllowed(allowedOrigin, event.origin)) return;
    const data = event.data;
    if (!data || data.source !== EDITOR_SOURCE || typeof data.type !== 'string') return;
    onMessage(data);
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

/**
 * origin 白名单判定。
 *
 * 真实浏览器中 postMessage 的 event.origin 恒为发送方 origin（不会是空串）；
 * jsdom（jest 测试环境）同窗口 postMessage 的 event.origin 为空串，为使
 * 消息桥行为可被测试覆盖，仅在"允许来源即本页自身 origin"（同源部署）时
 * 兼容空串。跨来源联调配置（REACT_APP_NATIVE_LEDGER_URL）不受该分支影响。
 */
export function originAllowed(allowedOrigin, eventOrigin) {
  if (!eventOrigin) return allowedOrigin === window.location.origin;
  return eventOrigin === allowedOrigin;
}

/** 宿主 → 编辑器发送消息。payload 可能含 MobX observable（Proxy），直接
 * postMessage 会因结构化克隆失败抛 DataCloneError，统一先 JSON 净化为纯对象。 */
export function postToEditor(contentWindow, type, payload = {}, requestId) {
  if (!contentWindow) return;
  let clean = payload;
  try {
    clean = JSON.parse(JSON.stringify(payload ?? {}));
  } catch (e) {
    clean = {};
  }
  contentWindow.postMessage({source: HOST_SOURCE, type, payload: clean, requestId}, '*');
}

let collectSeq = 0;

/**
 * 编辑器通道 Hook：管理 iframe 消息监听、就绪状态、加载失败与收集请求。
 *
 * - handlers: {onValues, onDraftMeta, onExportPdf}（编辑器推送分发）；
 * - 返回 {ready, loadFailed, retry, collect, sendInit, notifySaved}；
 * - collect() 返回 Promise<state>：向编辑器请求全量状态（快照/绑定/纸张/
 *   填写值），8 秒未应答按失败处理（iframe 加载失败或编辑器异常）；
 * - iframe 挂载后 12 秒未收到 nl-ready 判定加载失败（编辑器静态包缺失/
 *   加载异常），retry() 重置状态并重新加载 iframe。
 */
export function useEditorChannel(iframeRef, handlers) {
  const [ready, setReady] = useState(false);
  const [readySeq, setReadySeq] = useState(0);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers || {};
  const pendingCollect = useRef(null);
  const collectResolve = useRef(null);
  const collectReject = useRef(null);
  const collectTimer = useRef(null);
  const readyTimer = useRef(null);

  const origin = resolveEditorOrigin();

  const clearCollect = () => {
    if (collectTimer.current) {
      window.clearTimeout(collectTimer.current);
      collectTimer.current = null;
    }
    pendingCollect.current = null;
  };

  useEffect(() => {
    // 每次 iframe 重载（key 变化）后重置就绪/失败状态并重新计时
    setReady(false);
    setLoadFailed(false);
    if (readyTimer.current) window.clearTimeout(readyTimer.current);
    readyTimer.current = window.setTimeout(() => {
      setLoadFailed(true);
    }, 12000);
    const off = listenEditor(origin, message => {
      if (message.type === MSG.READY) {
        if (readyTimer.current) {
          window.clearTimeout(readyTimer.current);
          readyTimer.current = null;
        }
        setReady(true);
        setLoadFailed(false);
        // 每次 nl-ready（含 iframe 重挂载）递增序号，宿主据此（重）发 nl-init：
        // postMessage 不排队，编辑器脚本未挂载前发送的消息会丢失
        setReadySeq(value => value + 1);
      } else if (message.type === MSG.VALUES) {
        handlersRef.current.onValues && handlersRef.current.onValues(message.payload || {});
      } else if (message.type === MSG.DRAFT_META) {
        handlersRef.current.onDraftMeta && handlersRef.current.onDraftMeta(message.payload || {});
      } else if (message.type === MSG.EXPORT_PDF) {
        handlersRef.current.onExportPdf && handlersRef.current.onExportPdf();
      } else if (message.type === MSG.COLLECT_RESULT
                 && pendingCollect.current
                 && pendingCollect.current === message.requestId) {
        clearCollect();
        const resolve = collectResolve.current;
        collectResolve.current = null;
        collectReject.current = null;
        resolve && resolve(message.payload || {});
      }
    });
    return () => {
      off();
      if (readyTimer.current) window.clearTimeout(readyTimer.current);
      clearCollect();
      if (collectReject.current) {
        collectReject.current(new Error('编辑器通道已关闭'));
        collectReject.current = null;
        collectResolve.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [origin, reloadToken]);

  const retry = () => setReloadToken(value => value + 1);

  const collect = (timeoutMs = 8000) => new Promise((resolve, reject) => {
    const win = iframeRef.current && iframeRef.current.contentWindow;
    if (!win || !ready) {
      reject(new Error('编辑器尚未就绪，请稍后重试'));
      return;
    }
    if (pendingCollect.current) {
      reject(new Error('已有收集请求进行中'));
      return;
    }
    collectSeq += 1;
    const requestId = `collect-${Date.now()}-${collectSeq}`;
    pendingCollect.current = requestId;
    collectResolve.current = resolve;
    collectReject.current = reject;
    postToEditor(win, MSG.COLLECT, {}, requestId);
    collectTimer.current = window.setTimeout(() => {
      const timedOut = pendingCollect.current === requestId;
      clearCollect();
      collectResolve.current = null;
      const rej = collectReject.current;
      collectReject.current = null;
      if (timedOut && rej) rej(new Error('收集编辑器状态超时，请重试'));
    }, timeoutMs);
  });

  const sendInit = payload => {
    const win = iframeRef.current && iframeRef.current.contentWindow;
    postToEditor(win, MSG.INIT, payload);
  };

  const notifySaved = () => {
    const win = iframeRef.current && iframeRef.current.contentWindow;
    postToEditor(win, MSG.SAVED, {});
  };

  return {ready, readySeq, loadFailed, retry, collect, sendInit, notifySaved, reloadToken};
}

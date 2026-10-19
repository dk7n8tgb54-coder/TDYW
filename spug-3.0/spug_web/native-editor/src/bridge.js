/**
 * 消息桥协议（编辑器 iframe ⇄ 平台宿主页面）。
 *
 * 安全约定：
 * - 所有消息带 source 标识（'native-ledger-editor' / 'native-ledger-host'），
 *   收到不带 source 或 source 不符的消息一律忽略；
 * - 宿主通过 window.postMessage 发送，编辑器只接受宿主窗口（window.parent）
 *   的消息；宿主侧校验 event.origin（同源部署为 location.origin）；
 * - 需要应答的消息带 requestId，编辑器回包原样携带；消息内容只有模板
 *   数据与填写值，不传递任何凭据（认证由宿主页面的 /api 请求承载）。
 *
 * 消息清单：
 * 编辑器 → 宿主：
 *   nl-ready            编辑器挂载完成，等待 nl-init
 *   nl-values           {values} 填写值变更（fill 模式，节流推送）
 *   nl-draft-meta       {title, bindingsCount, paper, dirty} 草稿元信息变更
 *                       （template 模式，节流推送；不含快照本体）
 *   nl-collect-result   {requestId, snapshot, bindings, paper, values, dirty}
 *                       应答 nl-collect（宿主保存/发布/导出前收集全量状态）
 *   nl-export-pdf       fill 模式打印弹窗请求导出（宿主先保存再走后端导出）
 * 宿主 → 编辑器：
 *   nl-init             {mode:'template'|'fill', data} 初始化数据（慢路径重发）
 *   nl-collect          {requestId} 请求收集当前全量状态
 *   nl-saved            宿主已成功保存（草稿/填写值），编辑器复位脏标记
 */

export const EDITOR_SOURCE = 'native-ledger-editor';
export const HOST_SOURCE = 'native-ledger-host';

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

let requestSeq = 0;

export function nextRequestId(prefix) {
  requestSeq += 1;
  return `${prefix}-${Date.now()}-${requestSeq}`;
}

/** 编辑器 → 宿主发送消息（目标固定 window.parent）。 */
export function postToHost(type, payload = {}, requestId) {
  if (window.parent === window) return;
  window.parent.postMessage({ source: EDITOR_SOURCE, type, payload, requestId }, '*');
}

/**
 * 编辑器侧监听宿主消息：校验来源窗口与 source 标识后分发。
 * 返回解绑函数。
 */
export function listenHost(onMessage) {
  const handler = (event) => {
    if (event.source !== window.parent) return;
    const data = event.data;
    if (!data || data.source !== HOST_SOURCE || typeof data.type !== 'string') return;
    onMessage(data);
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

/**
 * 宿主侧监听编辑器消息：由宿主注入 allowedOrigin（iframe src 的来源，
 * 同源部署即 location.origin），来源或 source 不符一律忽略。
 * 返回解绑函数。
 */
export function listenEditor(allowedOrigin, onMessage) {
  const expected = allowedOrigin || window.location.origin;
  const handler = (event) => {
    if (event.origin !== expected) return;
    const data = event.data;
    if (!data || data.source !== EDITOR_SOURCE || typeof data.type !== 'string') return;
    onMessage(data);
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

/** 宿主 → 编辑器发送消息（目标 iframe contentWindow）。 */
export function postToEditor(contentWindow, type, payload = {}, requestId) {
  if (!contentWindow) return;
  contentWindow.postMessage({ source: HOST_SOURCE, type, payload, requestId }, '*');
}

/**
 * 资料库发布门禁前端测试（stable_contract）
 *
 * 覆盖共享请求层与党建上下文注入：
 * 1. systemFolderContext 状态机与参数注入纯函数
 * 2. http.js 请求拦截器：党建模式自动注入 system_folder（GET query / POST body / FormData）
 * 3. http.js 响应拦截器：HTTP 200 + {"error": "..."} 必须被识别为业务失败
 * 4. 二进制响应透传与 JSON 错误识别
 * 5. 同一错误 2 秒内不重复提示；skipErrorNotification 抑制弹窗
 */

// --- Mock antd ---
const mockMessage = { info: jest.fn(), error: jest.fn(), success: jest.fn(), warning: jest.fn() };
jest.mock('antd', () => ({ message: mockMessage }));

// --- Node 老版本缺少 TextEncoder/TextDecoder 全局（浏览器环境原生支持）---
if (typeof global.TextDecoder === 'undefined') {
  global.TextDecoder = class {
    decode(bytes) {
      const u8 = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
      let latin1 = '';
      for (let i = 0; i < u8.length; i += 1) latin1 += String.fromCharCode(u8[i]);
      try {
        return decodeURIComponent(escape(latin1));
      } catch (e) {
        return latin1;
      }
    }
  };
}

const { setSystemFolder, getSystemFolder, isPartyBuildingDocumentsMode,
        isPartyBuildingDocumentsPath, shouldUseSystemFolder,
        appendSystemFolderParam, withSystemFolderParams,
        PARTY_BUILDING_DOCUMENTS_CODE } = require('libs/systemFolderContext');
const history = require('libs/history').default;
const http = require('libs/http').default;

const PB_PATH = '/document/party-building-documents';

// 用 mock adapter 驱动真实 axios 拦截器链
let adapterResponse = null;
let lastConfig = null;
http.defaults.adapter = (config) => {
  lastConfig = config;
  return Promise.resolve(adapterResponse);
};

function setPath(path) {
  // 使用 history 包自身导航，确保其内部 location 同步
  history.push(path);
}

beforeEach(() => {
  jest.clearAllMocks();
  setSystemFolder(null);
  setPath('/');
});

describe('A. systemFolderContext 状态机', () => {
  test('A1 setSystemFolder / getSystemFolder 往返，空值清除', () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    expect(getSystemFolder()).toBe(PARTY_BUILDING_DOCUMENTS_CODE);
    setSystemFolder(null);
    expect(getSystemFolder()).toBeNull();
    setSystemFolder('');
    expect(getSystemFolder()).toBeNull();
  });

  test('A2 isPartyBuildingDocumentsMode 只认党建编码', () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    expect(isPartyBuildingDocumentsMode()).toBe(true);
    setSystemFolder('other_code');
    expect(isPartyBuildingDocumentsMode()).toBe(false);
    setSystemFolder(null);
    expect(isPartyBuildingDocumentsMode()).toBe(false);
  });

  test('A3 isPartyBuildingDocumentsPath 精确与前缀匹配，拒绝相似前缀', () => {
    expect(isPartyBuildingDocumentsPath(PB_PATH)).toBe(true);
    expect(isPartyBuildingDocumentsPath(`${PB_PATH}/sub`)).toBe(true);
    expect(isPartyBuildingDocumentsPath('/document')).toBe(false);
    expect(isPartyBuildingDocumentsPath(`${PB_PATH}-other`)).toBe(false);
  });

  test('A4 shouldUseSystemFolder 需要激活 + 党建路径同时满足', () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    expect(shouldUseSystemFolder(PB_PATH)).toBe(true);
    expect(shouldUseSystemFolder('/document')).toBe(false);
    setSystemFolder(null);
    expect(shouldUseSystemFolder(PB_PATH)).toBe(false);
  });
});

describe('B. systemFolderContext 参数注入纯函数', () => {
  test('B1 appendSystemFolderParam 注入且保留已有 query', () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    expect(appendSystemFolderParam('/api/document/download/?id=1', PB_PATH))
      .toBe('/api/document/download/?id=1&system_folder=party_building_documents');
    expect(appendSystemFolderParam('/api/document/download/', PB_PATH))
      .toBe('/api/document/download/?system_folder=party_building_documents');
  });

  test('B2 非党建路径不注入', () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    expect(appendSystemFolderParam('/api/document/download/?id=1', '/document'))
      .toBe('/api/document/download/?id=1');
  });

  test('B3 withSystemFolderParams 注入且不修改入参', () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    const input = { id: 5 };
    const out = withSystemFolderParams(input, PB_PATH);
    expect(out).toEqual({ id: 5, system_folder: 'party_building_documents' });
    expect(input).toEqual({ id: 5 }, '不得原地修改调用方对象');
  });

  test('B4 未激活时不注入', () => {
    expect(withSystemFolderParams({ id: 5 }, PB_PATH)).toEqual({ id: 5 });
  });
});

describe('C. http 请求拦截器：system_folder 注入', () => {
  test('C1 党建模式下 GET /api/document/* 注入 query 参数', async () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    setPath(PB_PATH);
    adapterResponse = { data: { data: [], error: '' }, status: 200, statusText: 'OK', headers: {}, config: { url: '/api/document/folder/' } };
    await http.get('/api/document/folder/');
    expect(lastConfig.params.system_folder).toBe(PARTY_BUILDING_DOCUMENTS_CODE);
  });

  test('C2 党建模式下 POST JSON 注入 body', async () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    setPath(PB_PATH);
    adapterResponse = { data: { data: '', error: '' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    await http.post('/api/document/folder/', { name: 'x' });
    const body = typeof lastConfig.data === 'string'
      ? JSON.parse(lastConfig.data) : lastConfig.data;
    expect(body.system_folder).toBe(PARTY_BUILDING_DOCUMENTS_CODE);
    expect(body.name).toBe('x');
  });

  test('C3 党建模式下 POST FormData 注入表单字段', async () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    setPath(PB_PATH);
    adapterResponse = { data: { data: '', error: '' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    const fd = new FormData();
    fd.append('file', new Blob(['x']), 'a.txt');
    // 与 fileUpload.js:146 一致：调用方显式声明 multipart Content-Type
    await http.post('/api/document/upload/', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    expect(lastConfig.data.has('system_folder')).toBe(true);
    expect(lastConfig.data.get('system_folder')).toBe(PARTY_BUILDING_DOCUMENTS_CODE);
  });

  test('C4 非 document 接口不注入', async () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    setPath(PB_PATH);
    adapterResponse = { data: { data: [], error: '' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    await http.get('/api/home/notice/');
    expect(lastConfig.params && lastConfig.params.system_folder).toBeUndefined();
  });

  test('C5 普通资料库路径不注入（避免污染公共库请求）', async () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    setPath('/document');
    adapterResponse = { data: { data: [], error: '' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    await http.get('/api/document/folder/');
    expect(lastConfig.params && lastConfig.params.system_folder).toBeUndefined();
  });

  test('C6 已有 system_folder 时不覆盖调用方显式值', async () => {
    setSystemFolder(PARTY_BUILDING_DOCUMENTS_CODE);
    setPath(PB_PATH);
    adapterResponse = { data: { data: '', error: '' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    await http.get('/api/document/folder/', { params: { system_folder: 'explicit' } });
    expect(lastConfig.params.system_folder).toBe('explicit');
  });
});

describe('D. http 响应拦截器：业务错误识别', () => {
  test('D1 HTTP 200 + {"data":X,"error":""} 解析为业务数据', async () => {
    adapterResponse = { data: { data: { id: 1 }, error: '' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    await expect(http.get('/api/document/folder/')).resolves.toEqual({ id: 1 });
  });

  test('D2 HTTP 200 + {"data":"","error":"权限拒绝"} 必须被当作业务失败', async () => {
    adapterResponse = { data: { data: '', error: '权限拒绝' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    await expect(http.get('/api/document/folder/')).rejects.toBe('权限拒绝');
    expect(mockMessage.error).toHaveBeenCalledWith('权限拒绝');
  });

  test('D3 成功响应 data 为空字符串时返回空对象而非空字符串', async () => {
    adapterResponse = { data: { data: '', error: '' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    await expect(http.get('/api/document/folder/')).resolves.toEqual({});
  });

  test('D4 非 200 状态码被拒绝并提示', async () => {
    adapterResponse = { data: 'Not Found', status: 404, statusText: 'Not Found', headers: {}, config: {} };
    await expect(http.get('/api/document/folder/')).rejects.toBe('请求失败: 404 Not Found');
  });

  test('D5 二进制响应（非 JSON content-type）直接透传', async () => {
    adapterResponse = {
      data: new Blob(['binary']),
      status: 200, statusText: 'OK',
      headers: { 'content-type': 'application/octet-stream' },
      config: { responseType: 'blob' },
    };
    const result = await http.get('/api/document/download/', { responseType: 'blob' });
    expect(result).toBe(adapterResponse);
    expect(mockMessage.error).not.toHaveBeenCalled();
  });

  test('D6 二进制通道返回 JSON 错误时被识别为业务失败', async () => {
    // 直接调用真实响应拦截器；data 为字符串覆盖 handleResponse 二进制分支的
    // `typeof response.data === 'string' ? response.data : decode(...)` 取值路径
    const handler = http.interceptors.response.handlers[0].fulfilled;
    await expect(handler({
      data: JSON.stringify({ data: '', error: '文件不存在' }),
      status: 200, statusText: 'OK',
      headers: { 'content-type': 'application/json' },
      config: { responseType: 'blob' },
    })).rejects.toBe('文件不存在');
  });

  test('D7 skipErrorNotification 抑制错误弹窗但仍拒绝', async () => {
    adapterResponse = { data: { data: '', error: '静默失败' }, status: 200, statusText: 'OK', headers: {}, config: { skipErrorNotification: true } };
    await expect(http.get('/api/document/folder/')).rejects.toBe('静默失败');
    expect(mockMessage.error).not.toHaveBeenCalled();
  });
});

describe('E. 错误去重', () => {
  test('E1 同一错误 2 秒内只提示一次', async () => {
    const resp = { data: { data: '', error: '去重错误' }, status: 200, statusText: 'OK', headers: {}, config: {} };
    adapterResponse = resp;
    await expect(http.get('/api/document/folder/')).rejects.toBe('去重错误');
    await expect(http.get('/api/document/folder/')).rejects.toBe('去重错误');
    await expect(http.get('/api/document/folder/')).rejects.toBe('去重错误');
    expect(mockMessage.error).toHaveBeenCalledTimes(1);
  });
});

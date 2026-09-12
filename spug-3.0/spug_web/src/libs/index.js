/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import _http from './http';
import _history from './history';

export * from './functools';
export * from './router';
export * from './attachmentCount';
export { exportFile } from './exportFile';
export const http = _http;
export const history = _history;
// 构建期版本常量：仅用于「关于」页对 spug.cc 上游新版本的检查参数。
// 平台版本号唯一来源是后端 spug_api/VERSION（/api/system/version/），
// 界面展示一律使用服务端返回值，不要用本常量做版本展示。
export const VERSION = process.env.REACT_APP_SPUG_VERSION || 'v3.3.3';

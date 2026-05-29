/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * RecycleBinStore - 兼容层
 * 为了保持向后兼容，此文件重定向到新的拆分 Store
 * 
 * 【第二阶段重构】
 * - 原 store.js 已拆分为 stores/RecycleBinUIStore.js 和 stores/RecycleBinBusinessStore.js
 * - 此文件提供兼容层，确保旧代码无需修改即可工作
 * 
 * 建议：新代码直接导入 stores/index.js 使用
 */
import store from './stores';

export default store;

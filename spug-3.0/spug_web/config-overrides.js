/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
const {override, addDecoratorsLegacy, addLessLoader, addWebpackAlias} = require('customize-cra');
const path = require('path');

module.exports = override(
  addDecoratorsLegacy(),
  addLessLoader({
    lessOptions: {
      javascriptEnabled: true,
      modifyVars: {
        '@primary-color': '#2563fc'
      }
    }
  }),
  // 【2.3重构】添加 @/ 路径别名支持
  addWebpackAlias({
    ['@']: path.resolve(__dirname, 'src')
  }),
);

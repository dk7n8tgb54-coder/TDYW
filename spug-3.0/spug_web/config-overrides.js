/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
const {override, addDecoratorsLegacy, addLessLoader, addWebpackAlias} = require('customize-cra');
const path = require('path');

const webpackConfig = override(
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

// jest 配置：忽略 __tests__/ 下的辅助模块（非测试文件）被 jest 当成测试文件跑
const jestConfig = config => {
  config.moduleNameMapper = {
    ...(config.moduleNameMapper || {}),
    '^libs/(.*)$': '<rootDir>/src/libs/$1',
    '^pages/(.*)$': '<rootDir>/src/pages/$1',
    '^components/(.*)$': '<rootDir>/src/components/$1',
    '^stores/(.*)$': '<rootDir>/src/stores/$1',
  };
  config.testPathIgnorePatterns = [
    ...(config.testPathIgnorePatterns || ['/node_modules/']),
    '_gatewayEnv'
  ];
  return config;
};

module.exports = {
  webpack: webpackConfig,
  jest: jestConfig,
};

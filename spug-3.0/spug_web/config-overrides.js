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
    // 与 webpack 侧 addWebpackAlias 的 @ -> src 保持一致，
    // 使源码中的 @/ 导入在 jest 下同样可解析（此前仅 webpack 支持）
    '^@/(.*)$': '<rootDir>/src/$1',
  };
  config.testPathIgnorePatterns = [
    ...(config.testPathIgnorePatterns || ['/node_modules/']),
    '_gatewayEnv'
  ];
  // 【2026-08-16 修复】jest 编译通道补齐 decorators 支持：
  // webpack 侧由上方 addDecoratorsLegacy() 提供，jest 侧此前缺失，导致 import 链
  // 触及 MobX 装饰器 store 的测试套件在加载阶段编译失败。
  // 实际生效的 js transform 在 rewireJestConfig 阶段已被 react-app-rewired 替换为
  // 其自带的 babelTransform（scripts/utils/babelTransform.js），因此两个来源路径
  // 都要匹配；css/文件 transform 保持不变。
  const customBabelTransform = require.resolve('./config/jest/babelTransform.js');
  const defaultBabelTransforms = [
    require.resolve('react-scripts/config/jest/babelTransform.js'),
    require.resolve('react-app-rewired/scripts/utils/babelTransform.js'),
  ].map((p) => p.toLowerCase());
  config.transform = Object.fromEntries(
    Object.entries(config.transform || {}).map(([pattern, transformer]) => [
      pattern,
      defaultBabelTransforms.includes(String(transformer).toLowerCase())
        ? customBabelTransform
        : transformer,
    ])
  );
  return config;
};

module.exports = {
  webpack: webpackConfig,
  jest: jestConfig,
};

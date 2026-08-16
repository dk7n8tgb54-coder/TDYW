'use strict';
/**
 * jest babel 转换器（2026-08-16）
 *
 * 基于 react-app-rewired 的 babelTransform（scripts/utils/babelTransform.js）
 * 扩展：保留其 preset 配置与 babelrc:true 行为（当前所有通过的测试套件正是
 * 走的那个转换器），在其基础上补齐 legacy decorators + class properties 插件。
 *
 * 背景：webpack 通道由 config-overrides.js 的 addDecoratorsLegacy() 提供同样的
 * 插件组合，jest 通道此前缺失，导致任何 import 链触及 MobX 装饰器 store 的测试
 * 套件在加载阶段编译失败（如 pages/document/__tests__/pauseForPageLeave.test.js）。
 * 由 config-overrides.js 的 jest 段将 js transform 指向本文件。
 */
const babelJestMd = require('babel-jest');
const babelJest = babelJestMd.__esModule ? babelJestMd.default : babelJestMd;

const hasJsxRuntime = (() => {
  if (process.env.DISABLE_NEW_JSX_TRANSFORM === 'true') {
    return false;
  }

  try {
    require.resolve('react/jsx-runtime');
    return true;
  } catch (e) {
    return false;
  }
})();

module.exports = babelJest.createTransformer({
  presets: [
    [
      require.resolve('babel-preset-react-app'),
      {
        runtime: hasJsxRuntime ? 'automatic' : 'classic',
      },
    ],
  ],
  plugins: [
    // 与 customize-cra addDecoratorsLegacy 相同组合：legacy 装饰器 + loose 类属性
    [require.resolve('@babel/plugin-proposal-decorators'), { legacy: true }],
    [require.resolve('@babel/plugin-proposal-class-properties'), { loose: true }],
  ],
  babelrc: true,
});

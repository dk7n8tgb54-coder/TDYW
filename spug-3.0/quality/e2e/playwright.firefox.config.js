/**
 * 多浏览器矩阵配置：在共享基础配置上仅切换浏览器项目。
 * 用法：npx playwright test <spec> --config=playwright.firefox.config.js
 * 不影响默认 playwright.config.js（chromium）的日常门禁行为。
 */
const base = require('./playwright.config.js');

module.exports = Object.assign({}, base, {
  projects: [
    {
      name: 'firefox',
      use: { ...base.use, browserName: 'firefox' },
    },
  ],
});

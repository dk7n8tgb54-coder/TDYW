/**
 * 合同协议模块 - 前端 JS/JSX 语法校验（Babel 解析）。
 *
 * 项目使用 legacy decorators + class properties，node --check 无法解析 ESM/JSX，
 * 必须通过 @babel/core 配合相应插件做真实语法解析。
 *
 * 用法： node scripts/check_syntax.js <文件/目录...>
 */
const fs = require('fs');
const path = require('path');
const babel = require('@babel/core');

const roots = process.argv.slice(2);

function walk(target, acc = []) {
  const stat = fs.statSync(target);
  if (stat.isFile()) {
    if (/\.(js|jsx)$/.test(target)) acc.push(target);
    return acc;
  }
  for (const entry of fs.readdirSync(target)) {
    const full = path.join(target, entry);
    if (fs.statSync(full).isDirectory()) {
      if (entry === 'node_modules' || entry === '.git') continue;
      walk(full, acc);
    } else if (/\.(js|jsx)$/.test(entry)) {
      acc.push(full);
    }
  }
  return acc;
}

const files = roots.flatMap((r) => walk(r));
let failed = 0;

for (const file of files) {
  try {
    babel.transformFileSync(file, {
      babelrc: false,
      configFile: false,
      ast: false,
      code: false,
      parserOpts: { plugins: ['jsx', 'classProperties', 'decorators-legacy'] },
      plugins: [
        ['@babel/plugin-proposal-decorators', { legacy: true }],
        ['@babel/plugin-proposal-class-properties', { loose: true }],
      ],
    });
    console.log(`OK    ${file}`);
  } catch (err) {
    failed += 1;
    console.log(`FAIL  ${file}\n      ${err.message.split('\n')[0]}`);
  }
}

console.log(`\n---- 共 ${files.length} 个文件，失败 ${failed} 个 ----`);
process.exit(failed ? 1 : 0);

// 语法验证脚本：使用 @babel/parser 解析 ES Module + decorators + classProperties
const parser = require('@babel/parser');
const fs = require('fs');
const path = require('path');

const files = process.argv.slice(2);
let ok = 0, fail = 0;
for (const f of files) {
  try {
    const code = fs.readFileSync(f, 'utf8');
    parser.parse(code, {
      sourceType: 'module',
      plugins: ['classProperties', 'decorators-legacy', 'dynamicImport', 'jsx'],
    });
    console.log('OK  ', f);
    ok++;
  } catch (e) {
    console.log('FAIL', f, ':', e.message);
    fail++;
  }
}
console.log('---');
console.log('OK:', ok, ' FAIL:', fail);
process.exit(fail > 0 ? 1 : 0);

const fs = require('fs');
const babel = require('@babel/core');

const files = [
  'src/pages/document/stores/upload/core/coordinators/ChunkUploadCoordinator.js',
  'src/pages/document/stores/upload/core/controls/ItemOperationController.js',
  'src/pages/document/stores/upload/core/fileUpload.js',
  'src/pages/document/stores/upload/core/chunkUpload.js',
  'src/pages/document/stores/upload/core/index.js',
];

let failed = 0;
for (const f of files) {
  const code = fs.readFileSync(f, 'utf8');
  try {
    babel.parseSync(code, {
      filename: f,
      babelrc: true,
      configFile: './babel.config.js',
    });
    console.log('OK  ' + f);
  } catch (e) {
    failed++;
    console.error('FAIL ' + f);
    console.error('  ' + (e.message || e));
  }
}
console.log('---');
console.log('Failed: ' + failed);
process.exit(failed > 0 ? 1 : 0);

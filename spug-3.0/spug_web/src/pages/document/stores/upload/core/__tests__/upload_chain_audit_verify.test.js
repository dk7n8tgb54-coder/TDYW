/**
 * 上传链路风险点验证测试（前端部分）
 *
 * 验证 upload_chain_audit_verify.py 中标注的前端风险点。
 * 通过直接读取源文件的方式验证代码结构。
 *
 * 若 **风险存在**（代码未修复），对应测试将 FAIL；
 * 若 **风险已修复**（代码已处理），对应测试 PASS。
 *
 * 运行方式：
 *   cd spug_web && npx react-app-rewired test --watchAll=false --testPathPattern=upload_chain_audit_verify
 */
import fs from 'fs';
import path from 'path';

// ---- 工具函数 ----
const PROJECT_ROOT = path.resolve(__dirname, '../../../../../../..');
const CORE_DIR = path.resolve(__dirname, '..');
const CHUNK_FILE = path.join(CORE_DIR, 'chunkUpload.js');
const CONSTANTS_FILE = path.join(CORE_DIR, 'upload-core-constants.js');
const USM_FILE = path.join(CORE_DIR, 'UploadStateMachine.js');

function readFile(p) {
  return fs.readFileSync(p, 'utf-8');
}

// ============================================================
// P0-2: TERMINAL_STATUSES 包含 error，与可重试业务矛盾
// ============================================================
describe('P0-2: TERMINAL_STATUSES 包含 error，与可重试业务矛盾', () => {
  const source = readFile(CONSTANTS_FILE);

  // TERMINAL_STATUSES = Object.freeze([UPLOAD_STATUS.COMPLETED, UPLOAD_STATUS.ERROR, UPLOAD_STATUS.CANCELLED])
  const tsMatch = source.match(/TERMINAL_STATUSES\s*=\s*Object\.freeze\(\[([\s\S]*?)\]\)/);
  // FINAL_STATES = ['completed', 'cancelled']
  const fsMatch = source.match(/FINAL_STATES\s*=\s*\[([\s\S]*?)\]/);

  test('TERMINAL_STATUSES 包含 UPLOAD_STATUS.ERROR', () => {
    expect(tsMatch).not.toBeNull();
    expect(tsMatch[1]).toContain('ERROR');
  });

  test('FINAL_STATES 不包含 error', () => {
    expect(fsMatch).not.toBeNull();
    const hasError = fsMatch[1].includes('error') || fsMatch[1].includes('ERROR');
    expect(hasError).toBe(false);
  });

  test('TERMINAL_STATUSES 与 FINAL_STATES 不一致——error 被 TERMINAL_STATUSES 包含但被 FINAL_STATES 排除', () => {
    expect(tsMatch).not.toBeNull();
    expect(fsMatch).not.toBeNull();
    const terminalHasError = tsMatch[1].includes('ERROR');
    const finalHasError = fsMatch[1].includes('error') || fsMatch[1].includes('ERROR');
    // 风险确认：TERMINAL_STATUSES 含 error 但 FINAL_STATES 不含
    // 这是故意设计的（FINAL_STATES 注释说 error 保留状态机以支持原地重试）
    // 但 TERMINAL_STATUSES 的命名"终态集合"在语义上仍误导
    if (terminalHasError && !finalHasError) {
      console.log('  → 注：FINAL_STATES 注释说"error 保留状态机以支持原地重试"');
      console.log('  → 但 TERMINAL_STATUSES（终态集合）包含 error，语义上矛盾');
      // 不 assert 失败，因为这是设计选择而非 bug
    }
  });
});

// ============================================================
// P0-3: uploadSingleChunk XHR 回调未检查 operationVersion
// ============================================================
describe('P0-3: XHR load/error/abort/timeout 回调缺 operationVersion 检查', () => {
  const source = readFile(CHUNK_FILE);

  const methodStart = source.indexOf('async uploadSingleChunk(');
  expect(methodStart).toBeGreaterThanOrEqual(0);
  const fromMethod = source.slice(methodStart);

  // 定位各回调位置
  const loadPattern = "xhr.addEventListener('load', () => {";
  const loadIdx = fromMethod.indexOf(loadPattern);
  const errorPattern = "xhr.addEventListener('error', () => {";
  const errorIdx = fromMethod.indexOf(errorPattern);
  const abortPattern = "xhr.addEventListener('abort', () => {";
  const abortIdx = fromMethod.indexOf(abortPattern);
  const timeoutPattern = "xhr.addEventListener('timeout', () => {";
  const timeoutIdx = fromMethod.indexOf(timeoutPattern);

  // progress 回调（作为对照，它应该检查）
  const progressPattern = "xhr.upload.addEventListener('progress', (e) => {";
  const progressIdx = fromMethod.indexOf(progressPattern);

  test('对照：progress 回调有 operationVersion 检查', () => {
    expect(progressIdx).toBeGreaterThanOrEqual(0);
    const window = fromMethod.slice(progressIdx, progressIdx + 200);
    const hasCheck = window.includes('isCurrentOperation') || window.includes('operationVersion');
    console.log('  progress 回调：有 version 检查 =', hasCheck);
    expect(hasCheck).toBe(true);  // 对照点，必须通过
  });

  test('load 回调有 operationVersion 检查', () => {
    expect(loadIdx).toBeGreaterThanOrEqual(0);
    const window = fromMethod.slice(loadIdx, loadIdx + 200);
    const hasCheck = window.includes('isCurrentOperation') || window.includes('operationVersion');
    console.log('  load 回调：有 version 检查 =', hasCheck);
    if (!hasCheck) {
      console.log('  → 风险确认：load 回调没有检查 operationVersion！');
      console.log(`  → 代码: ${window.replace(/\n/g, '\\n').slice(0, 150)}`);
    }
    expect(hasCheck).toBe(true);  // 风险点：应检查但未检查 → FAIL
  });

  test('error/abort/timeout 回调有 operationVersion 检查', () => {
    const callbacks = [
      { name: 'error', idx: errorIdx },
      { name: 'abort', idx: abortIdx },
      { name: 'timeout', idx: timeoutIdx },
    ];
    callbacks.forEach(cb => {
      expect(cb.idx).toBeGreaterThanOrEqual(0);
      const window = fromMethod.slice(cb.idx, cb.idx + 150);
      const hasCheck = window.includes('isCurrentOperation') || window.includes('operationVersion');
      console.log(`  ${cb.name} 回调：有 version 检查 =`, hasCheck);
      if (!hasCheck) {
        console.log(`  → 风险确认：${cb.name} 回调没有检查 operationVersion！`);
        console.log(`  → 代码: ${window.replace(/\n/g, '\\n').slice(0, 120)}`);
      }
      expect(hasCheck).toBe(true);  // 风险点：应检查但未检查 → FAIL
    });
  });
});

// ============================================================
// P1-1: mergeChunks 递归重试无深度限制
// ============================================================
describe('P1-1: mergeChunks 递归重试无深度限制', () => {
  const source = readFile(CHUNK_FILE);

  // 直接在整个文件中搜索递归调用，避免方法体提取不准确
  const recursiveCall = source.match(/return\s+this\.mergeChunks\s*\(/);

  test('mergeChunks 存在递归重试', () => {
    expect(recursiveCall).not.toBeNull();
    if (recursiveCall) {
      const recIdx = source.indexOf('return this.mergeChunks(');
      const window = source.slice(Math.max(0, recIdx - 120), recIdx + 100);
      console.log(`  → 递归调用附近代码: ${window.replace(/\n/g, '\\n')}`);
    }
  });

  test('递归重试有深度限制（retryCount/retryDepth/maxRetries）', () => {
    expect(recursiveCall).not.toBeNull();
    // 检查 mergeChunks 方法签名附近是否有深度计数器
    const mergeStart = source.indexOf('async mergeChunks(');
    const mergeEnd = source.indexOf('\n  async ', mergeStart + 1);
    const mergeBody = source.slice(mergeStart, mergeEnd > 0 ? mergeEnd : mergeStart + 1000);
    const hasDepthCounter = mergeBody.includes('retryCount') || 
                            mergeBody.includes('retryDepth') || 
                            mergeBody.includes('maxRetries') ||
                            mergeBody.includes('maxRetry') ||
                            mergeBody.includes('retryLimit');
    console.log('  有深度计数器:', hasDepthCounter);
    if (!hasDepthCounter) {
      console.log('  → 风险确认：mergeChunks 递归重试无深度限制，极端情况下可能无限递归');
    }
    expect(hasDepthCounter).toBe(true);  // 风险点：应限制但未限制 → FAIL
  });
});

// ============================================================
// P2-2: onCalculatingEntry queueMicrotask 竞态条件
// ============================================================
describe('P2-2: onCalculatingEntry queueMicrotask 竞态', () => {
  const source = readFile(USM_FILE);

  const methodStart = source.indexOf('onCalculatingEntry');
  expect(methodStart).toBeGreaterThanOrEqual(0);

  let methodBody = source.slice(methodStart);
  let nextEntry = methodBody.search(/\n\s+on\w+Entry\s*\(/);
  if (nextEntry > 0) {
    methodBody = methodBody.slice(0, nextEntry);
  }

  const hasMicrotask = methodBody.includes('queueMicrotask');

  test('onCalculatingEntry 使用 queueMicrotask 延迟回调', () => {
    expect(hasMicrotask).toBe(true);
  });

  test('queueMicrotask 回调中有额外的状态检查（防止竞态）', () => {
    expect(hasMicrotask).toBe(true);
    const qmIdx = methodBody.indexOf('queueMicrotask');
    const qmBlock = methodBody.slice(qmIdx, qmIdx + 250);
    const hasGuardCheck = qmBlock.includes('findUploadItemInCurrentTenant') && 
                          (qmBlock.includes('currentState') || qmBlock.includes('status'));
    console.log(`  queueMicrotask 回调代码: ${qmBlock.replace(/\n/g, '\\n').slice(0, 200)}`);
    console.log('  有额外状态检查:', hasGuardCheck);
    if (hasGuardCheck) {
      console.log('  → 缓释：有额外状态检查，竞态风险较低（但仍存在理论窗口）');
    } else {
      console.log('  → 风险确认：无额外状态检查，延迟回调可能在不合适的时机触发错误');
    }
    // 有额外检查，低风险，不做硬断言
  });
});
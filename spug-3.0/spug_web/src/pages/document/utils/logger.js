/**
 * logger - 按环境分级的轻量日志器
 *
 * 设计原则（行业惯例 + YAGNI）：
 * - 生产（NODE_ENV=production）：只输出 error（避免 F12 控制台刷屏、泄露内部信息）
 * - 开发（NODE_ENV=development）：debug/info/warn/error 全部输出
 * - 显式 debug()：永远只在 dev 输出（高频诊断）
 * - 命名空间 (createLogger)：替代原 console.log('[UploadStateMachine] ...') 的前缀风格
 *
 * 行为参考：
 * - 百度网盘：生产无 console
 * - 阿里云盘：生产无 console
 * - 行业惯例：production bundle 中 console.log 会被 tree-shake / 死代码消除
 *
 * 使用：
 *   import { logger } from '@/pages/document/utils/logger';
 *   logger.debug('xxx', data);          // 仅 dev
 *   logger.info('xxx');                 // 仅 dev
 *   logger.warn('xxx');                 // 仅 dev
 *   logger.error('xxx', error);         // 永远输出（含生产）
 *
 *   const log = createLogger('UploadStateMachine');
 *   log.debug('转换状态', from, to);    // 输出: [UploadStateMachine] 转换状态 A -> B
 *   log.error('失败', error);
 */

const isDev = process.env.NODE_ENV !== 'production';

function formatArgs(args) {
  return args.map((arg) => {
    if (arg instanceof Error) {
      return `${arg.message}${arg.stack ? `\n${arg.stack}` : ''}`;
    }
    if (typeof arg === 'object') {
      try {
        return JSON.stringify(arg);
      } catch (e) {
        return String(arg);
      }
    }
    return arg;
  });
}

function emit(level, args) {
  // 永远在 error 级别输出，无论环境
  if (level === 'error') {
    // eslint-disable-next-line no-console
    console.error(...formatArgs(args));
    return;
  }
  // 其他级别只在 dev 输出
  if (!isDev) return;
  // eslint-disable-next-line no-console
  const fn = console[level] || console.log;
  fn(...formatArgs(args));
}

export const logger = {
  debug: (...args) => emit('debug', args),
  info: (...args) => emit('info', args),
  warn: (...args) => emit('warn', args),
  error: (...args) => emit('error', args),
};

/**
 * 创建带命名空间的 logger
 * 自动给消息加 [namespace] 前缀
 */
export function createLogger(namespace) {
  const prefix = `[${namespace}]`;
  return {
    debug: (...args) => emit('debug', [prefix, ...args]),
    info: (...args) => emit('info', [prefix, ...args]),
    warn: (...args) => emit('warn', [prefix, ...args]),
    error: (...args) => emit('error', [prefix, ...args]),
  };
}

export default logger;

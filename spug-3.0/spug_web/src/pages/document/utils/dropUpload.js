/**
 * 拖拽上传工具模块
 *
 * 职责（单一）：
 *   1. 解析 DataTransfer，区分普通文件和文件夹（Chromium webkitGetAsEntry）
 *   2. 递归读取目录条目，规范化为 {file, relativePath, rootName}
 *   3. 保护上限：最大深度 20、单次最大条目数 5000、定期让出事件循环
 *   4. 路径安全校验：拒绝 ..、绝对路径、空字节、异常分隔符
 *
 * 不负责：
 *   - 上传请求（由 uploadCoreStore 处理）
 *   - 队列状态（由 queueStore 处理）
 *   - UI 交互（由 DocumentDropUploadLayer 处理）
 *
 * 兼容性：
 *   - Chrome/Edge：支持普通文件 + 目录拖入
 *   - Firefox/Safari：仅支持普通文件拖入（webkitGetAsEntry 不可用时回退到 dataTransfer.files）
 */

// ============ 保护上限常量 ============

/** 目录递归最大深度（防止恶意嵌套目录卡死浏览器） */
export const MAX_DROP_DEPTH = 20;
/** 单次 drop 解析的最大条目数（超过后停止并标记 truncated） */
export const MAX_DROP_ENTRIES = 5000;
/** 每解析 N 个条目让出一次事件循环，避免页面无响应 */
const YIELD_INTERVAL = 50;

// ============ 浏览器能力检测 ============

/**
 * 检测当前浏览器是否支持目录拖入（webkitGetAsEntry）
 */
export function supportsDirectoryDrop() {
  return typeof DataTransferItem !== 'undefined' &&
    typeof DataTransferItem.prototype.webkitGetAsEntry === 'function';
}

/**
 * 判断 DataTransfer 是否包含文件类型（用于过滤页面内 DOM 拖动）
 */
export function hasFilesType(dataTransfer) {
  if (!dataTransfer || !dataTransfer.types) return false;
  // dataTransfer.types 是 DOMStringList 或数组，统一转数组判断
  const types = Array.from(dataTransfer.types);
  return types.includes('Files');
}

// ============ 路径安全校验 ============

/**
 * 校验相对路径安全性
 * 拒绝：空路径、空字节、.. 穿越符号、绝对路径（/ \ 和 Windows 盘符）
 *
 * @param {string} path - 相对路径，如 '顶层目录/子目录/文件.pdf'
 * @returns {{valid: boolean, message?: string}}
 */
export function validateRelativePath(path) {
  if (!path || typeof path !== 'string') {
    return { valid: false, message: '路径为空' };
  }
  if (path.includes('\0')) {
    return { valid: false, message: '路径包含空字节' };
  }
  if (path.includes('..')) {
    return { valid: false, message: '路径包含非法的上级目录引用' };
  }
  if (path.startsWith('/') || path.startsWith('\\')) {
    return { valid: false, message: '路径不能为绝对路径' };
  }
  // Windows 盘符绝对路径，如 C:\ 或 D:/
  if (/^[a-zA-Z]:[\\\/]/.test(path)) {
    return { valid: false, message: '路径不能为绝对路径' };
  }
  return { valid: true };
}

// ============ 统一条目读取辅助 ============

/**
 * 从规范化条目或 File 对象获取 File
 * 兼容两种输入：
 *   - 拖拽条目 {file, relativePath, rootName} → 返回 entry.file
 *   - File 对象（按钮上传 webkitRelativePath）→ 返回 file 本身
 */
export function getEntryFile(entry) {
  if (!entry) return null;
  if (entry.file instanceof File) return entry.file;
  if (entry instanceof File) return entry;
  return null;
}

/**
 * 从规范化条目或 File 对象获取相对路径
 * 兼容两种输入：
 *   - 拖拽条目 {file, relativePath, rootName} → 返回 entry.relativePath
 *   - File 对象（按钮上传）→ 返回 file.webkitRelativePath || file.name
 */
export function getEntryRelativePath(entry) {
  if (!entry) return '';
  if (typeof entry.relativePath === 'string') return entry.relativePath;
  if (entry instanceof File) return entry.webkitRelativePath || entry.name;
  return '';
}

// ============ 内部：FileSystemEntry 异步读取 ============

/**
 * Promise 包装 FileSystemFileEntry.file()
 */
function readEntryFile(fileEntry) {
  return new Promise((resolve, reject) => {
    if (!fileEntry || typeof fileEntry.file !== 'function') {
      reject(new Error('无效的文件条目'));
      return;
    }
    fileEntry.file(resolve, reject);
  });
}

/**
 * 循环读取 FileSystemDirectoryReader.readEntries() 直到返回空数组
 *
 * 关键：readEntries 一次只返回部分结果，必须循环调用直到返回空数组，
 * 否则会遗漏文件（尤其是大目录）。
 */
function readAllEntries(dirReader) {
  return new Promise((resolve, reject) => {
    const all = [];
    const readBatch = () => {
      dirReader.readEntries((batch) => {
        if (batch && batch.length > 0) {
          all.push(...batch);
          readBatch(); // 继续读下一批
        } else {
          resolve(all);
        }
      }, reject);
    };
    readBatch();
  });
}

// ============ 内部：递归遍历目录 ============

/**
 * 递归遍历 FileSystemEntry，收集所有文件为规范化条目
 *
 * @param {FileSystemEntry} entry - 文件或目录条目
 * @param {string} path - 当前累积的相对路径前缀（不含 entry 自身名称）
 * @param {number} depth - 当前深度（从 1 开始）
 * @param {Object} state - 收集状态（entries/count/rootName/标志位）
 * @private
 */
async function traverseEntry(entry, path, depth, state) {
  // 超过条目上限，停止收集
  if (state.count >= MAX_DROP_ENTRIES) {
    state.entryLimitExceeded = true;
    return;
  }
  // 超过深度上限，标记并停止
  if (depth > MAX_DROP_DEPTH) {
    state.depthExceeded = true;
    return;
  }

  if (entry && entry.isFile) {
    try {
      const file = await readEntryFile(entry);
      if (!file) return;
      // relativePath 包含完整路径（顶层目录名/子目录/.../文件名），
      // FolderStructureBuilder 据此创建子目录结构
      const relativePath = path ? `${path}/${file.name}` : file.name;
      const pathCheck = validateRelativePath(relativePath);
      if (!pathCheck.valid) {
        state.invalidPaths = state.invalidPaths || [];
        state.invalidPaths.push(relativePath);
        return;
      }
      state.entries.push({
        file,
        relativePath,
        rootName: state.rootName,
      });
      state.count += 1;
      // 定期让出事件循环，避免大量文件解析时页面无响应
      if (state.count % YIELD_INTERVAL === 0) {
        await new Promise(resolve => setTimeout(resolve, 0));
      }
    } catch (e) {
      state.readErrors = state.readErrors || [];
      state.readErrors.push(entry.name || 'unknown');
    }
  } else if (entry && entry.isDirectory) {
    const dirName = entry.name || '';
    // 子目录路径：path/dirName
    const childPath = path ? `${path}/${dirName}` : dirName;
    try {
      const reader = entry.createReader();
      const children = await readAllEntries(reader);
      for (const child of children) {
        if (state.count >= MAX_DROP_ENTRIES) {
          state.entryLimitExceeded = true;
          break;
        }
        await traverseEntry(child, childPath, depth + 1, state);
      }
    } catch (e) {
      state.readErrors = state.readErrors || [];
      state.readErrors.push(dirName || 'unknown');
    }
  }
}

// ============ 主入口：collectDroppedItems ============

/**
 * 解析 drop 事件的 DataTransfer，收集所有文件
 *
 * 返回结构：
 *   {
 *     files: File[],                          // 所有文件（普通+文件夹内）
 *     entries: [{file, relativePath, rootName}], // 规范化条目（供 handleFolderEntries）
 *     hasFolder: boolean,                     // 是否包含文件夹
 *     errors: string[],                       // 解析错误/警告信息
 *     truncated: boolean,                     // 是否因条目数超限被截断
 *     depthExceeded: boolean,                 // 是否有目录超过最大深度
 *   }
 *
 * 解析策略：
 *   1. 优先用 dataTransfer.items + webkitGetAsEntry（Chromium，支持目录）
 *   2. 回退到 dataTransfer.files（Firefox/Safari，仅普通文件）
 *
 * 注意：webkitGetAsEntry 必须在 drop 事件同步阶段调用（DataTransferItemList 事件后失效），
 *      所以本函数在开头同步收集所有 entry，再异步递归遍历。
 *
 * @param {DataTransfer} dataTransfer - drop 事件的 dataTransfer
 * @returns {Promise<Object>}
 */
export async function collectDroppedItems(dataTransfer) {
  const result = {
    files: [],
    entries: [],
    hasFolder: false,
    errors: [],
    truncated: false,
    depthExceeded: false,
  };

  if (!dataTransfer) {
    result.errors.push('无拖拽数据');
    return result;
  }

  // 优先用 webkitGetAsEntry 解析（Chromium 支持目录）
  const items = dataTransfer.items;
  if (items && items.length > 0 && supportsDirectoryDrop()) {
    // 同步阶段：收集所有 entry（必须在 drop 事件同步阶段完成）
    const topEntries = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind !== 'file') continue;
      let entry = null;
      try {
        entry = item.webkitGetAsEntry();
      } catch (e) {
        // 忽略单条解析失败，后续用 dataTransfer.files 兜底
      }
      if (entry) {
        topEntries.push(entry);
      }
    }

    if (topEntries.length > 0) {
      // 异步阶段：按顶层来源分组递归遍历
      for (const entry of topEntries) {
        if (entry.isDirectory) {
          result.hasFolder = true;
        }
        const rootName = entry.name || '';
        const state = {
          entries: [],
          count: 0,
          rootName,
          depthExceeded: false,
          entryLimitExceeded: false,
        };
        // 顶层 entry 的初始 path 恒为空：
        //   - 目录：traverseEntry 进入 isDirectory 分支时会用 entry.name 拼路径（childPath = 'rootName'）
        //     若 initialPath 非空会导致 'rootName/rootName' 重复
        //   - 文件：relativePath 直接等于 file.name（落在当前目录，不创建子目录）
        const initialPath = '';
        await traverseEntry(entry, initialPath, 1, state);

        if (state.depthExceeded) result.depthExceeded = true;
        if (state.entryLimitExceeded) result.truncated = true;
        if (state.invalidPaths && state.invalidPaths.length > 0) {
          result.errors.push(`路径非法被跳过: ${state.invalidPaths.slice(0, 5).join(', ')}${state.invalidPaths.length > 5 ? ' 等' : ''}`);
        }
        if (state.readErrors && state.readErrors.length > 0) {
          result.errors.push(`读取失败: ${state.readErrors.slice(0, 5).join(', ')}${state.readErrors.length > 5 ? ' 等' : ''}`);
        }
        result.entries.push(...state.entries);
      }

      // 从 entries 提取 files（统一出口）
      if (result.entries.length > 0) {
        result.files = result.entries.map(e => e.file);
      }
      return result;
    }
  }

  // 回退：用 dataTransfer.files（Firefox/Safari 或无 webkitGetAsEntry 支持）
  const files = dataTransfer.files;
  if (files && files.length > 0) {
    result.files = Array.from(files);
    result.entries = result.files.map(f => ({
      file: f,
      relativePath: f.name,
      rootName: f.name,
    }));
    result.hasFolder = false;
  }

  return result;
}

/**
 * 判断收集结果是否为空文件夹批次（用于提示"空文件夹无需上传"）
 */
export function isEmptyFolderBatch(collected) {
  return !!(collected && collected.hasFolder && collected.entries.length === 0 && collected.files.length === 0);
}

/**
 * 判断收集结果是否仅有普通文件（无文件夹），可直接走 handleFileSelect
 */
export function isPlainFilesOnly(collected) {
  return !!(collected && !collected.hasFolder && collected.files.length > 0);
}

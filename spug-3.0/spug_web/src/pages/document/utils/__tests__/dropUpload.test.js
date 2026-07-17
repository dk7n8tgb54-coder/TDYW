/**
 * dropUpload.js 工具模块单元测试
 *
 * 覆盖场景（prompt 12.1）：
 *   - 普通单文件 / 多文件
 *   - 单个嵌套目录 / 多个顶层目录
 *   - 普通文件与目录混合
 *   - readEntries() 多批返回不遗漏
 *   - 空目录
 *   - 目录深度超限
 *   - 文件数量超限
 *   - 读取异常
 *   - 不支持 webkitGetAsEntry 时回退
 *   - 路径安全校验
 */
import {
  collectDroppedItems,
  hasFilesType,
  supportsDirectoryDrop,
  validateRelativePath,
  getEntryFile,
  getEntryRelativePath,
  isEmptyFolderBatch,
  isPlainFilesOnly,
  MAX_DROP_DEPTH,
  MAX_DROP_ENTRIES,
} from '../dropUpload';

// ============ Mock 工厂：构造 fake FileSystemEntry / DataTransfer ============

/**
 * 构造 fake file entry
 */
function makeFileEntry(name, fileContent = 'x') {
  return {
    isFile: true,
    isDirectory: false,
    name,
    file: (cb) => cb(new File([fileContent], name)),
  };
}

/**
 * 构造 fake directory entry
 * @param {string} name - 目录名
 * @param {Array} children - 子条目
 * @param {Object} [options]
 * @param {Array[]} [options.readBatches] - readEntries 分批返回（测试多批读取）
 * @param {boolean} [options.readFail] - 读取失败（测试读取异常）
 */
function makeDirEntry(name, children, options = {}) {
  const { readBatches, readFail } = options;
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => {
      let callCount = 0;
      const batches = readBatches || [children];
      return {
        readEntries: (cb, errCb) => {
          if (readFail) {
            errCb(new Error('读取目录失败'));
            return;
          }
          if (callCount < batches.length) {
            const batch = batches[callCount++];
            cb(batch);
          } else {
            cb([]);
          }
        },
      };
    },
  };
}

/**
 * 构造 fake DataTransfer
 * @param {Array} entries - 顶层 entry 数组
 * @param {boolean} [withFilesFallback=true] - 是否同时填充 dataTransfer.files（回退用）
 */
function makeDataTransfer(entries, withFilesFallback = true) {
  const items = entries.map(entry => ({
    kind: 'file',
    webkitGetAsEntry: () => entry,
  }));
  const files = withFilesFallback
    ? entries.filter(e => e.isFile).map(e => new File(['x'], e.name))
    : [];
  return {
    items,
    files,
    types: ['Files'],
  };
}

// ============ 全局 Mock：DataTransferItem.prototype.webkitGetAsEntry ============
// supportsDirectoryDrop 检查此属性，需在全局定义

beforeAll(() => {
  if (typeof global.DataTransferItem === 'undefined') {
    global.DataTransferItem = function DataTransferItem() {};
  }
  global.DataTransferItem.prototype.webkitGetAsEntry = function webkitGetAsEntry() {
    return null;
  };
});

afterAll(() => {
  delete global.DataTransferItem.prototype.webkitGetAsEntry;
});

// ============ 纯函数测试 ============

describe('dropUpload - 纯函数', () => {
  describe('validateRelativePath', () => {
    it('合法相对路径通过', () => {
      expect(validateRelativePath('a/b/c.txt').valid).toBe(true);
      expect(validateRelativePath('顶层目录/子目录/文件.pdf').valid).toBe(true);
      expect(validateRelativePath('file.txt').valid).toBe(true);
    });

    it('空路径拒绝', () => {
      expect(validateRelativePath('').valid).toBe(false);
      expect(validateRelativePath(null).valid).toBe(false);
      expect(validateRelativePath(undefined).valid).toBe(false);
    });

    it('空字节拒绝', () => {
      expect(validateRelativePath('a\0b').valid).toBe(false);
    });

    it('.. 穿越符号拒绝', () => {
      expect(validateRelativePath('../etc/passwd').valid).toBe(false);
      expect(validateRelativePath('a/../../b').valid).toBe(false);
    });

    it('绝对路径拒绝（Unix 和 Windows）', () => {
      expect(validateRelativePath('/etc/passwd').valid).toBe(false);
      expect(validateRelativePath('\\windows\\system32').valid).toBe(false);
      expect(validateRelativePath('C:\\Users').valid).toBe(false);
      expect(validateRelativePath('D:/data').valid).toBe(false);
    });
  });

  describe('hasFilesType', () => {
    it('包含 Files 返回 true', () => {
      expect(hasFilesType({ types: ['Files'] })).toBe(true);
      expect(hasFilesType({ types: { 0: 'Files', length: 1 } })).toBe(true);
    });

    it('不包含 Files 返回 false', () => {
      expect(hasFilesType({ types: ['text/plain'] })).toBe(false);
      expect(hasFilesType({ types: ['text/html', 'text/uri-list'] })).toBe(false);
    });

    it('null/undefined 返回 false', () => {
      expect(hasFilesType(null)).toBe(false);
      expect(hasFilesType(undefined)).toBe(false);
      expect(hasFilesType({})).toBe(false);
    });
  });

  describe('supportsDirectoryDrop', () => {
    it('定义了 webkitGetAsEntry 返回 true', () => {
      expect(supportsDirectoryDrop()).toBe(true);
    });
  });

  describe('getEntryFile / getEntryRelativePath', () => {
    it('从规范化条目读取 file 和 relativePath', () => {
      const file = new File(['x'], 'a.txt');
      const entry = { file, relativePath: 'dir/a.txt', rootName: 'dir' };
      expect(getEntryFile(entry)).toBe(file);
      expect(getEntryRelativePath(entry)).toBe('dir/a.txt');
    });

    it('从 File 对象读取（按钮上传兼容）', () => {
      const file = new File(['x'], 'a.txt');
      Object.defineProperty(file, 'webkitRelativePath', { value: 'dir/a.txt', configurable: true });
      expect(getEntryFile(file)).toBe(file);
      expect(getEntryRelativePath(file)).toBe('dir/a.txt');
    });

    it('null/空对象返回安全值', () => {
      expect(getEntryFile(null)).toBe(null);
      expect(getEntryRelativePath(null)).toBe('');
      expect(getEntryFile({})).toBe(null);
      expect(getEntryRelativePath({})).toBe('');
    });
  });

  describe('isEmptyFolderBatch / isPlainFilesOnly', () => {
    it('空文件夹批次识别', () => {
      expect(isEmptyFolderBatch({ hasFolder: true, entries: [], files: [] })).toBe(true);
      expect(isEmptyFolderBatch({ hasFolder: false, entries: [], files: [] })).toBe(false);
      expect(isEmptyFolderBatch({ hasFolder: true, entries: [{}], files: [{}] })).toBe(false);
    });

    it('纯普通文件识别', () => {
      expect(isPlainFilesOnly({ hasFolder: false, files: [{}] })).toBe(true);
      expect(isPlainFilesOnly({ hasFolder: true, files: [{}] })).toBe(false);
      expect(isPlainFilesOnly({ hasFolder: false, files: [] })).toBe(false);
    });
  });
});

// ============ collectDroppedItems 测试 ============

describe('collectDroppedItems', () => {
  it('普通单文件', async () => {
    const dt = makeDataTransfer([makeFileEntry('a.txt')]);
    const result = await collectDroppedItems(dt);
    expect(result.files.length).toBe(1);
    expect(result.files[0].name).toBe('a.txt');
    expect(result.entries.length).toBe(1);
    expect(result.entries[0].relativePath).toBe('a.txt');
    expect(result.hasFolder).toBe(false);
  });

  it('多文件', async () => {
    const dt = makeDataTransfer([
      makeFileEntry('a.txt'),
      makeFileEntry('b.txt'),
      makeFileEntry('c.txt'),
    ]);
    const result = await collectDroppedItems(dt);
    expect(result.files.length).toBe(3);
    expect(result.entries.map(e => e.file.name).sort()).toEqual(['a.txt', 'b.txt', 'c.txt']);
    expect(result.hasFolder).toBe(false);
  });

  it('单个嵌套目录', async () => {
    const inner = makeFileEntry('inner.txt');
    const sub = makeDirEntry('sub', [inner]);
    const root = makeDirEntry('root', [sub]);
    const dt = makeDataTransfer([root]);
    const result = await collectDroppedItems(dt);
    expect(result.hasFolder).toBe(true);
    expect(result.entries.length).toBe(1);
    expect(result.entries[0].file.name).toBe('inner.txt');
    expect(result.entries[0].relativePath).toBe('root/sub/inner.txt');
    expect(result.entries[0].rootName).toBe('root');
  });

  it('多个顶层目录', async () => {
    const dir1 = makeDirEntry('dir1', [makeFileEntry('a.txt')]);
    const dir2 = makeDirEntry('dir2', [makeFileEntry('b.txt')]);
    const dt = makeDataTransfer([dir1, dir2]);
    const result = await collectDroppedItems(dt);
    expect(result.hasFolder).toBe(true);
    expect(result.entries.length).toBe(2);
    const paths = result.entries.map(e => e.relativePath).sort();
    expect(paths).toEqual(['dir1/a.txt', 'dir2/b.txt']);
  });

  it('普通文件与目录混合', async () => {
    const plainFile = makeFileEntry('plain.txt');
    const dir = makeDirEntry('folder', [makeFileEntry('inside.txt')]);
    const dt = makeDataTransfer([plainFile, dir]);
    const result = await collectDroppedItems(dt);
    expect(result.hasFolder).toBe(true);
    expect(result.entries.length).toBe(2);
    const byPath = result.entries.reduce((acc, e) => {
      acc[e.relativePath] = e;
      return acc;
    }, {});
    expect(byPath['plain.txt']).toBeDefined();
    expect(byPath['folder/inside.txt']).toBeDefined();
  });

  it('readEntries 多批返回不遗漏', async () => {
    // 模拟 readEntries 分两批返回：第一批 2 个，第二批 1 个，第三批空
    const file1 = makeFileEntry('f1.txt');
    const file2 = makeFileEntry('f2.txt');
    const file3 = makeFileEntry('f3.txt');
    const dir = makeDirEntry('multi', null, {
      readBatches: [[file1, file2], [file3]],
    });
    const dt = makeDataTransfer([dir]);
    const result = await collectDroppedItems(dt);
    expect(result.entries.length).toBe(3);
    const names = result.entries.map(e => e.file.name).sort();
    expect(names).toEqual(['f1.txt', 'f2.txt', 'f3.txt']);
  });

  it('空目录', async () => {
    const dir = makeDirEntry('empty', []);
    const dt = makeDataTransfer([dir]);
    const result = await collectDroppedItems(dt);
    expect(result.hasFolder).toBe(true);
    expect(result.entries.length).toBe(0);
    expect(result.files.length).toBe(0);
    expect(isEmptyFolderBatch(result)).toBe(true);
  });

  it('目录深度超限被标记', async () => {
    // 构造深度 = MAX_DROP_DEPTH + 2 的嵌套目录
    let deepest = makeFileEntry('deep.txt');
    for (let i = 0; i < MAX_DROP_DEPTH + 2; i++) {
      deepest = makeDirEntry(`d${i}`, [deepest]);
    }
    const dt = makeDataTransfer([deepest]);
    const result = await collectDroppedItems(dt);
    expect(result.depthExceeded).toBe(true);
    // 深度超限的文件不应被收集
    expect(result.entries.length).toBe(0);
  });

  it('文件数量超限被截断', async () => {
    // 构造超过 MAX_DROP_ENTRIES 的文件
    const files = [];
    for (let i = 0; i < MAX_DROP_ENTRIES + 100; i++) {
      files.push(makeFileEntry(`f${i}.txt`));
    }
    // 分批返回避免一次过多
    const batches = [];
    for (let i = 0; i < files.length; i += 100) {
      batches.push(files.slice(i, i + 100));
    }
    const dir = makeDirEntry('huge', null, { readBatches: batches });
    const dt = makeDataTransfer([dir]);
    const result = await collectDroppedItems(dt);
    expect(result.truncated).toBe(true);
    expect(result.entries.length).toBeLessThanOrEqual(MAX_DROP_ENTRIES);
  });

  it('读取异常被记录到 errors', async () => {
    const dir = makeDirEntry('faildir', null, { readFail: true });
    const dt = makeDataTransfer([dir]);
    const result = await collectDroppedItems(dt);
    expect(result.hasFolder).toBe(true);
    expect(result.entries.length).toBe(0);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it('不支持 webkitGetAsEntry 时回退到 dataTransfer.files', async () => {
    // 临时移除 webkitGetAsEntry 支持
    const originalFn = global.DataTransferItem.prototype.webkitGetAsEntry;
    delete global.DataTransferItem.prototype.webkitGetAsEntry;

    const file = new File(['x'], 'fallback.txt');
    const dt = {
      items: [{ kind: 'file' }],
      files: [file],
      types: ['Files'],
    };
    const result = await collectDroppedItems(dt);
    expect(result.files.length).toBe(1);
    expect(result.files[0].name).toBe('fallback.txt');
    expect(result.hasFolder).toBe(false);

    // 恢复
    global.DataTransferItem.prototype.webkitGetAsEntry = originalFn;
  });

  it('null dataTransfer 返回空结果', async () => {
    const result = await collectDroppedItems(null);
    expect(result.files.length).toBe(0);
    expect(result.entries.length).toBe(0);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it('路径非法被跳过', async () => {
    // 构造一个 file.name 含 .. 的异常 entry（模拟恶意输入）
    const maliciousFile = {
      isFile: true,
      isDirectory: false,
      name: '../escape.txt',
      file: (cb) => cb(new File(['x'], '../escape.txt')),
    };
    const dir = makeDirEntry('dir', [maliciousFile]);
    const dt = makeDataTransfer([dir]);
    const result = await collectDroppedItems(dt);
    expect(result.entries.length).toBe(0);
    expect(result.errors.some(e => e.includes('路径非法'))).toBe(true);
  });
});

/**
 * FolderStructureBuilder - 文件夹结构构建器
 *
 * 职责（单一）：
 *   1. 从文件列表解析出需要创建的文件夹路径（全路径展开+去重）
 *   2. 按深度分组，逐层并发创建（同层可并行，跨层必须串行）
 *   3. 区分本次创建和复用的文件夹，支持失败回滚
 *
 * 设计原则：
 *   - 全路径展开：从 A/B/C/file.txt 提取 A, A/B, A/B/C 三条路径
 *   - 按层创建：先创建所有 1 层，再 2 层，再 3 层
 *   - 只创建最后一级：创建 A/B/C 时只创建 C，父 ID 从 folderMap 拿
 *   - 后端幂等：同名同父重复 POST 返回已有 ID，前端无需预查
 *
 * 拆分自：原 folderUpload.js (2026-06-06 重构，2026-06-11 幂等改造)
 */
import { action } from 'mobx';

const FOLDER_API_BASE = '/api/document/folder/';
const CONCURRENCY = 3; // 同深度并发创建数

export class FolderStructureBuilder {
  constructor() {
    // 状态：本次会话内创建的文件夹 ID（用于回滚）
    this._createdByThisInstance = new Set();
    // 状态：复用的历史文件夹 ID（回滚时不删除）
    this._reusedFolderIds = new Set();
    // 状态：路径 → ID 缓存
    this._folderMap = new Map();
  }

  // ============================================================
  // 公共 API
  // ============================================================

  /**
   * 构建文件夹结构
   *
   * 支持两种输入格式（按钮上传 / 拖拽上传 共用）：
   *   1. File[]：每个 File 带 webkitRelativePath（按钮 webkitdirectory 选择）
   *   2. Array<{file, relativePath, rootName}>：拖拽 webkitGetAsEntry 规范化后的条目
   *
   * @param {File[]|Array<{file, relativePath}>} filesOrEntries - 文件列表或规范化条目
   * @param {number|null} rootTargetId - 根目标文件夹 ID（null 表示根目录）
   * @param {boolean} isPublic - 是否公共空间
   * @param {string|null} [systemFolderCode=null] - 系统目录 code（党建工作场景必传）
   *   显式传入后，创建文件夹的 POST 请求会显式带 system_folder 参数，
   *   不依赖 http.js 拦截器（党建任务离开党建路由后仍能正确创建子目录）
   * @returns {Promise<Map<string, number>>} folderMap (path → folderId)
   */
  @action
  async build(filesOrEntries, rootTargetId, isPublic, systemFolderCode = null) {
    this._reset();
    this._systemFolderCode = systemFolderCode || null;
    const depthGroups = this._extractDepthGroups(filesOrEntries);
    await this._createByDepth(depthGroups, rootTargetId, isPublic);
    return this._folderMap;
  }

  /**
   * 回滚本次创建的文件夹（保留复用的历史文件夹）
   */
  async rollback() {
    if (this._createdByThisInstance.size === 0) return;

    console.warn('[FolderStructureBuilder] 回滚本次创建的文件夹:', this._createdByThisInstance.size);
    const { http } = await import('libs');

    // 逆序删除（从叶子到根）
    for (const folderId of [...this._createdByThisInstance].reverse()) {
      try {
        await http.delete(`${FOLDER_API_BASE}${folderId}/`);
      } catch (e) {
        console.error(`[FolderStructureBuilder] 回滚文件夹 ${folderId} 失败:`, e);
      }
    }
    this._reset();
  }

  /**
   * 获取本次创建的文件夹 ID 数量
   */
  get createdCount() {
    return this._createdByThisInstance.size;
  }

  // ============================================================
  // 内部方法
  // ============================================================

  _reset() {
    this._createdByThisInstance.clear();
    this._reusedFolderIds.clear();
    this._folderMap.clear();
    this._systemFolderCode = null;
  }

  /**
   * 从文件列表提取所有祖先路径，去重后按深度分组
   *
   * 支持两种输入：
   *   - File：使用 file.webkitRelativePath（按钮上传）
   *   - {file, relativePath}：使用 entry.relativePath（拖拽上传）
   *
   * 例如文件 A/B/C/file.txt 会产生 3 条路径：
   *   A          (depth=1)
   *   A/B        (depth=2)
   *   A/B/C      (depth=3)
   *
   * 这样创建 A/B/C 时只需创建 C，父 ID 从 folderMap.get('A/B') 拿。
   * 不再让每条叶子路径都从 A 开始递归创建，避免并发重复。
   *
   * @param {File[]|Array<{file, relativePath}>} filesOrEntries
   * @returns {Map<number, string[]>} depth → paths
   */
  _extractDepthGroups(filesOrEntries) {
    const allPaths = new Set();

    filesOrEntries.forEach(entry => {
      // 兼容 File（按钮上传）和 {file, relativePath}（拖拽上传）两种格式
      const relativePath = (entry && entry.relativePath) || entry.webkitRelativePath || entry.name;
      const parts = relativePath.split('/').slice(0, -1); // 去掉文件名

      // 展开所有祖先路径：A, A/B, A/B/C
      for (let i = 1; i <= parts.length; i++) {
        allPaths.add(parts.slice(0, i).join('/'));
      }
    });

    const depthGroups = new Map();
    [...allPaths].forEach(path => {
      const depth = path.split('/').length;
      if (!depthGroups.has(depth)) depthGroups.set(depth, []);
      depthGroups.get(depth).push(path);
    });

    return depthGroups;
  }

  /**
   * 按深度顺序逐层创建（先浅后深，同层并发）
   */
  async _createByDepth(depthGroups, rootTargetId, isPublic) {
    const sortedDepths = Array.from(depthGroups.keys()).sort((a, b) => a - b);

    for (const depth of sortedDepths) {
      const paths = depthGroups.get(depth);
      await this._runInBatches(
        paths,
        async (path) => {
          const folderId = await this._createSinglePath(path, rootTargetId, isPublic);
          this._folderMap.set(path, folderId);
        },
        CONCURRENCY
      );
    }
  }

  /**
   * 创建单条路径的文件夹（只创建最后一级）
   *
   * 例如路径 "A/B/C"：
   *   - folderName = "C"
   *   - parentPath = "A/B"
   *   - parentId = folderMap.get("A/B") （上一轮已创建）
   *   - 如果 parentId 不存在则 fallback 到 rootTargetId
   *
   * 后端幂等保证：即使并发重复请求，也返回已有 ID。
   */
  async _createSinglePath(path, rootTargetId, isPublic) {
    // 已有缓存（同层去重或前序批次已创建）
    if (this._folderMap.has(path)) {
      return this._folderMap.get(path);
    }

    const parts = path.split('/');
    const folderName = parts[parts.length - 1];
    const parentPath = parts.slice(0, -1).join('/');
    const parentId = parentPath ? (this._folderMap.get(parentPath) || rootTargetId) : rootTargetId;

    const folderId = await this._createOne(folderName, parentId, isPublic);
    this._folderMap.set(path, folderId);
    return folderId;
  }

  /**
   * 创建单个文件夹（后端幂等：同名同父返回已有 ID）
   *
   * 【拖拽上传】显式传 system_folder 到 folder create API：
   *   - 党建任务离开党建路由后，http.js 拦截器不再注入 system_folder（路由已变）
   *   - 但队列项保存的 systemFolderCode 仍指向党建工作
   *   - 因此这里必须显式传 system_folder，后端才能把子目录创建到党建根下
   */
  async _createOne(name, parentId, isPublic) {
    const { http } = await import('libs');
    const params = {
      name,
      parent_id: parentId,
      is_public: isPublic,
    };

    // 显式传 system_folder，不依赖 http.js 拦截器
    if (this._systemFolderCode) {
      params.system_folder = this._systemFolderCode;
    }

    const tenantId = null;
    if (tenantId) {
      params.tenant_id = tenantId;
    }

    const result = await http.post(FOLDER_API_BASE, params);
    // 后端幂等返回 { id, created }，created=false 表示复用了已有目录
    if (result.created === false) {
      this._reusedFolderIds.add(result.id);
    } else {
      this._createdByThisInstance.add(result.id);
    }
    return result.id;
  }

  /**
   * 分批并发执行
   */
  async _runInBatches(items, processor, concurrency) {
    const results = [];
    for (let i = 0; i < items.length; i += concurrency) {
      const batch = items.slice(i, i + concurrency);
      const batchResults = await Promise.all(batch.map(processor));
      results.push(...batchResults);
    }
    return results;
  }
}

export default FolderStructureBuilder;

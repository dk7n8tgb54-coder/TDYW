/**
 * FolderStructureBuilder - 文件夹结构构建器
 *
 * 职责（单一）：
 *   1. 从文件列表解析出需要创建的文件夹路径
 *   2. 按深度分组，并发创建（避免同层级竞态）
 *   3. 区分本次创建和复用的文件夹，支持失败回滚
 *
 * 设计原则：
 *   - 状态自管理：folderMap, createdByThisInstance, reusedFolderIds 都在实例内
 *   - 无副作用：构建过程不修改外部状态（除了调用 HTTP 接口）
 *   - 可测试：所有依赖通过参数或方法注入
 *
 * 拆分自：原 folderUpload.js (2026-06-06 重构)
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
   * @param {File[]} files - 带 webkitRelativePath 的文件列表
   * @param {number|null} rootTargetId - 根目标文件夹 ID（null 表示根目录）
   * @param {boolean} isPublic - 是否公共空间
   * @returns {Promise<Map<string, number>>} folderMap (path → folderId)
   */
  @action
  async build(files, rootTargetId, isPublic) {
    this._reset();
    const depthGroups = this._extractDepthGroups(files);
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
  }

  /**
   * 从文件列表提取所有唯一路径，按深度分组
   * @returns {Map<number, string[]>} depth → paths
   */
  _extractDepthGroups(files) {
    const paths = [...new Set(
      files
        .map(f => (f.webkitRelativePath || f.name).split('/').slice(0, -1).join('/'))
        .filter(p => p)
    )];

    const depthGroups = new Map();
    paths.forEach(path => {
      const depth = path.split('/').length;
      if (!depthGroups.has(depth)) depthGroups.set(depth, []);
      depthGroups.get(depth).push(path);
    });

    return depthGroups;
  }

  /**
   * 按深度顺序逐层创建（先浅后深）
   */
  async _createByDepth(depthGroups, rootTargetId, isPublic) {
    const sortedDepths = Array.from(depthGroups.keys()).sort((a, b) => a - b);

    for (const depth of sortedDepths) {
      const paths = depthGroups.get(depth);
      await this._runInBatches(
        paths,
        async (path) => {
          const folderId = await this._createPathStructure(path, rootTargetId, isPublic);
          this._folderMap.set(path, folderId);
        },
        CONCURRENCY
      );
    }
  }

  /**
   * 创建单条路径的文件夹结构（支持多层级）
   * 例如路径 "docs/2024/reports" 会逐级创建
   */
  async _createPathStructure(folderPath, parentFolderId, isPublic) {
    const pathParts = folderPath.split('/');
    let currentParentId = parentFolderId;
    let currentPath = '';

    for (const folderName of pathParts) {
      currentPath = currentPath ? `${currentPath}/${folderName}` : folderName;

      // 1. 检查本地缓存
      const cachedId = this._folderMap.get(currentPath);
      if (cachedId) {
        currentParentId = cachedId;
        this._reusedFolderIds.add(currentParentId);
        continue;
      }

      // 2. 服务端幂等检查
      const existingId = await this._checkExisting(folderName, currentParentId, isPublic);
      if (existingId) {
        currentParentId = existingId;
        this._reusedFolderIds.add(currentParentId);
        this._folderMap.set(currentPath, currentParentId);
        continue;
      }

      // 3. 创建新文件夹
      const folderId = await this._createOne(folderName, currentParentId, isPublic);
      currentParentId = folderId;
      this._createdByThisInstance.add(currentParentId);
      this._folderMap.set(currentPath, currentParentId);
    }

    return currentParentId;
  }

  /**
   * 服务端查询是否已存在同名文件夹
   */
  async _checkExisting(name, parentId, isPublic) {
    try {
      const { http } = await import('libs');
      const result = await http.get(FOLDER_API_BASE, {
        params: { parent_id: parentId, name, is_public: isPublic }
      });
      return result.results?.[0]?.id || null;
    } catch (e) {
      return null;
    }
  }

  /**
   * 创建单个文件夹
   */
  async _createOne(name, parentId, isPublic) {
    const { http } = await import('libs');
    const params = {
      name,
      parent_id: parentId,
      is_public: isPublic,
    };

    const tenantId = isPublic ? null : sessionStorage.getItem('tenant_id');
    if (tenantId) {
      params.tenant_id = tenantId;
    }

    const result = await http.post(FOLDER_API_BASE, params);
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

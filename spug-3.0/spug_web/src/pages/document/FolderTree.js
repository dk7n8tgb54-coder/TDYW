/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * FolderTree - 左侧文件夹树
 *
 * 【M6 重构 + 2026-06-07 key 冲突修复】
 * - 改用 antd loadData API 按需加载子节点
 * - 单根节点（公共文档），子节点按需加载
 */
import React from 'react';
import { observer } from 'mobx-react';
import { reaction } from 'mobx';
import { Tree, Tooltip } from 'antd';
import { http } from 'libs';
import navigationStore from './stores/navigation';
import { parseRawId, generateKey } from './utils/keyUtils';
import styles from './FolderTree.module.less';
import { createLogger } from '@/pages/document/utils/logger';
import { FolderIcon } from './components/FileTypeIcon';
import { PARTY_BUILDING_DOCUMENTS_CODE } from 'libs/systemFolderContext';
import { computeLeafState, resolveCreatorName, resolveRefreshNodeKey, applyChildrenToTree } from './utils/folderTreeNode';
import { naturalCompare } from './utils/naturalSort';
const log = createLogger("FolderTree");

// 纯函数从 utils/folderTreeNode 导入，便于单测（避免装饰器语法在 jest 中报错）
export { computeLeafState, resolveCreatorName };

@observer
class FolderTree extends React.Component {
  _pendingLoadTokens = new Set();
  treeRef = React.createRef();

  state = {
    data: [],
    loading: false,
    expandedKeys: [],
    selectedKeys: []
  };
  componentDidMount() {
    this._isMounted = true;
    // 【M6 重构】改用 antd loadData API，按需加载子节点
    this.fetchFolders();
    // 【2026-08-30 左右同步】右侧导航（列表点击/面包屑/返回/URL 恢复）改变 currentFolderId 时，
    // 左侧树跟随选中并展开到对应位置（revealFolder）
    this._navReaction = reaction(
      () => navigationStore.currentFolderId,
      (folderId) => this.revealFolder(folderId),
    );
  }
  componentWillUnmount() {
    this._isMounted = false;
    if (this._navReaction) {
      this._navReaction();
      this._navReaction = null;
    }
    this._pendingLoadTokens.forEach(token => {
      token.active = false;
    });
    this._pendingLoadTokens.clear();
  }
  componentDidUpdate(prevProps) {
    // 党建工作锁定模式：根目录 ID 变化（初始化后）时刷新
    if (prevProps.lockedRoot !== this.props.lockedRoot
        || prevProps.rootFolderId !== this.props.rootFolderId) {
      this.fetchFolders();
      // 【2026-08-30 左右同步】initSystemFolder 触发 reaction 时 rootFolderId prop 尚未更新，
      // 定位会因 key 解析不到而放弃；这里在根 ID 就绪后补一次定位
      if (this.props.lockedRoot && this.props.rootFolderId
          && navigationStore.currentFolderId === this.props.rootFolderId) {
        this.revealFolder(this.props.rootFolderId);
      }
    }
  }

  /**
   * 【2026-06-07 M6 重构】根据 parentId 加载子文件夹
   * parentId === null -> 加载根目录的子文件夹
   * parentId !== null -> 加载指定文件夹的子文件夹
   */
  fetchChildFolders = async (parentId) => {
    if (!this._isMounted) return [];
    const { lockedRoot } = this.props;
    const url = '/api/document/folder/';
    const params = {
      id: parentId,
      is_public: true
    };
    if (lockedRoot) {
      params.system_folder = PARTY_BUILDING_DOCUMENTS_CODE;
    }
    const res = await http.get(url, { params, skipErrorNotification: true });
    // 后端返回 { folders: [...], files: [...], pagination: ... } 或 [...]（all=true 时）
    const folders = Array.isArray(res) ? res : (res.folders || []);
    return folders;
  };

  _runTreeLoad = (loader) => {
    if (!this._isMounted) {
      return new Promise(() => undefined);
    }

    const token = { active: true };
    this._pendingLoadTokens.add(token);

    return new Promise((resolve, reject) => {
      Promise.resolve()
        .then(loader)
        .then(() => {
          this._pendingLoadTokens.delete(token);
          if (this._isMounted && token.active) {
            resolve();
          }
        })
        .catch((error) => {
          this._pendingLoadTokens.delete(token);
          if (this._isMounted && token.active) {
            reject(error);
          }
        });
    });
  };

  fetchFolders = async () => {
    try {
      this.setState({
        loading: true
      });
      const { lockedRoot } = this.props;
      // 党建工作锁定模式：构建单根节点树
      if (lockedRoot) {
        const treeData = this.buildSingleRootTree();
        if (this._isMounted) {
          this.setState({ data: treeData, expandedKeys: ['system-root'] }, () => {
            // 仅预加载根节点的一级子目录；下级目录由用户单击展开三角触发 onLoadData 按需加载
            this._loadSystemRootChildren();
          });
        }
        return;
      }
      // 构建单根节点树（仅公共根节点）
      const treeData = this.buildDualRootTree();

      if (this._isMounted) {
        this.setState({
          data: treeData,
          expandedKeys: ['public-root']
        }, () => {
          // 预加载公共根节点的一级 children
          this._loadActiveRootChildren();
        });
      }
    } catch (error) {
      log.error("fetchFolders error:", error);
      log.error("error stack:", error?.stack || 'No stack trace');
      // 不抛出错误，避免Uncaught (in promise)错误
      // 显示空的树形结构
      if (this._isMounted) {
        this.setState({
          data: this.props.lockedRoot ? this.buildSingleRootTree() : this.buildDualRootTree()
        });
      }
    } finally {
      if (this._isMounted) {
        this.setState({
          loading: false
        });
      }
    }
  };

  /**
   * 党建工作锁定模式：构建单根节点树
   * 根节点代表党建工作根目录（真实文件夹），children 预加载
   */
  buildSingleRootTree = () => {
    const { rootFolderId, rootFolderName } = this.props;
    const name = rootFolderName || '党建工作';
    return [{
      key: 'system-root',
      rawId: rootFolderId,
      folderName: name,
      title: this.renderNodeWithTooltip(name, { isRoot: true, rootVariant: 'public', open: true }),
      selectable: true,
      children: undefined,
      isLeaf: false
    }];
  };

  /**
   * 党建工作锁定模式：预加载根目录的一级子文件夹
   */
  _loadSystemRootChildren = async () => {
    try {
      const { rootFolderId } = this.props;
      if (!rootFolderId) return;
      const folders = await this.fetchChildFolders(rootFolderId);
      this._setRootChildren('system-root', folders);
    } catch (error) {
      log.warn(`[FolderTree] 预加载系统根节点失败:`, error);
    }
  };

  /**
   * 预加载公共根节点的一级子文件夹
   */
  _loadActiveRootChildren = async () => {
    try {
      const rootKey = 'public-root';
      // 根节点的 parentId 是 null
      const folders = await this.fetchChildFolders(null);
      this._setRootChildren(rootKey, folders);
    } catch (error) {
      log.warn(`[FolderTree] 预加载根节点失败:`, error);
    }
  };

  /**
   * 把预加载的 children 写入对应的根节点
   * 通过更新 treeData 中对应 key 的 children
   * 返回构建后的 children（供 refreshNodeChildren 判断是否需要展开）
   */
  _setRootChildren = (rootKey, folders) => {
    if (!this._isMounted) return [];
    const builtChildren = this._buildFolderChildren(folders);
    // 根节点加载完成后根据实际一级子目录更新叶子状态（folders.length>0 -> 可展开）
    this.setState((prevState) => ({
      data: applyChildrenToTree(prevState.data, rootKey, builtChildren),
    }));
    return builtChildren;
  };

  refresh = () => {
    this.fetchFolders();
  };

  /**
   * 【2026-08-30 新建文件夹即时上树】定向刷新指定父目录在树中的子节点。
   * 与 refresh()（整树重建、展开状态重置）不同：
   * - 仅重建受影响分支（applyChildrenToTree），保留其它分支与已展开节点
   * - folderId 为空或等于党建锁定根 ID 时刷新树根节点（system-root / public-root）
   * - 节点未在树中渲染（分支从未展开）时无需处理：后续展开时 onLoadData 会拉取最新数据
   * - 刷新后若该节点有子目录且未展开则自动展开，保证新建的子文件夹立即可见
   * @param {number|null} folderId - 发生结构变化的父目录 ID（null 表示树根）
   */
  refreshNodeChildren = async (folderId) => {
    if (!this._isMounted) return;
    const { lockedRoot, rootFolderId } = this.props;
    const key = resolveRefreshNodeKey(folderId, { lockedRoot, rootFolderId });
    if (!key) return;
    const isRootKey = key === 'system-root' || key === 'public-root';
    const node = isRootKey
      ? this.state.data.find(n => n.key === key)
      : this._findNodeInData(this.state.data, key);
    if (!node) return;
    try {
      // 根节点取数与预加载逻辑保持一致：党建锁定根是真实文件夹（按 rootFolderId），普通根按 null
      const parentId = key === 'system-root' ? rootFolderId : (key === 'public-root' ? null : folderId);
      const folders = await this.fetchChildFolders(parentId);
      if (!this._isMounted) return;
      const builtChildren = isRootKey
        ? this._setRootChildren(key, folders)
        : this._setNodeChildren(key, folders);
      if (builtChildren.length > 0) {
        this.setState((prevState) => (
          prevState.expandedKeys.includes(key)
            ? null
            : { expandedKeys: [...prevState.expandedKeys, key] }
        ));
      }
    } catch (error) {
      log.warn('[FolderTree] 刷新节点子目录失败:', error);
    }
  };

  /**
   * 【2026-08-30 左右同步】让左侧树跟随右侧导航：选中并展开到当前文件夹。
   * 由 currentFolderId 的 reaction 触发（右侧列表点击/面包屑/返回/URL 恢复）。
   * - 目标为树根：直接选中
   * - 目标节点已在树中：展开祖先链 + 选中（无额外请求）
   * - 目标节点不在树中（分支从未展开）：沿 navigationStore.path 自上而下逐级
   *   拉取父级 children 物化缺失节点，再展开 + 选中（对齐 VSCode 的 reveal 行为）
   * - 物化失败（父级 children 中无该目录）时安全放弃，不影响右侧导航
   * 说明：点击树中当前节点（toggle 收起）不会改变 currentFolderId，不触发本方法，
   * 收起行为不受影响；点击其它节点触发的 reveal 与 handleSelect 的展开结果一致，
   * React 批处理下无闪烁。
   */
  revealFolder = async (folderId) => {
    if (!this._isMounted) return;
    const { lockedRoot, rootFolderId } = this.props;
    const targetKey = resolveRefreshNodeKey(folderId, { lockedRoot, rootFolderId });
    if (!targetKey) return;
    const token = (this._revealToken = (this._revealToken || 0) + 1);

    const isRootTarget = targetKey === 'public-root' || targetKey === 'system-root';
    const toExpand = [];
    if (!isRootTarget) {
      // 党建锁定根对应树上的 system-root 节点，从链中剔除，避免按 folder-<rootId> 物化
      const path = (navigationStore.path || []).filter(p => p && p.id != null
        && !(lockedRoot && p.id === rootFolderId));
      let parentNodeId = lockedRoot ? rootFolderId : null;
      let parentKey = lockedRoot ? 'system-root' : 'public-root';
      const confirmed = new Set();
      for (const entry of path) {
        const entryKey = generateKey(entry.id, 'folder');
        if (!confirmed.has(entryKey) && !this._findNodeInData(this.state.data, entryKey)) {
          let folders;
          try {
            folders = await this.fetchChildFolders(parentNodeId);
          } catch (error) {
            log.warn('[FolderTree] 定位目录时加载父级 children 失败:', error);
            return;
          }
          if (!this._isMounted || token !== this._revealToken) return;
          const built = this._buildFolderChildren(folders);
          if (!built.some(n => n && n.key === entryKey)) {
            // 父级 children 中没有该目录（数据不一致或被过滤）：安全放弃
            log.warn('[FolderTree] 定位目录未出现在父级 children 中，放弃展开:', entry.name);
            return;
          }
          confirmed.add(entryKey);
          this.setState((prevState) => ({
            data: applyChildrenToTree(prevState.data, parentKey, built),
          }));
        }
        toExpand.push(entryKey);
        parentNodeId = entry.id;
        parentKey = entryKey;
      }
    }

    if (!this._isMounted || token !== this._revealToken) return;
    const ensureKeys = isRootTarget ? [targetKey] : toExpand;
    this.setState((prevState) => ({
      expandedKeys: Array.from(new Set([...(prevState.expandedKeys || []), ...ensureKeys])),
      selectedKeys: [targetKey],
    }), () => this._scrollToNode(targetKey));
  };

  /** 展开渲染完成后把选中节点滚入可视区（antd Tree.scrollTo，4.20+；不可用时静默跳过） */
  _scrollToNode = (key) => {
    const tree = this.treeRef && this.treeRef.current;
    if (tree && typeof tree.scrollTo === 'function') {
      try {
        tree.scrollTo({ key, align: 'auto' });
      } catch (error) {
        // 滚动失败不影响功能
      }
    }
  };

  // 构建单根节点树形结构（仅公共根节点）
  buildDualRootTree = () => {
    const publicRoot = {
      key: 'public-root',
      title: this.renderNodeWithTooltip('公共文档', { isRoot: true, rootVariant: 'public', open: true }),
      selectable: true,
      children: undefined,
      isLeaf: false
    };
    return [publicRoot];
  };

  /**
   * 【M6 重构】antd loadData 回调 - 用户展开节点时按需加载
   * @param {Object} treeNode - antd TreeNode
   * @returns {Promise<void>}
   */
  onLoadData = (treeNode) => this._runTreeLoad(async () => {
    const key = treeNode.key;

    // 党建工作系统根节点：展开时加载其一级子文件夹
    if (key === 'system-root') {
      const nodeData = this.state.data.find(n => n.key === key);
      if (nodeData && nodeData.children && nodeData.children.length > 0) {
        return;
      }
      const { rootFolderId } = this.props;
      const folders = await this.fetchChildFolders(rootFolderId);
      this._setRootChildren(key, folders);
      return;
    }

    // 公共根节点：展开时加载一级子文件夹
    if (key === 'public-root') {
      // 已经预加载过了
      const nodeData = this.state.data.find(n => n.key === key);
      if (nodeData && nodeData.children && nodeData.children.length > 0) {
        return;
      }
      const folders = await this.fetchChildFolders(null);
      this._setRootChildren(key, folders);
      return;
    }

    // 普通文件夹节点：展开时加载它的子文件夹
    const folderId = parseRawId(key);
    if (!folderId) return;

    const folders = await this.fetchChildFolders(folderId);
    this._setNodeChildren(key, folders);
  });

  /**
   * 更新普通节点的 children
   * 返回构建后的 children（供 refreshNodeChildren 判断是否需要展开）
   */
  _setNodeChildren = (key, folders) => {
    if (!this._isMounted) return [];
    const builtChildren = this._buildFolderChildren(folders);
    // 加载完成后同步叶子状态：返回空数组 -> 叶子；返回子目录 -> 可展开
    this.setState((prevState) => ({
      data: applyChildrenToTree(prevState.data, key, builtChildren),
    }));
    return builtChildren;
  };

  /**
   * 统一节点标题渲染（根节点与普通节点共用同一骨架）。
   * 根节点仅追加颜色/字重修饰类，图标尺寸与水平间距全树一致（16px）。
   * 【2026-07-17 布局优化】创建人不再常驻显示，仅保留图标 + 名称；
   *   完整名称与创建人通过 Tooltip 悬停展示（见 renderNodeWithTooltip）。
   */
  renderNodeTitle = (name, { isRoot = false, rootVariant = null, open = false } = {}) => {
    const rootClass = isRoot
      ? (rootVariant === 'public' ? styles.publicRoot : '')
      : '';
    const className = rootClass ? `${styles.nodeContent} ${rootClass}` : styles.nodeContent;
    return (
      <div className={className}>
        <span className={styles.folderIcon}><FolderIcon size={16} open={open} /></span>
        <span className={styles.nodeLabel}>{name}</span>
      </div>
    );
  };

  /**
   * 用 Tooltip 包裹节点标题，悬停展示完整文件夹名称 + 创建人。
   * 创建人为空时 Tooltip 只显示名称。根节点（无 creator）同样适用。
   */
  renderNodeWithTooltip = (name, opts = {}) => {
    const { creator = null } = opts;
    const titleNode = creator
      ? (
        <div>
          <div>{name}</div>
          <div style={{ fontSize: 11, color: '#bfbfbf', marginTop: 2 }}>创建人：{creator}</div>
        </div>
      )
      : <span>{name}</span>;
    return (
      <Tooltip title={titleNode} placement="right" mouseEnterDelay={0.3} overlayClassName={styles.nodeTooltip}>
        {this.renderNodeTitle(name, opts)}
      </Tooltip>
    );
  };

  /**
   * 【M6 重构】把后端返回的 folder 列表转为 antd tree node 格式。
   * 根据 has_children 字段映射 isLeaf / children：
   *   - has_children === true  -> 可展开（isLeaf:false, children:undefined）
   *   - has_children === false -> 叶子（isLeaf:true, children:[]，不显示三角但保留槽位）
   *   - has_children 缺失（旧后端）-> 保守允许展开
   */
  _buildFolderChildren = (folders) => {
    if (!Array.isArray(folders)) {
      log.warn("folders is not an array:", folders);
      return [];
    }
    // 累积到 folderMap，用于 buildFolderPath
    if (!this.folderMap) this.folderMap = new Map();

    // 同级节点按名称自然排序（后端 order_by 为字典序，"文件夹11"会排在"文件夹2"前）
    const sorted = [...folders].sort((a, b) => naturalCompare(a.name, b.name));

    return sorted.map(f => {
      if (!f || !f.id) return null;
      // 累积 folderMap
      this.folderMap.set(f.id, {
        id: f.id,
        name: f.name || '未命名',
        parent_id: f.parent_id,
        created_at: f.created_at,
        created_by: f.created_by,
        created_by_id: f.created_by_id
      });
      // 检查循环引用
      const hasLoopRef = f.parent_id === f.id;
      if (hasLoopRef) {
        log.warn("\u68C0\u6D4B\u5230\u5FAA\u73AF\u5F15\u7528: \u6587\u4EF6\u5939", f.name, 'parent_id 指向自身');
      }
      const { isLeaf, children } = computeLeafState(f.has_children);
      const creatorName = resolveCreatorName(f.created_by);
      return {
        key: generateKey(f.id, 'folder'),
        rawId: f.id,
        folderName: f.name,
        title: this.renderNodeWithTooltip(f.name, { creator: creatorName }),
        isLeaf,
        children
      };
    }).filter(Boolean);
  };

  handleSelect = (_, {
    node
  }) => {
    // 【2026-08-30 左右同步】受控选中：点击节点立即高亮（单选）
    this.setState({ selectedKeys: [node.key] });
    // 【2026-08-30 左右同步】先做 toggle 展开/收起，再导航：
    // 导航会触发 revealFolder 把目标节点展开；若先导航后 toggle，
    // toggle 会把 reveal 刚展开的节点又收起。
    this._expandNodeOnSelect(node.key);
    // 党建工作系统根节点选择
    if (node.key === 'system-root') {
      const { rootFolderId, rootFolderName } = this.props;
      if (rootFolderId) {
        navigationStore.selectFolder(rootFolderId, rootFolderName || '党建工作');
      }
      return;
    }
    // 处理公共根节点选择
    if (node.key === 'public-root') {
      navigationStore.selectRootFolder();
    } else {
      // 解析文件夹ID（使用工具函数）
      const folderId = parseRawId(node.key);
      if (folderId) {
        const folderName = node.folderName || '未命名文件夹';
        // 【2026-07-17 完整路径修复】通过 parent_id 向上构造完整祖先链，
        //   使用 setPath 保存完整路径，不再用 selectFolder 把路径重置为单节点。
        //   树按需加载流程下，点击节点及其所有祖先均已在 folderMap 中累积，
        //   可安全构造；祖先缺失时 buildFolderPath 安全停止并记录日志，
        //   此时退回 selectFolder 单节点兜底，保证可用性。
        const fullPath = this.buildFolderPath(folderId);
        if (fullPath.length > 0) {
          navigationStore.setPath(fullPath, folderId);
        } else {
          navigationStore.selectFolder(folderId, folderName);
        }
      }
    }
  };

  /**
   * 单击文件夹节点时切换展开/收起（toggle 行为）
   * - 已展开则收起（移除该 key）
   * - 未展开且非叶子节点则展开
   * - 叶子节点（isLeaf=true）不操作
   * - children=undefined 时 antd Tree 检测到 expandedKeys 变化会自动触发 onLoadData 按需加载
   * - 【2026-08-30 根节点固定展开】一级根目录（公共文档/党建工作）不允许收起
   */
  _expandNodeOnSelect = (key) => {
    if (!this._isMounted || !key) return;
    const rootKey = this.props.lockedRoot ? 'system-root' : 'public-root';
    this.setState((prevState) => {
      if (prevState.expandedKeys.includes(key)) {
        // 根节点固定展开：点击根只导航，不收起
        if (key === rootKey) {
          return null;
        }
        // 已展开 -> 收起
        return { expandedKeys: prevState.expandedKeys.filter(k => k !== key) };
      }
      const node = this._findNodeInData(prevState.data, key);
      if (node && node.isLeaf === true) {
        return null; // 叶子节点，无子文件夹
      }
      return { expandedKeys: [...prevState.expandedKeys, key] };
    });
  };

  /**
   * 在 state.data 中递归查找节点
   */
  _findNodeInData = (nodes, key) => {
    if (!Array.isArray(nodes)) return null;
    for (const n of nodes) {
      if (n.key === key) return n;
      if (Array.isArray(n.children)) {
        const found = this._findNodeInData(n.children, key);
        if (found) return found;
      }
    }
    return null;
  };


  /**
   * 构建文件夹路径（从根目录到指定文件夹的完整祖先链）
   * 【2026-07-17 完整路径修复】
   * - 普通模式：向上追溯至 parent_id === null（根目录）停止
   * - 党建工作锁定模式：向上追溯至锁定根目录（rootFolderId）停止，
   *   锁定根作为路径起点，不越界到公共资料库
   * - 循环引用保护（visited set）
   * - 最大深度保护（MAX_PATH_DEPTH）
   * - 祖先数据异常缺失时安全停止并记录日志，不构造错误路径
   * @param {number} folderId - 目标文件夹ID
   * @returns {Array} 路径数组 [{id, name}, ...] 从根到目标
   */
  buildFolderPath = folderId => {
    const path = [];
    const visited = new Set();
    let currentId = folderId;
    const MAX_PATH_DEPTH = 100;
    const { lockedRoot, rootFolderId, rootFolderName } = this.props;

    while (currentId !== null && currentId !== undefined && path.length < MAX_PATH_DEPTH) {
      // 循环引用保护
      if (visited.has(currentId)) {
        log.warn('检测到循环引用，停止构建路径。已构建层级:', path.length, '循环节点:', currentId);
        break;
      }
      visited.add(currentId);

      // 党建工作锁定模式：到达锁定根目录，加入路径并停止（不越界到公共库）
      if (lockedRoot && currentId === rootFolderId) {
        path.unshift({ id: currentId, name: rootFolderName || '党建工作' });
        break;
      }

      // 从 folderMap 中查找文件夹
      const folder = this.folderMap ? this.folderMap.get(currentId) : null;
      if (folder) {
        path.unshift({
          id: currentId,
          name: folder.name || '未命名文件夹'
        });
        currentId = folder.parent_id;
      } else {
        // 祖先数据异常缺失：安全停止并记录日志，不构造错误路径
        log.warn('祖先文件夹数据缺失，无法构建完整路径。已构建层级:', path.length, '缺失节点:', currentId);
        break;
      }
    }
    return path;
  };
  /**
   * 展开/收起回调（受控 expandedKeys）。
   * 【2026-08-30 根节点固定展开】一级根目录（公共文档/党建工作）始终保持展开：
   * 用户点击根节点的收起箭头时，antd 传入的 expandedKeys 不含根 key，
   * 此处强制保留；子目录的收起不受影响。
   */
  handleExpand = (expandedKeys) => {
    if (!this._isMounted) return;
    const rootKey = this.props.lockedRoot ? 'system-root' : 'public-root';
    const nextKeys = Array.isArray(expandedKeys) && !expandedKeys.includes(rootKey)
      ? [...expandedKeys, rootKey]
      : expandedKeys;
    this.setState({ expandedKeys: nextKeys });
  };

  render() {
    const {
      lockedRoot
    } = this.props;
    const defaultExpandedKey = lockedRoot
      ? 'system-root'
      : 'public-root';
    return <div className={styles.container}>
        <div className={styles.header}>
          <span className={styles.title}>文件夹</span>
        </div>
        <div className={styles.treeWrapper}>
          <Tree
            showIcon={false}
            treeData={this.state.data}
            onSelect={this.handleSelect}
            selectedKeys={this.state.selectedKeys}
            loading={this.state.loading}
            defaultExpandedKeys={[defaultExpandedKey]}
            expandedKeys={this.state.expandedKeys}
            onExpand={this.handleExpand}
            // 【M6 关键】loadData API + children undefined -> 按需加载
            loadData={this.onLoadData}
            motion={false}
            ref={this.treeRef}
          />
        </div>
      </div>;
  }
}
export default FolderTree;

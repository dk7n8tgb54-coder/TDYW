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
import { Tree, Tooltip } from 'antd';
import { http } from 'libs';
import navigationStore from './stores/navigation';
import { parseRawId, generateKey } from './utils/keyUtils';
import styles from './FolderTree.module.less';
import { createLogger } from '@/pages/document/utils/logger';
import { FolderIcon } from './components/FileTypeIcon';
import { PARTY_BUILDING_DOCUMENTS_CODE } from 'libs/systemFolderContext';
import { computeLeafState, resolveCreatorName } from './utils/folderTreeNode';
const log = createLogger("FolderTree");

// 纯函数从 utils/folderTreeNode 导入，便于单测（避免装饰器语法在 jest 中报错）
export { computeLeafState, resolveCreatorName };

@observer
class FolderTree extends React.Component {
  _pendingLoadTokens = new Set();

  state = {
    data: [],
    loading: false,
    expandedKeys: []
  };
  componentDidMount() {
    this._isMounted = true;
    // 【M6 重构】改用 antd loadData API，按需加载子节点
    this.fetchFolders();
  }
  componentWillUnmount() {
    this._isMounted = false;
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
   */
  _setRootChildren = (rootKey, folders) => {
    if (!this._isMounted) return;
    const builtChildren = this._buildFolderChildren(folders);
    // 根节点加载完成后根据实际一级子目录更新叶子状态（folders.length>0 -> 可展开）
    const isLeaf = builtChildren.length === 0;
    this.setState((prevState) => {
      const newData = prevState.data.map(node => {
        if (node.key === rootKey) {
          return { ...node, children: builtChildren, isLeaf };
        }
        return node;
      });
      return { data: newData };
    });
  };

  refresh = () => {
    this.fetchFolders();
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
   */
  _setNodeChildren = (key, folders) => {
    if (!this._isMounted) return;
    const builtChildren = this._buildFolderChildren(folders);
    // 加载完成后同步叶子状态：返回空数组 -> 叶子；返回子目录 -> 可展开
    const isLeaf = builtChildren.length === 0;
    this.setState((prevState) => {
      const updateNode = (node) => {
        if (node.key === key) {
          return { ...node, children: builtChildren, isLeaf };
        }
        if (node.children && Array.isArray(node.children)) {
          return { ...node, children: node.children.map(updateNode) };
        }
        return node;
      };
      return { data: prevState.data.map(updateNode) };
    });
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

    return folders.map(f => {
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
    // 党建工作系统根节点选择
    if (node.key === 'system-root') {
      const { rootFolderId, rootFolderName } = this.props;
      if (rootFolderId) {
        navigationStore.selectFolder(rootFolderId, rootFolderName || '党建工作');
      }
      this._expandNodeOnSelect(node.key);
      return;
    }
    // 处理公共根节点选择
    if (node.key === 'public-root') {
      navigationStore.selectRootFolder();
      this._expandNodeOnSelect(node.key);
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
        this._expandNodeOnSelect(node.key);
      }
    }
  };

  /**
   * 单击文件夹节点时切换展开/收起（toggle 行为）
   * - 已展开则收起（移除该 key）
   * - 未展开且非叶子节点则展开
   * - 叶子节点（isLeaf=true）不操作
   * - children=undefined 时 antd Tree 检测到 expandedKeys 变化会自动触发 onLoadData 按需加载
   */
  _expandNodeOnSelect = (key) => {
    if (!this._isMounted || !key) return;
    this.setState((prevState) => {
      if (prevState.expandedKeys.includes(key)) {
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
            loading={this.state.loading}
            defaultExpandedKeys={[defaultExpandedKey]}
            expandedKeys={this.state.expandedKeys}
            onExpand={expandedKeys => {
              if (this._isMounted) {
                this.setState({ expandedKeys });
              }
            }}
            // 【M6 关键】loadData API + children undefined -> 按需加载
            loadData={this.onLoadData}
            motion={false}
          />
        </div>
      </div>;
  }
}
export default FolderTree;

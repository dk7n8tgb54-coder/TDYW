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
 * - 双根节点（公共/私人）互斥填充 children，避免 key 冲突：
 *   修复前：两个根节点都预加载相同 folders → antd 报 "Same 'key' exist"
 *   修复后：只预加载当前 isPublic 对应根节点，另一个根节点 children=[]（空）
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Tree } from 'antd';
import { http } from 'libs';
import navigationStore from './stores/navigation';
import { parseRawId, generateKey } from './utils/keyUtils';
import styles from './FolderTree.module.less';
import { createLogger } from '@/pages/document/utils/logger';
import { FolderIcon } from './components/FileTypeIcon';
const log = createLogger("FolderTree");
@observer
class FolderTree extends React.Component {
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
  }
  componentDidUpdate(prevProps) {
    // 监听isPublic变化，刷新文件夹树
    if (prevProps.isPublic !== this.props.isPublic) {
      this.fetchFolders();
    }
  }

  /**
   * 【2026-06-07 M6 重构】根据 parentId 加载子文件夹
   * parentId === null → 加载根目录的子文件夹（双根节点：公共/私人）
   * parentId !== null → 加载指定文件夹的子文件夹
   */
  fetchChildFolders = async (parentId) => {
    const { isPublic } = this.props;
    const url = '/api/document/folder/';
    const params = {
      id: parentId,
      is_public: isPublic
    };
    const res = await http.get(url, { params });
    // 后端返回 { folders: [...], files: [...], pagination: ... } 或 [...]（all=true 时）
    const folders = Array.isArray(res) ? res : (res.folders || []);
    return folders;
  };

  fetchFolders = async () => {
    try {
      this.setState({
        loading: true
      });
      const { isPublic } = this.props;
      // 【M6 重构】用 antd loadData + children undefined 实现按需加载
      // 根节点本身不需要查后端（"我的文件"/"公共共享库"是 UI 概念）
      // 当前 isPublic 对应的根节点 children 设为 undefined（触发 loadData），
      // 另一个根节点 children 设为 []（避免被 loadData 误触发 + 不显示展开箭头）
      const treeData = this.buildDualRootTree(isPublic);

      if (this._isMounted) {
        this.setState({
          data: treeData
        }, () => {
          // setState 回调里预加载当前激活根节点的一级 children
          // 关键：只预加载一个根节点（另一个保持空），避免 antd key 冲突
          this._loadActiveRootChildren(isPublic);
        });
      }
    } catch (error) {
      log.error("fetchFolders error:", error);
      log.error("error stack:", error?.stack || 'No stack trace');
      // 不抛出错误，避免Uncaught (in promise)错误
      // 显示空的树形结构
      if (this._isMounted) {
        this.setState({
          data: this.buildDualRootTree(this.props.isPublic)
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
   * 【M6 重构】异步预加载"当前激活"根节点的一级子文件夹
   * 注意：每次只预加载当前 isPublic 对应的那个根节点（另一个根节点保持空）
   * - 避免两个根节点 children 列表重复导致 antd key 冲突
   * - 避免无谓的请求（用户可能永远不会切换到另一个根节点）
   */
  _loadActiveRootChildren = async (isPublic) => {
    try {
      const rootKey = isPublic ? 'public-root' : 'private-root';
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
    this.setState((prevState) => {
      const newData = prevState.data.map(node => {
        if (node.key === rootKey) {
          return { ...node, children: this._buildFolderChildren(folders) };
        }
        return node;
      });
      return { data: newData };
    });
  };

  refresh = () => {
    this.fetchFolders();
  };

  // 构建双根节点树形结构
  // 【M6 重构】两个根节点同时存在（key 不重复：public-root / private-root）
  // 互斥地设置 children：
  //   - 当前 isPublic 对应的根节点：children: undefined → 触发 antd loadData 按需加载
  //   - 另一个根节点：children: [] → 表示"已加载但无数据"，避免被 loadData 误触发
  // 关键：绝不能两个根节点都填充相同 folders（key 冲突）
  buildDualRootTree = (isPublic) => {
    const privateRoot = {
      key: 'private-root',
      title: <div className={styles.privateRoot}>
          <span className={styles.rootEmoji}><FolderIcon size={18} /></span>
          <span className={styles.rootLabel}>我的文件</span>
        </div>,
      selectable: true,
      // isPublic === true 时，private-root 暂不预加载
      children: isPublic ? [] : undefined,
      isLeaf: false
    };
    const publicRoot = {
      key: 'public-root',
      title: <div className={styles.publicRoot}>
          <span className={styles.rootEmoji}><FolderIcon size={18} open /></span>
          <span className={styles.rootLabel}>公共共享库</span>
        </div>,
      selectable: true,
      // isPublic === false 时，public-root 暂不预加载
      children: isPublic ? undefined : [],
      isLeaf: false
    };
    return [publicRoot, privateRoot];
  };

  /**
   * 【M6 重构】antd loadData 回调 - 用户展开节点时按需加载
   * @param {Object} treeNode - antd TreeNode
   * @returns {Promise<void>}
   */
  onLoadData = async (treeNode) => {
    const key = treeNode.key;

    // 双根节点：展开时加载一级子文件夹
    // 注意：loadData 触发时 this.props.isPublic 可能还是旧的（点击根节点 → selectRootFolder
    // → componentDidUpdate 异步链路），所以要根据 root key 反推 isPublic
    if (key === 'private-root' || key === 'public-root') {
      // 已经预加载过了
      const nodeData = this.state.data.find(n => n.key === key);
      if (nodeData && nodeData.children && nodeData.children.length > 0) {
        return;
      }
      // 根据 root key 决定 isPublic（绕过 props 可能的时序问题）
      const rootIsPublic = key === 'public-root';
      const folders = await this.fetchChildFoldersForSpace(rootIsPublic);
      this._setRootChildren(key, folders);
      return;
    }

    // 普通文件夹节点：展开时加载它的子文件夹
    const folderId = parseRawId(key);
    if (!folderId) return;

    const folders = await this.fetchChildFolders(folderId);
    this._setNodeChildren(key, folders);
  };

  /**
   * 【M6 重构】根据空间类型加载根目录子文件夹（绕过 props.isPublic）
   * 用于 onLoadData 处理根节点展开，避免 props 时序问题
   */
  fetchChildFoldersForSpace = async (isPublic) => {
    const url = '/api/document/folder/';
    const params = {
      id: null,
      is_public: isPublic
    };
    const res = await http.get(url, { params });
    const folders = Array.isArray(res) ? res : (res.folders || []);
    return folders;
  };

  /**
   * 更新普通节点的 children
   */
  _setNodeChildren = (key, folders) => {
    if (!this._isMounted) return;
    this.setState((prevState) => {
      const updateNode = (node) => {
        if (node.key === key) {
          return { ...node, children: this._buildFolderChildren(folders) };
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
   * 【M6 重构】把后端返回的 folder 列表转为 antd tree node 格式
   * 每个节点: { key, rawId, folderName, title, isLeaf: true (待 onLoadData 更新) }
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
      return {
        key: generateKey(f.id, 'folder'),
        rawId: f.id,
        folderName: f.name,
        title: <div className={styles.folderNode}>
            <span className={styles.folderEmoji}><FolderIcon size={16} /></span>
            <span className={styles.folderName}>{f.name}</span>
            {this.props.isPublic && f.created_by && (f.created_by.nickname || f.created_by.username) && <span className={styles.folderCreator}>
                {f.created_by.nickname || f.created_by.username}
              </span>}
          </div>,
        // 【M6 关键】isLeaf: false 让 antd 知道该节点可展开（即使还没有 children）
        isLeaf: false,
        children: undefined
      };
    }).filter(Boolean);
  };

  handleSelect = (_, {
    node
  }) => {
    // 处理根节点选择
    if (node.key === 'private-root' || node.key === 'public-root') {
      navigationStore.selectRootFolder(node.key === 'public-root');
    } else {
      // 解析文件夹ID（使用工具函数）
      const folderId = parseRawId(node.key);
      if (folderId) {
        // 获取文件夹名称
        const folderName = node.folderName || '未命名文件夹';

        // 【修复】使用 selectFolder 方法，确保 selectedFolderId 被正确设置
        navigationStore.selectFolder(folderId, folderName);
      }
    }
  };

  /**
   * 构建文件夹路径（从根目录到指定文件夹的完整路径）
   * @param {number} folderId - 目标文件夹ID
   * @returns {Array} 路径数组 [{id, name}, ...]
   */
  buildFolderPath = folderId => {
    const path = [];
    let currentId = folderId;
    let maxIterations = 100; // 防止死循环

    // 使用 folderMap 而不是树结构，因为 folderMap 包含所有文件夹的完整信息
    while (currentId !== null && maxIterations > 0) {
      maxIterations--;

      // 从 folderMap 中查找文件夹
      const folder = this.folderMap ? this.folderMap.get(currentId) : null;
      if (folder) {
        path.unshift({
          id: currentId,
          name: folder.name || '未命名文件夹'
        });
        currentId = folder.parent_id;
      } else {
        // 找不到文件夹，停止查找
        log.warn("Folder not found in folderMap:", currentId);
        break;
      }
    }
    return path;
  };
  render() {
    const {
      isPublic
    } = this.props;
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
            defaultExpandedKeys={[isPublic ? 'public-root' : 'private-root']}
            expandedKeys={this.state.expandedKeys}
            onExpand={expandedKeys => this.setState({ expandedKeys })}
            // 【M6 关键】loadData API + children undefined → 按需加载
            loadData={this.onLoadData}
            motion={false}
          />
        </div>
      </div>;
  }
}
export default FolderTree;
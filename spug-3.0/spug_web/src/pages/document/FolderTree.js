/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Tree } from 'antd';
import { http } from 'libs';
import navigationStore from './stores/navigation';
import { parseRawId, generateKey } from './utils/keyUtils';

import styles from './FolderTree.module.less';

@observer
class FolderTree extends React.Component {
  state = {
    data: [],
    loading: false,
    expandedKeys: []
  };

  componentDidMount() {
    this._isMounted = true;
    // 【P0-2修复】初始只加载一级子文件夹，不加载全部，实现懒加载
    this.fetchFolders(true);
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

  fetchFolders = async (lazy = false) => {
    try {
      this.setState({ loading: true });
      const { isPublic } = this.props;
      const url = '/api/document/folder/';
      // 【P0-2修复】懒加载模式：初始只获取一级子文件夹，不获取全部
      const params = lazy
        ? { id: null, is_public: isPublic }
        : { id: null, all: true, is_public: isPublic };
      const res = await http.get(url, { params });
      const folders = Array.isArray(res) ? res : [];

      // 构建双根节点树形结构
      const treeData = this.buildDualRootTree(folders, isPublic);

      // 检查组件是否已卸载
      if (this._isMounted) {
        this.setState({ data: treeData });
      }
    } catch (error) {
      console.error('[FolderTree] fetchFolders error:', error);
      console.error('[FolderTree] error stack:', error?.stack || 'No stack trace');
      // 不抛出错误，避免Uncaught (in promise)错误
      // 显示空的树形结构
      if (this._isMounted) {
        this.setState({ data: this.buildDualRootTree([], this.props.isPublic) });
      }
    } finally {
      if (this._isMounted) {
        this.setState({ loading: false });
      }
    }
  };

  refresh = () => {
    this.fetchFolders();
  };

  // 构建双根节点树形结构
  buildDualRootTree = (folders, isPublic) => {
    const privateRoot = {
      key: 'private-root',
      title: (
        <div className={styles.privateRoot}>
          <span className={styles.rootEmoji} role="img" aria-label="文件夹">📁</span>
          <span className={styles.rootLabel}>我的文件</span>
        </div>
      ),
      selectable: true,
      children: isPublic ? [] : this.buildTreeData(null, folders)
    };

    const publicRoot = {
      key: 'public-root',
      title: (
        <div className={styles.publicRoot}>
          <span className={styles.rootEmoji} role="img" aria-label="打开的文件夹">📂</span>
          <span className={styles.rootLabel}>公共共享库</span>
        </div>
      ),
      selectable: true,
      children: isPublic ? this.buildTreeData(null, folders) : []
    };

    return [publicRoot, privateRoot];
  };

  /**
   * 构建树形数据（优化版本，处理边界情况）
   * @param {number|null} parentId - 父文件夹ID
   * @param {Array} folders - 所有文件夹扁平列表
   * @returns {Array} 树形结构节点数组
   */
  buildTreeData = (parentId, folders) => {
    // 边界检查：确保 folders 是数组
    if (!Array.isArray(folders)) {
      console.warn('[FolderTree] folders is not an array:', folders);
      return [];
    }

    // 1. 构建文件夹映射，方便快速查找父节点
    const folderMap = new Map();
    folders.forEach(f => {
      // 跳过无效数据（无ID或null）
      if (!f || !f.id) return;

      folderMap.set(f.id, {
        id: f.id,
        name: f.name || '未命名',
        parent_id: f.parent_id,
        created_at: f.created_at,
        created_by: f.created_by,
        created_by_id: f.created_by_id
      });
    });

    // 保存到实例属性，供 buildFolderPath 使用
    this.folderMap = folderMap;

    // 2. 查找当前层级的孩子
    const children = [];
    for (const [, folder] of folderMap) {
      const isChild = parentId === null ? !folder.parent_id : folder.parent_id === parentId;
      if (isChild) {
        children.push(folder);
      }
    }

    // 3. 递归构建树
    const result = children.map(f => {
      const childFolders = this.buildTreeData(f.id, folders);

      // 检查循环引用（parent_id 指向自身）
      const hasLoopRef = f.parent_id === f.id;
      if (hasLoopRef) {
        console.warn('[FolderTree] 检测到循环引用: 文件夹', f.name, 'parent_id 指向自身');
      }

      return {
        key: generateKey(f.id, 'folder'),
        rawId: f.id,
        folderName: f.name,
        title: (
          <div className={styles.folderNode}>
            <span className={styles.folderEmoji} role="img" aria-label="文件夹">📁</span>
            <span className={styles.folderName}>{f.name}</span>
            {this.props.isPublic && f.created_by && (f.created_by.nickname || f.created_by.username) && (
              <span className={styles.folderCreator}>
                {f.created_by.nickname || f.created_by.username}
              </span>
            )}
          </div>
        ),
        // 有子文件夹才设置 children，避免空数组导致渲染问题
        children: childFolders.length > 0 ? childFolders : undefined
      };
    });

    return result;
  };

  handleSelect = (_, { node }) => {
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
  buildFolderPath = (folderId) => {
    const path = [];
    let currentId = folderId;
    let maxIterations = 100; // 防止死循环

    // 使用 folderMap 而不是树结构，因为 folderMap 包含所有文件夹的完整信息
    while (currentId !== null && maxIterations > 0) {
      maxIterations--;

      // 从 folderMap 中查找文件夹
      const folder = this.folderMap ? this.folderMap.get(currentId) : null;
      if (folder) {
        path.unshift({ id: currentId, name: folder.name || '未命名文件夹' });
        currentId = folder.parent_id;
      } else {
        // 找不到文件夹，停止查找
        console.warn('[FolderTree] Folder not found in folderMap:', currentId);
        break;
      }
    }

    return path;
  };

  render() {
    const { isPublic } = this.props;

    return (
      <div className={styles.container}>
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
            onExpand={(expandedKeys) => this.setState({ expandedKeys })}
            motion={false}
          />
        </div>
      </div>
    );
  }
}

export default FolderTree;


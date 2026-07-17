/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Tree, Modal, message } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, FolderOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import store from './store';
import styles from './index.module.less';

@observer
class CategoryTree extends React.Component {
  componentDidMount() {
    store.fetchCategories();
  }

  handleSelect = (selectedKeys) => {
    if (selectedKeys.length === 0) return;
    const key = selectedKeys[0];
    if (key === 'all') {
      store.f_category_id = undefined;
    } else {
      store.f_category_id = parseInt(key, 10);
    }
    store.pageNum = 1;
    store.fetchRecords();
  };

  handleAddRoot = () => {
    store.showCategoryForm({});
  };

  handleAddChild = (node) => {
    store.showCategoryForm({ parent_id: node.id, parent_name: node.name });
  };

  handleEdit = (node) => {
    store.showCategoryForm(node);
  };

  handleDelete = (node) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除分类【${node.name}】吗？`,
      onOk: () => {
        return http.delete(`/api/regulation/categories/${node.id}/`)
          .then(() => {
            message.success('删除成功');
            store.fetchCategories();
          });
      },
    });
  };

  buildTreeData = (categories) => {
    const canManageCategory = hasPermission('document.regulation.category_manage');
    return categories.map(cat => {
      const title = (
        <span className={styles.treeNodeTitle}>
          <span className={styles.treeNodeMain}>
            <FolderOutlined className={styles.treeNodeIcon} />
            <span className={styles.treeNodeName}>{cat.name}</span>
          </span>
          {canManageCategory && (
            <span className={styles.treeActions}>
              <PlusOutlined
                onClick={(e) => { e.stopPropagation(); this.handleAddChild(cat); }}
              />
              <EditOutlined
                onClick={(e) => { e.stopPropagation(); this.handleEdit(cat); }}
              />
              <DeleteOutlined
                onClick={(e) => { e.stopPropagation(); this.handleDelete(cat); }}
              />
            </span>
          )}
        </span>
      );
      return {
        key: String(cat.id),
        title,
        data: cat,
        isLeaf: cat.is_leaf,
        children: cat.children && cat.children.length > 0 ? this.buildTreeData(cat.children) : undefined,
      };
    });
  };

  render() {
    const canManageCategory = hasPermission('document.regulation.category_manage');
    return (
      <React.Fragment>
        <div className={styles.sidebarHeader}>
          <span>规章管理分类</span>
          {canManageCategory && (
            <PlusOutlined
              style={{ cursor: 'pointer', color: '#1890ff' }}
              onClick={this.handleAddRoot}
              title="新建根分类"
            />
          )}
        </div>
        <div className={styles.sidebarBody}>
          <div
            className={`${styles.allNode} ${!store.f_category_id ? styles.allNodeActive : ''}`}
            onClick={() => {
              store.f_category_id = undefined;
              store.pageNum = 1;
              store.fetchRecords();
            }}
          >
            <FolderOutlined style={{ marginRight: 6 }} />
            全部规章
          </div>
          {store.categories.length > 0 && (
            <Tree
              defaultExpandAll
              selectedKeys={store.f_category_id ? [String(store.f_category_id)] : []}
              onSelect={this.handleSelect}
              treeData={this.buildTreeData(store.categories)}
            />
          )}
        </div>
      </React.Fragment>
    );
  }
}

export default CategoryTree;

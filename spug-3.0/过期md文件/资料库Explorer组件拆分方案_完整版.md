# 资料库 Explorer 组件拆分方案（完整可执行版）

## ⚠️ 关键问题检查

### 原方案存在的问题

| 问题 | 风险 | 解决方案 |
|------|------|----------|
| 未说明组件通信方式 | 拆分后数据流混乱 | 明确定义 Props 接口 |
| 未处理样式继承 | 样式丢失 | 保留原样式文件或 CSS-in-JS |
| 未说明 Hook 依赖 | 无法调用 | 详细列出每个 Hook 的参数 |
| 未处理事件冒泡 | 右键菜单等失效 | 明确事件处理方式 |
| 未处理 ref 转发 | 详情面板无法操作 | 使用 forwardRef 或回调 |

---

## 最终目录结构

```
src/pages/document/
├── Explorer/
│   ├── index.js                 # 主容器 (~250行)
│   ├── index.module.less        # 主容器样式
│   ├── views/
│   │   ├── FileTable.js         # 列表视图 (~350行)
│   │   ├── FileGrid.js          # 网格视图 (~300行)
│   │   └── index.module.less    # 视图公共样式
│   ├── components/
│   │   ├── DetailPanel.js       # 详情面板 (~250行)
│   │   ├── ContextMenu.js       # 右键菜单 (~150行)
│   │   ├── FolderTreeSelector.js # 文件夹选择 (~200行)
│   │   └── index.module.less    # 组件样式
│   ├── hooks/
│   │   ├── useFileOperations.js # 文件操作 (~500行)
│   │   ├── useSelection.js      # 选中管理 (~100行)
│   │   └── useExplorerState.js  # 状态管理 (~200行)
│   └── utils.js                 # 工具函数 (~150行)
├── stores/                      # 保持现有
└── index.js                     # 模块入口
```

---

## 1. 完整 Props 接口定义

### 公共 Props 类型定义
```javascript
// types.js - 公共类型定义
import PropTypes from 'prop-types';

// 【优化】提取公共视图 Props，避免重复定义
export const baseViewPropTypes = {
  // 数据
  data: PropTypes.array.isRequired,
  loading: PropTypes.bool,
  
  // 选择
  selectedRowKeys: PropTypes.array,
  onSelectChange: PropTypes.func,              // (selectedKeys) => void
  
  // 事件
  onItemClick: PropTypes.func,                 // (item) => void
  onItemDoubleClick: PropTypes.func,           // (item) => void
  onContextMenu: PropTypes.func,               // (e, item) => void
  
  // 其他
  isPublic: PropTypes.bool,
  currentUserId: PropTypes.number,
};

export const baseViewDefaultProps = {
  loading: false,
  selectedRowKeys: [],
  isPublic: false,
};
```

### FileTable Props
```javascript
import { baseViewPropTypes, baseViewDefaultProps } from './types';

FileTable.propTypes = {
  ...baseViewPropTypes,
  // 分页 (Table 内置)
  pagination: PropTypes.shape({
    current: PropTypes.number,
    pageSize: PropTypes.number,
    total: PropTypes.number,
    onChange: PropTypes.func,
  }),
  
  // 排序
  sortOrder: PropTypes.shape({
    columnKey: PropTypes.string,
    order: PropTypes.oneOf(['ascend', 'descend']),
  }),
  onSort: PropTypes.func,                      // (columnKey, order) => void
  
  // 行操作 (别名映射，与 baseViewPropTypes 兼容)
  onRowClick: PropTypes.func,                  // (record) => void
  onRowDoubleClick: PropTypes.func,            // (record) => void
};

FileTable.defaultProps = {
  ...baseViewDefaultProps,
  pagination: { current: 1, pageSize: 20, total: 0 },
};
```

### FileGrid Props
```javascript
import { baseViewPropTypes, baseViewDefaultProps } from './types';

FileGrid.propTypes = {
  ...baseViewPropTypes,
  // 分页
  currentPage: PropTypes.number,
  pageSize: PropTypes.number,
  total: PropTypes.number,
  onPageChange: PropTypes.func,                // (page, pageSize) => void
};

FileGrid.defaultProps = {
  ...baseViewDefaultProps,
  currentPage: 1,
  pageSize: 20,
  total: 0,
};
```

### DetailPanel Props
```javascript
DetailPanel.propTypes = {
  // 当前选中项
  selectedItem: PropTypes.object,              // null 表示未选中
  
  // 文件夹内容（如果是文件夹）
  folderContents: PropTypes.array,
  loading: PropTypes.bool,
  
  // 回调
  onClose: PropTypes.func,
  onItemClick: PropTypes.func,                 // 点击面板内项目
}
```

### useFileOperations Hook
```javascript
// 参数
const useFileOperations = ({
  isPublic,           // 当前是否公共空间
  currentFolderId,    // 当前文件夹ID
  refresh,            // 刷新列表的回调
  onFolderChange,     // 文件夹变化的回调
  message,            // antd message 实例
}) => {
  // 返回值
  return {
    handleCopy,       // (items, targetFolderId) => Promise
    handleMove,       // (items, targetFolderId) => Promise
    handleDelete,     // (items) => Promise
    handleRename,     // (item, newName) => Promise
    handleCreateFolder, // (name) => Promise
    handleDownload,   // (item) => Promise
  }
}
```

---

## 2. 数据流设计（细化版）

```
┌─────────────────────────────────────────────────────────────────┐
│                    Explorer/index.js                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  State: items, loading, selectedKeys, pagination        │   │
│  │  Methods: fetchItems, handleSelect, handlePageChange    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌─────────────────┐
│  FileTable    │    │   FileGrid    │    │  DetailPanel    │
│  (列表视图)    │    │  (网格视图)    │    │   (详情面板)     │
└───────────────┘    └───────────────┘    └─────────────────┘
        │                     │                     │
        │    ┌────────────────┘                     │
        │    │                                      │
        ▼    ▼                                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    useFileOperations                          │
│         (复制/移动/删除/重命名/创建文件夹/下载)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 完整迁移步骤（可执行）

### Step 0: 准备工作
```bash
# 1. 备份原文件
cp src/pages/document/Explorer.js src/pages/document/Explorer.js.bak

# 2. 创建目录结构
mkdir -p src/pages/document/Explorer/{views,components,hooks}
touch src/pages/document/Explorer/index.js
touch src/pages/document/Explorer/utils.js
touch src/pages/document/Explorer/index.module.less
```

### Step 1: 提取工具函数 (utils.js)
```javascript
// utils.js - 纯函数，无任何依赖

export const formatFileSize = (size) => {
  if (size === null || size === undefined) return '-';
  if (size < 1024) return size + ' B';
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB';
  if (size < 1024 * 1024 * 1024) return (size / (1024 * 1024)).toFixed(1) + ' MB';
  return (size / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
};

export const formatDate = (date) => {
  if (!date) return '-';
  const d = new Date(date);
  return d.toLocaleString('zh-CN');
};

export const getFileIcon = (fileName, fileType) => {
  // 根据文件类型返回图标
  const iconMap = {
    folder: '📁',
    image: '🖼️',
    video: '🎬',
    audio: '🎵',
    document: '📄',
    archive: '📦',
    code: '💻',
  };
  return iconMap[fileType] || '📄';
};

export const generateKey = (item) => {
  return item.isFolder ? `folder_${item.id}` : `file_${item.id}`;
};

// 其他工具函数...
```

### Step 2: 提取 Hooks

#### hooks/useExplorerState.js
```javascript
import { useState, useCallback, useRef, useEffect } from 'react';
import http from 'libs/http';

export const useExplorerState = (isPublic, folderId) => {
  const [state, setState] = useState({
    items: [],
    filteredItems: [],
    loading: false,
    selectedRowKeys: [],
    sortOrder: { columnKey: null, order: null },
  });

  // 【修复】使用 ref 保存分页信息，避免 fetchItems 依赖 state 导致的循环
  const paginationRef = useRef({ currentPage: 1, pageSize: 20, total: 0 });

  const fetchItems = useCallback(async (resetSelected = false) => {
    const { currentPage, pageSize } = paginationRef.current;
    
    setState(prev => ({ ...prev, loading: true }));
    try {
      const res = await http.get('/api/document/items/', {
        params: {
          folder_id: folderId,
          is_public: isPublic,
          page: currentPage,
          page_size: pageSize,
        }
      });
      
      const items = [...res.folders, ...res.files];
      const totalItems = (res.pagination?.total_folders || 0) + 
                        (res.pagination?.total_files || 0);
      
      paginationRef.current.total = totalItems;
      
      setState(prev => ({
        ...prev,
        items,
        filteredItems: items,
        loading: false,
        selectedRowKeys: resetSelected ? [] : prev.selectedRowKeys,
      }));
    } catch (error) {
      setState(prev => ({ ...prev, loading: false }));
      throw error;
    }
  // 【修复】移除 pagination 依赖，只依赖 isPublic 和 folderId
  }, [isPublic, folderId]);

  // 【修复】当 isPublic 或 folderId 变化时，重置分页并重新加载
  useEffect(() => {
    paginationRef.current.currentPage = 1;
    fetchItems(true);
  }, [isPublic, folderId, fetchItems]);

  const setSelectedRowKeys = useCallback((keys) => {
    setState(prev => ({ ...prev, selectedRowKeys: keys }));
  }, []);

  const setPage = useCallback((page, pageSize) => {
    paginationRef.current.currentPage = page;
    if (pageSize) paginationRef.current.pageSize = pageSize;
  }, []);

  return {
    ...state,
    currentPage: paginationRef.current.currentPage,
    pageSize: paginationRef.current.pageSize,
    total: paginationRef.current.total,
    fetchItems,
    setSelectedRowKeys,
    setPage,
  };
};
```

#### hooks/useSelection.js
```javascript
import { useState, useCallback } from 'react';
import { message } from 'antd';  // 【修复】补充 message 导入

export const useSelection = (maxSelect = 100) => {
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);

  const handleSelect = useCallback((key, selected) => {
    setSelectedRowKeys(prev => {
      if (selected) {
        if (prev.length >= maxSelect) {
          message.warning(`最多选择 ${maxSelect} 项`);
          return prev;
        }
        return [...prev, key];
      }
      return prev.filter(k => k !== key);
    });
  }, [maxSelect]);

  const handleSelectAll = useCallback((data, selected) => {
    if (selected) {
      const allKeys = data.map(item => item.key).slice(0, maxSelect);
      setSelectedRowKeys(allKeys);
    } else {
      setSelectedRowKeys([]);
    }
  }, [maxSelect]);

  const clearSelection = useCallback(() => {
    setSelectedRowKeys([]);
  }, []);

  return {
    selectedRowKeys,
    setSelectedRowKeys,
    handleSelect,
    handleSelectAll,
    clearSelection,
  };
};
```

#### hooks/useFileOperations.js
```javascript
import { useCallback } from 'react';
import http from 'libs/http';
import { message } from 'antd';

export const useFileOperations = ({ 
  isPublic, 
  folderId, 
  refresh, 
  onFolderChange 
}) => {
  
  const handleDelete = useCallback(async (items) => {
    if (!items?.length) return;
    
    try {
      const deletePromises = items.map(item => {
        const url = item.isFolder 
          ? '/api/document/folder/'
          : '/api/document/file/';
        return http.delete(url, {
          params: { id: item.id, is_public: isPublic }
        });
      });
      
      await Promise.all(deletePromises);
      message.success(`已删除 ${items.length} 项`);
      refresh(true);
      
      // 如果有文件夹被删除，刷新左侧树
      const hasFolder = items.some(i => i.isFolder);
      if (hasFolder) onFolderChange?.();
    } catch (error) {
      message.error(error.message || '删除失败');
    }
  }, [isPublic, refresh, onFolderChange]);

  const handleCopy = useCallback(async (items, targetFolderId) => {
    if (!items?.length) return;
    
    try {
      const promises = items.map(item => 
        http.post('/api/document/copy/', {
          id: item.id,
          folder_id: targetFolderId,
          is_public: isPublic,
          is_folder: item.isFolder,
        })
      );
      
      await Promise.all(promises);
      message.success(`已复制 ${items.length} 项`);
      refresh(true);
    } catch (error) {
      message.error(error.message || '复制失败');
    }
  }, [isPublic, refresh]);

  const handleMove = useCallback(async (items, targetFolderId) => {
    if (!items?.length) return;
    
    try {
      const promises = items.map(item => 
        http.post('/api/document/move/', {
          id: item.id,
          target_folder_id: targetFolderId,
          is_public: isPublic,
          is_folder: item.isFolder,
        })
      );
      
      await Promise.all(promises);
      message.success(`已移动 ${items.length} 项`);
      refresh(true);
      onFolderChange?.(); // 刷新左侧树
    } catch (error) {
      message.error(error.message || '移动失败');
    }
  }, [isPublic, refresh, onFolderChange]);

  const handleRename = useCallback(async (item, newName) => {
    if (!item || !newName?.trim()) return;
    
    try {
      const url = item.isFolder 
        ? '/api/document/folder/rename/'
        : '/api/document/file/rename/';
      
      await http.post(url, {
        id: item.id,
        name: newName.trim(),
        is_public: isPublic,
      });
      
      message.success('重命名成功');
      refresh(true);
    } catch (error) {
      message.error(error.message || '重命名失败');
    }
  }, [isPublic, refresh]);

  const handleCreateFolder = useCallback(async (name) => {
    if (!name?.trim()) return;
    
    try {
      await http.post('/api/document/folder/', {
        name: name.trim(),
        parent_id: folderId,
        is_public: isPublic,
      });
      
      message.success('创建成功');
      refresh(true);
      onFolderChange?.(); // 刷新左侧树
    } catch (error) {
      message.error(error.message || '创建失败');
    }
  }, [isPublic, folderId, refresh, onFolderChange]);

  return {
    handleDelete,
    handleCopy,
    handleMove,
    handleRename,
    handleCreateFolder,
  };
};
```

### Step 3: 拆分视图组件

#### views/FileTable.js
```javascript
import React from 'react';
import { Table } from 'antd';
import { formatFileSize, formatDate, getFileIcon } from '../utils';
import styles from './index.module.less';

const FileTable = ({
  data,
  loading,
  pagination,
  selectedRowKeys,
  onSelectChange,
  sortOrder,
  onSort,
  onRowClick,
  onRowDoubleClick,
  onContextMenu,
  isPublic,
}) => {
  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      sorter: true,  // 【修复】启用排序
      sortOrder: sortOrder?.columnKey === 'name' ? sortOrder.order : null,
      render: (text, record) => (
        <span>
          {record.isFolder ? '📁' : getFileIcon(text, record.file_type)}
          <span className={styles.fileName}>{text}</span>
        </span>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      sorter: true,  // 【修复】启用排序
      sortOrder: sortOrder?.columnKey === 'size' ? sortOrder.order : null,
      render: (size, record) => record.isFolder ? '-' : formatFileSize(size),
    },
    {
      title: '修改时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      sorter: true,  // 【修复】启用排序
      sortOrder: sortOrder?.columnKey === 'updated_at' ? sortOrder.order : null,
      render: formatDate,
    },
  ];

  return (
    <Table
      columns={columns}
      dataSource={data}
      loading={loading}
      rowKey="key"
      pagination={pagination}
      rowSelection={{
        selectedRowKeys,
        onChange: onSelectChange,
      }}
      onRow={(record) => ({
        onClick: () => onRowClick?.(record),
        onDoubleClick: () => onRowDoubleClick?.(record),
        onContextMenu: (e) => {
          e.preventDefault();
          onContextMenu?.(e, record);
        },
      })}
    />
  );
};

export default FileTable;
```

#### views/FileGrid.js
```javascript
import React from 'react';
import { Pagination, Empty } from 'antd';
import { formatFileSize, getFileIcon } from '../utils';
import styles from './index.module.less';

const FileGrid = ({
  data,
  loading,
  currentPage,
  pageSize,
  total,
  onPageChange,
  selectedRowKeys,
  onSelectChange,
  onItemClick,
  onItemDoubleClick,
  onContextMenu,
  isPublic,
  currentUserId,
}) => {
  if (!data?.length) {
    return <Empty description="暂无文件" />;
  }

  // 【修复】处理点击选中
  const handleItemClick = (item, e) => {
    if (e?.ctrlKey || e?.metaKey) {
      // Ctrl/Cmd 点击：切换选中
      const newKeys = selectedRowKeys.includes(item.key)
        ? selectedRowKeys.filter(k => k !== item.key)
        : [...selectedRowKeys, item.key];
      onSelectChange?.(newKeys);
    } else if (e?.shiftKey) {
      // Shift 点击：范围选择（简化版）
      onSelectChange?.([item.key]);
    } else {
      // 普通点击：单选
      onSelectChange?.([item.key]);
    }
    onItemClick?.(item);
  };

  return (
    <div className={styles.gridContainer}>
      {/* 顶部工具栏 */}
      <div className={styles.gridToolbar}>
        <span>共 {total} 项</span>
      </div>

      {/* 网格内容 */}
      <div className={styles.gridContent}>
        {data.map(item => (
          <div
            key={item.key}
            className={`${styles.gridItem} ${
              selectedRowKeys.includes(item.key) ? styles.selected : ''
            }`}
            onClick={(e) => handleItemClick(item, e)}
            onDoubleClick={() => onItemDoubleClick?.(item)}
            onContextMenu={(e) => {
              e.preventDefault();
              onContextMenu?.(e, item);
            }}
          >
            <div className={styles.itemIcon}>
              {item.isFolder 
                ? '📁' 
                : getFileIcon(item.display_name || item.name, item.file_type)
              }
            </div>
            <div className={styles.itemName} title={item.display_name || item.name}>
              {item.display_name || item.name}
            </div>
            {!item.isFolder && (
              <div className={styles.itemSize}>
                {formatFileSize(item.size)}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 分页 */}
      <div className={styles.gridPagination}>
        <Pagination
          current={currentPage}
          pageSize={pageSize}
          total={total}
          showSizeChanger
          showQuickJumper
          pageSizeOptions={['10', '20', '50', '100']}
          showTotal={(total, range) => `${range[0]}-${range[1]} / 共 ${total} 项`}
          onChange={onPageChange}
        />
      </div>
    </div>
  );
};

export default FileGrid;
```

### Step 4: 重构主容器 (Explorer/index.js)

```javascript
import React, { useEffect, useCallback } from 'react';
import { observer } from 'mobx-react';
import { Radio, Tooltip } from 'antd';
import { UnorderedListOutlined, AppstoreOutlined } from '@ant-design/icons';

// Hooks
import { useExplorerState } from './hooks/useExplorerState';
import { useSelection } from './hooks/useSelection';
import { useFileOperations } from './hooks/useFileOperations';

// Views
import FileTable from './views/FileTable';
import FileGrid from './views/FileGrid';

// Components
import DetailPanel from './components/DetailPanel';
import ContextMenu from './components/ContextMenu';

// Utils
import { generateKey } from './utils';
import styles from './index.module.less';

const Explorer = observer(({ 
  isPublic, 
  folderId, 
  onFolderChange,
  uploadCoreStore 
}) => {
  // 状态管理
  const {
    items,
    filteredItems,
    loading,
    currentPage,
    pageSize,
    total,
    sortOrder,
    fetchItems,
    setPage,
  } = useExplorerState(isPublic, folderId);

  // 选中管理
  const {
    selectedRowKeys,
    setSelectedRowKeys,
    clearSelection,
  } = useSelection();

  // 文件操作
  const {
    handleDelete,
    handleCopy,
    handleMove,
    handleRename,
    handleCreateFolder,
  } = useFileOperations({
    isPublic,
    folderId,
    refresh: fetchItems,
    onFolderChange,
  });

  // 视图模式
  const [viewMode, setViewMode] = React.useState('list'); // 'list' | 'grid'

  // 【修复】fetchItems 内部已处理 isPublic/folderId 变化的重新加载
  // 这里只需要初始加载一次
  useEffect(() => {
    fetchItems(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);  // 仅在组件挂载时执行

  // 处理选择变化
  const handleSelectChange = useCallback((keys) => {
    setSelectedRowKeys(keys);
  }, [setSelectedRowKeys]);

  // 处理分页变化
  const handlePageChange = useCallback((page, newPageSize) => {
    setPage(page, newPageSize);
    fetchItems(false);
  }, [setPage, fetchItems]);

  // 处理行点击
  const handleRowClick = useCallback((record) => {
    // 实现点击逻辑...
  }, []);

  // 处理行双击
  const handleRowDoubleClick = useCallback((record) => {
    if (record.isFolder) {
      // 进入文件夹
    } else {
      // 预览文件
    }
  }, []);

  // 处理右键菜单
  const handleContextMenu = useCallback((e, record) => {
    // 显示右键菜单
  }, []);

  // 准备数据
  const dataSource = filteredItems.map(item => ({
    ...item,
    key: generateKey(item),
  }));

  return (
    <div className={styles.explorer}>
      {/* 工具栏 */}
      <div className={styles.toolbar}>
        <Radio.Group 
          value={viewMode} 
          onChange={(e) => setViewMode(e.target.value)}
        >
          <Radio.Button value="list">
            <UnorderedListOutlined /> 列表
          </Radio.Button>
          <Radio.Button value="grid">
            <AppstoreOutlined /> 大图
          </Radio.Button>
        </Radio.Group>
      </div>

      {/* 主内容区 */}
      <div className={styles.mainContent}>
        <div className={styles.fileList}>
          {viewMode === 'list' ? (
            <FileTable
              data={dataSource}
              loading={loading}
              pagination={{
                current: currentPage,
                pageSize,
                total,
                onChange: handlePageChange,
              }}
              selectedRowKeys={selectedRowKeys}
              onSelectChange={handleSelectChange}
              sortOrder={sortOrder}
              onRowClick={handleRowClick}
              onRowDoubleClick={handleRowDoubleClick}
              onContextMenu={handleContextMenu}
              isPublic={isPublic}
            />
          ) : (
            <FileGrid
              data={dataSource}
              loading={loading}
              currentPage={currentPage}
              pageSize={pageSize}
              total={total}
              onPageChange={handlePageChange}
              selectedRowKeys={selectedRowKeys}
              onSelectChange={handleSelectChange}
              onItemClick={handleRowClick}
              onItemDoubleClick={handleRowDoubleClick}
              onContextMenu={handleContextMenu}
              isPublic={isPublic}
            />
          )}
        </div>

        {/* 右侧详情面板 */}
        <DetailPanel
          selectedItem={dataSource.find(i => i.key === selectedRowKeys[0])}
          onClose={clearSelection}
        />
      </div>
    </div>
  );
});

export default Explorer;
```

---

## 4. 关键注意事项

### 4.1 样式迁移
```less
// index.module.less
.explorer {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.toolbar {
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}

.mainContent {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.fileList {
  flex: 1;
  overflow: auto;
}
```

### 4.2 MobX 集成
```javascript
// 保持 observer 包裹
// 确保 uploadCoreStore 能触发刷新
useEffect(() => {
  const disposer = autorun(() => {
    const trigger = uploadCoreStore.refreshTrigger;
    if (trigger > 0) {
      fetchItems(true);
    }
  });
  return () => disposer();
}, []);
```

### 4.3 错误处理优化
```javascript
// hooks/useExplorerState.js 添加 onError 回调
export const useExplorerState = (isPublic, folderId, onError) => {
  const fetchItems = useCallback(async (resetSelected = false) => {
    // ... 省略代码
    } catch (error) {
      setState(prev => ({ ...prev, loading: false }));
      onError?.(error);  // 【优化】通知上层处理错误
      throw error;
    }
  }, [isPublic, folderId, onError]);
};

// Explorer/index.js 中使用
const { fetchItems } = useExplorerState(isPublic, folderId, (error) => {
  message.error(`加载失败: ${error.message}`);
});
```

### 4.4 样式类名对照表

| 原类名 (Explorer.js) | 新类名 (模块.less) | 说明 |
|---------------------|-------------------|------|
| `.explorer-container` | `.explorer` | 主容器 |
| `.toolbar` | `.toolbar` | 工具栏 |
| `.file-list-wrapper` | `.mainContent` | 内容区 |
| `.file-table` | `.fileList` | 列表区 |
| `.detail-panel` | `.detailPanel` | 详情面板 |
| `.grid-item` | `.gridItem` | 网格项 |
| `.grid-item.selected` | `.gridItem.selected` | 选中态 |

### 4.5 兼容旧代码
- 保持 Props 接口与原组件一致
- 事件处理函数命名不变
- 样式类名尽量保持一致

---

## 5. 验证清单

### 5.1 基础功能验证
- [ ] 列表视图显示正常
- [ ] 大图视图显示正常
- [ ] 视图切换正常（列表 ↔ 大图）
- [ ] 列表视图分页正常
- [ ] 大图视图分页正常
- [ ] 分页大小切换正常（10/20/50/100）

### 5.2 选择功能验证
- [ ] 单选正常
- [ ] 多选正常（Ctrl/Cmd + 点击）
- [ ] 全选/反选正常
- [ ] 选中数量限制提示正常
- [ ] 切换页面时选中状态保持正常

### 5.3 交互功能验证
- [ ] 单击选中正常
- [ ] 双击打开文件正常
- [ ] 双击进入文件夹正常
- [ ] 右键菜单正常
- [ ] 右键菜单功能正常（复制/移动/删除/重命名）

### 5.4 文件操作验证
- [ ] 复制文件正常
- [ ] 复制文件夹正常
- [ ] 移动文件正常
- [ ] 移动文件夹正常
- [ ] 删除文件正常
- [ ] 删除文件夹正常
- [ ] 重命名文件正常
- [ ] 重命名文件夹正常
- [ ] 创建文件夹正常

### 5.5 高级功能验证
- [ ] 详情面板正常显示
- [ ] 公共空间/私有空间切换正常
- [ ] 文件夹进入/返回正常
- [ ] 搜索功能正常
- [ ] 排序功能正常（名称/大小/时间）
- [ ] 上传后自动刷新正常

### 5.6 边界情况验证
- [ ] 空文件夹显示正常
- [ ] 加载状态显示正常
- [ ] 错误提示正常
- [ ] 大量数据（>1000条）分页正常
- [ ] 快速切换视图无错误

---

## 6. 回滚方案

如果拆分后出现问题，立即回滚：

```bash
# 恢复备份
cp src/pages/document/Explorer.js.bak src/pages/document/Explorer.js

# 删除拆分目录
rm -rf src/pages/document/Explorer/
```


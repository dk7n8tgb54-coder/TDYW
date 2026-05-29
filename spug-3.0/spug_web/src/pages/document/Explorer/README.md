# Explorer 组件拆分说明

## 目录结构

```
Explorer/
├── index.js                 # 主容器组件
├── index.module.less        # 主容器样式
├── README.md               # 本文件
├── utils.js                # 工具函数
├── hooks/
│   ├── useExplorerState.js # 状态管理
│   ├── useSelection.js     # 选择状态
│   └── useFileOperations.js # 文件操作
├── views/
│   ├── FileTable.js        # 列表视图
│   ├── FileGrid.js         # 网格视图
│   └── index.module.less   # 视图样式
└── components/
    ├── DetailPanel.js      # 详情面板
    └── index.module.less   # 组件样式
```

## 主要变更

### 1. 工具函数 (utils.js)
从原组件中提取的纯函数：
- `formatFileSize` - 格式化文件大小
- `formatDate` - 格式化日期
- `getFileIcon` - 获取文件图标
- `getFileTypeLabel` - 获取文件类型标签
- `isImage` / `isVideo` - 判断文件类型
- `generateItemKey` - 生成唯一键

### 2. Hooks

#### useExplorerState
管理 Explorer 的核心状态：
- items / filteredItems
- loading
- pagination (currentPage, pageSize, total)
- sortOrder

#### useSelection
管理选中状态：
- selectedRowKeys
- handleSelect / handleSelectAll / clearSelection

#### useFileOperations
管理文件操作：
- handleDelete
- handleCopy
- handleMove
- handleRename
- handleCreateFolder
- handleDownload

### 3. 视图组件

#### FileTable
- Table 组件展示
- 内置分页
- 排序支持
- 行选择

#### FileGrid
- 网格布局展示
- 底部分页
- 支持 Ctrl/Cmd 多选

### 4. 功能组件

#### DetailPanel
- 文件详情展示
- 文件夹内容预览

## 兼容性

新的 Explorer 组件完全兼容原有接口：

```javascript
// 原有调用方式仍然有效
<Explorer
  ref={explorerRef}
  folderId={folderId}
  isPublic={isPublic}
  viewMode={viewMode}
  onFolderChange={handleFolderChange}
/>

// ref 暴露的方法：
explorerRef.current.fetchItems()      // 刷新列表
explorerRef.current.handleSearch()    // 搜索
explorerRef.current.handleAddFolder() // 新建文件夹
explorerRef.current.toggleDetailPanel(callback) // 切换详情面板
```

## 验证清单

- [x] 列表视图显示正常
- [x] 大图视图显示正常
- [x] 分页功能正常
- [x] 单选/多选正常
- [x] 右键菜单正常
- [x] 文件操作（复制/移动/删除/重命名）正常
- [x] 新建文件夹正常
- [x] 详情面板正常
- [x] 搜索功能正常
- [x] 兼容原有 ref 调用方式

## 回滚

如需回滚到旧版本：

```bash
# 恢复备份
cp Explorer.js.bak Explorer.js

# 删除新目录
rm -rf Explorer/
```

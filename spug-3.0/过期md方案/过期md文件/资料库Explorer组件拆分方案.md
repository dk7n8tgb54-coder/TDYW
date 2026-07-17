# 资料库 Explorer 组件拆分方案

## 现状问题
- `Explorer.js` 2300+ 行，职责过多
- 包含列表视图、大图视图、详情面板、右键菜单、所有操作逻辑
- 难以维护，多人协作容易冲突

## 拆分目标
按**职责分离**原则，拆成多个小组件

---

## 拆分结构

```
src/pages/document/
├── Explorer/                          # 原 Explorer.js 拆分到这里
│   ├── index.js                       # 主容器 (200行)
│   ├── views/
│   │   ├── FileTable.js               # 列表视图 (Table)
│   │   └── FileGrid.js                # 大图/网格视图 (Grid)
│   ├── components/
│   │   ├── DetailPanel.js             # 右侧详情面板
│   │   ├── ContextMenu.js             # 右键菜单
│   │   └── FolderTreeSelector.js      # 文件夹选择弹窗
│   ├── hooks/
│   │   ├── useFileOperations.js       # 文件操作逻辑 (复制/移动/删除)
│   │   ├── useSelection.js            # 选中状态管理
│   │   └── usePagination.js           # 分页逻辑
│   └── utils.js                       # 工具函数 (文件图标/大小格式化等)
├── stores/                            # 保持现有结构
└── index.js                           # 文档模块入口
```

---

## 各文件职责

### 1. Explorer/index.js (主容器)
**职责：** 整体布局、状态协调、数据获取
```javascript
// 只保留：
- 整体布局 (左列表 + 右详情)
- 数据获取 fetchItems
- 视图模式切换 (list/grid)
- 状态: items, loading, viewMode, selectedKeys
// 不保留具体渲染逻辑
```

### 2. Explorer/views/FileTable.js
**职责：** 列表视图渲染
```javascript
// 从原 render() 中提取 Table 相关代码
- 表格列定义
- 行选择逻辑
- 排序逻辑
- 分页 (内置)
```

### 3. Explorer/views/FileGrid.js
**职责：** 大图/网格视图渲染
```javascript
// 从原 renderGridView 提取
- 网格布局
- 卡片渲染
- 双击/右键逻辑
- 分页 (底部)
```

### 4. Explorer/components/DetailPanel.js
**职责：** 右侧详情面板
```javascript
// 从原 render() 中提取右侧面板
- 文件详情展示
- 文件夹内容列表
- 展开/收起动画
```

### 5. Explorer/hooks/useFileOperations.js
**职责：** 文件操作业务逻辑
```javascript
// 所有文件操作方法：
- handleCopy/Move/Delete
- handleRename
- handleDownload
- handleCreateFolder
// 这些方法从 Class 方法改为 Hook
```

### 6. Explorer/hooks/useSelection.js
**职责：** 选中状态管理
```javascript
- selectedRowKeys 状态
- 全选/反选逻辑
- 多选限制
```

### 7. Explorer/utils.js
**职责：** 纯工具函数
```javascript
- formatFileSize
- formatDate
- getFileIcon
- getFileTypeLabel
- generateKey
```

---

## 迁移步骤

### 第一步：准备
1. 确保现有功能正常
2. 备份 Explorer.js

### 第二步：提取工具函数
```bash
# 创建 utils.js
# 把 formatFileSize, getFileIcon 等纯函数移过去
# 原文件改为 import { formatFileSize } from './utils'
```

### 第三步：提取 Hooks
```bash
# 创建 hooks/useFileOperations.js
# 把 handleDelete, handleCopy 等方法改成 Hook
# 注意：需要传入必要的依赖 (http, isPublic 等)
```

### 第四步：拆分视图组件
```bash
# 创建 views/FileTable.js 和 views/FileGrid.js
# 从原 render() 和 renderGridView 提取代码
# 通过 props 传递数据和回调
```

### 第五步：重构主容器
```bash
# 简化 Explorer/index.js
# 只保留整体布局和状态管理
# 引入拆分后的子组件
```

### 第六步：测试验证
- 列表视图正常
- 大图视图正常
- 分页正常
- 所有操作正常

---

## 数据流设计

```
Explorer/index.js (状态中心)
    │
    ├─► FileTable ◄── 传递: data, selectedKeys, onSelect
    │
    ├─► FileGrid ◄─── 传递: data, selectedKeys, onSelect
    │
    ├─► DetailPanel ◄── 传递: selectedItem
    │
    └─► useFileOperations ──► 提供: deleteFile, copyFile 等方法
```

---

## 预期效果

| 文件 | 行数 | 职责 |
|------|------|------|
| Explorer/index.js | ~200 | 整体布局、状态管理 |
| FileTable.js | ~300 | 列表视图 |
| FileGrid.js | ~250 | 网格视图 |
| DetailPanel.js | ~200 | 详情面板 |
| useFileOperations.js | ~400 | 操作逻辑 |
| utils.js | ~100 | 工具函数 |

**总计：** 从 2300 行分散到 6 个文件，每个文件职责清晰

---

## 是否需要现在拆分？

**建议：** 先修复大图分页问题，让功能可用。拆分是优化项，可以后续进行。

**拆分风险：**
- 可能引入新的 bug
- 需要充分测试
- 建议单独一个分支进行

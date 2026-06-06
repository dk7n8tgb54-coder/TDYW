# 资料库上传文件夹 Bug 修复方案

## 修复日期
2026-06-06

## 概述
本方案针对资料库上传文件夹功能代码审查中发现的 4 个 Bug 提供修复方法。

---

## Bug #1: `_prepareUploadItem` 中 totalChunks 计算使用错误的 chunk 大小

### 问题描述

**文件**: `spug_web/src/pages/document/stores/upload/core/folderUpload.js`
**行号**: 第 522 行

```javascript
// 当前代码（错误）
totalChunks: file.size > 32 * 1024 * 1024 ? Math.ceil(file.size / (8 * 1024 * 1024)) : 1,
```

**根因**: 实际分片大小 `UPLOAD_CONSTANTS.CHUNK_SIZE` = **32MB**（定义在 `stores/constants/upload.js` 第 179 行），但这里除数硬编码为 **8MB**，导致显示的分片数是实际的 **4倍**。

例如一个 64MB 文件：
- 正确分片数: `Math.ceil(64MB / 32MB)` = **2 chunks**
- 当前显示: `Math.ceil(64MB / 8MB)` = **8 chunks**

### 影响
- 上传队列中初始显示的总分片数错误
- 当 `uploadFileToFolder` 开始上传时会修正 `totalChunks`（通过 `updateUploadItem`），导致用户看到分片数从 8 → 2 的视觉抖动
- 虽然不影响实际上传功能，但影响用户体验和调试时的判断

### 修复方法

**方式一：直接硬编码为正确值（最简单）**

```javascript
// 修复后
totalChunks: file.size > 32 * 1024 * 1024 ? Math.ceil(file.size / (32 * 1024 * 1024)) : 1,
```

**方式二：使用常量（推荐）**

在文件顶部已有 `UPLOAD_CONSTANTS` 的引用路径，需要引入并使用：

```javascript
// 文件顶部添加 import（如果还没有直接引入 CHUNK_SIZE）
import { UPLOAD_CONSTANTS } from '../upload-core-constants';

// 修复后
totalChunks: file.size > UPLOAD_CONSTANTS.CHUNK_SIZE 
    ? Math.ceil(file.size / UPLOAD_CONSTANTS.CHUNK_SIZE) 
    : 1,
```

> **注意**: `folderUpload.js` 当前未直接 import `UPLOAD_CONSTANTS`，需确认 `upload-core-constants.js` 已导出 `UPLOAD_CONSTANTS`（经确认，该文件第 13 行已 `export const UPLOAD_CONSTANTS = ORIGINAL_UPLOAD_CONSTANTS;`）。

**推荐采用方式二**，与其他上传代码保持一致，避免魔法数字。

---

## Bug #2: `_getCachedFolderId` 使用 O(n) 遍历而非 Map.get()

### 问题描述

**文件**: `spug_web/src/pages/document/stores/upload/core/folderUpload.js`
**行号**: 第 319-326 行

```javascript
// 当前代码（O(n)）
_getCachedFolderId(path) {
    const folderMap = this.rootStore.pendingFolderFiles?.folderMap;
    if (!folderMap) return null;
    for (const [cachedPath, id] of folderMap) {
      if (cachedPath === path) return id;
    }
    return null;
}
```

**根因**: `folderMap` 是一个 JavaScript `Map` 对象，支持 O(1) 的 `get(key)` 操作，但此处使用了 `for...of` 遍历，时间复杂度为 O(n)。

### 影响
- 当上传包含大量嵌套文件夹（如 100+ 个子文件夹）时，每个文件夹的每个层级组件都会触发此查找
- 累积性能消耗不可忽略，尤其在文件夹上传流程中会被频繁调用

### 修复方法

直接使用 `Map.get()` 方法：

```javascript
// 修复后（O(1)）
_getCachedFolderId(path) {
    const folderMap = this.rootStore.pendingFolderFiles?.folderMap;
    if (!folderMap) return null;
    return folderMap.get(path) ?? null;
}
```

> **说明**: `Map.get()` 返回 `undefined` 当 key 不存在时，使用 `?? null` 保持返回类型一致。

---

## Bug #3: `folderPath` 参数始终传递 `null`，代码意图不清

### 问题描述

**文件**: `spug_web/src/pages/document/stores/upload/core/folderUpload.js`
**行号**: 第 440-442 行

```javascript
// 当前代码
await this.fileUploadStore.uploadFileToFolder(
    item.file, item.targetId, null, isPublic, item.file._folderUploadId
);
```

`folderPath` 参数（第三个参数）始终为 `null`。

**调用链追踪**:
1. `uploadFileToFolder` 接收 `folderPath` 参数，传给 `buildFolderFileName(folderPath, file.name)`
2. `buildFolderFileName(null, file.name)` 直接返回 `file.name`（不含路径）
3. `fileName` 仅在 `existingUploadId` 为空时用于创建新队列项的名称
4. 当前流程中 `existingUploadId` 始终存在（`_folderUploadId`），所以不会重建队列项

### 影响
- **当前无功能问题**：因为 `existingUploadId` 不为空，`fileName` 未被使用
- **潜在风险**：如果将来有人修改流程导致 `existingUploadId` 为空，文件会以不含路径的短文件名上传，而非 `folder/subfolder/file.txt` 格式
- **可读性问题**：代码意图不清，阅读者难以理解 `null` 的含义

### 修复方法

**方案一：传递实际的文件夹路径（推荐）**

从 `webkitRelativePath` 提取文件夹路径，显式传递：

```javascript
// 修复后
const folderPath = item.file.webkitRelativePath 
    ? item.file.webkitRelativePath.split('/').slice(0, -1).join('/') 
    : '';

await this.fileUploadStore.uploadFileToFolder(
    item.file, item.targetId, folderPath, isPublic, item.file._folderUploadId
);
```

**方案二：如果确认不需要，则从函数签名中移除该参数**

修改 `fileUpload.js` 中 `uploadFileToFolder` 的签名，移除 `folderPath` 参数（需要确认没有其他调用方依赖此参数）。

> **推荐采用方案一**，传递实际的文件夹路径，使代码自文档化。

---

## Bug #4: `_clearUniqueKeys` 清除范围过大

### 问题描述

**文件**: `spug_web/src/pages/document/stores/upload/core/folderUpload.js`
**行号**: 第 77-81 行

```javascript
// 当前代码
_clearUniqueKeys() {
    if (this.queueStore?.uploadingUniqueKeys) {
        this.queueStore.uploadingUniqueKeys.clear();
    }
}
```

**根因**: `uploadingUniqueKeys` 是一个全局的 `Set`（在 `queue.js` 中定义），被所有上传类型共享（普通文件上传、文件夹上传、分片上传等）。当页面触发 `beforeunload` 时，`clear()` 会清空整个 Set。

### 影响
- 如果用户同时有文件夹上传和普通文件上传在进行中，刷新页面会导致**所有**上传任务的去重保护失效
- 恢复后可能产生重复上传

### 修复方法

**方案一：只清除当前实例关联的 key（推荐）**

在实例中维护自己的 key 集合，仅清除自己添加的：

```javascript
// 构造函数中新增
this._myUniqueKeys = new Set();

// 修改 _initUploadState，记录添加的 key
_initUploadState(files, targetFolderId, isPublic, folderUniqueKey) {
    // ... 现有代码 ...
    if (this.queueStore?.uploadingUniqueKeys) {
        this.queueStore.uploadingUniqueKeys.add(folderUniqueKey);
        this._myUniqueKeys.add(folderUniqueKey);  // 【新增】记录归属
    }
    // ... 现有代码 ...
}

// 修改 _prepareUploadItem，记录每个文件的 uniqueKey
async _prepareUploadItem(file, targetFolderId, folderPath, isPublic, index) {
    // ... 现有代码 ...
    this.queueStore.addUniqueKey(file, targetFolderId, isPublic);
    const uniqueKey = this.queueStore.generateUniqueKey(file, targetFolderId, isPublic);
    this._myUniqueKeys.add(uniqueKey);  // 【新增】记录归属
    // ... 现有代码 ...
}

// 修改 _clearUniqueKeys，只清除自己的
_clearUniqueKeys() {
    if (this.queueStore?.uploadingUniqueKeys) {
        for (const key of this._myUniqueKeys) {
            this.queueStore.uploadingUniqueKeys.delete(key);
        }
        this._myUniqueKeys.clear();
    }
}
```

**方案二：移除全局 clear，改为依赖正常流程清理**

完全移除 `_clearUniqueKeys` 方法和 `beforeunload` 监听器，因为：
- 正常的文件夹上传成功/失败后，`_clearFolderKey` 已经清理了 `folderUniqueKey`
- 每个文件上传完成/失败后，各自的流程也已在清理 `uniqueKey`
- `beforeunload` 场景下的清理意义有限（页面即将销毁）

```javascript
// 移除构造函数中的以下代码:
// this._cleanupOnUnload = () => this._clearUniqueKeys();
// if (typeof window !== 'undefined') {
//   window.addEventListener('beforeunload', this._cleanupOnUnload);
// }

// 移除 destroy 中的以下代码:
// if (typeof window !== 'undefined') {
//   window.removeEventListener('beforeunload', this._cleanupOnUnload);
// }

// 删除 _clearUniqueKeys 方法
```

> **推荐采用方案一**，既保留去重保护清理的意图，又避免影响其他上传任务。

---

## 修复清单汇总

| Bug # | 文件 | 行号 | 问题 | 修复方法 |
|-------|------|------|------|----------|
| #1 | `folderUpload.js` | 522 | totalChunks 用 8MB 而非 32MB | 改用 `UPLOAD_CONSTANTS.CHUNK_SIZE` |
| #2 | `folderUpload.js` | 319-326 | O(n) 遍历 Map | 改用 `folderMap.get(path)` |
| #3 | `folderUpload.js` | 440 | folderPath 始终传 null | 从 `webkitRelativePath` 提取并传递 |
| #4 | `folderUpload.js` | 77-81 | clear() 清除所有 key | 改为只清除当前实例关联的 key |

所有修复均集中在 **一个文件**: `spug_web/src/pages/document/stores/upload/core/folderUpload.js`

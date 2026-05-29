# UploadPanel.js 修复报告

## 问题描述

点击传输列表后，控制台出现以下错误：

```
Uncaught TypeError: Invalid attempt to spread non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.
    at _nonIterableSpread (nonIterableSpread.js:2:1)
    at _toConsumableArray (toConsumableArray.js:6:1)
    at List (index.js:175:1)
```

## 问题原因

在前端队列租户隔离改造中，`UploadCoreStore.uploadQueue` 从**数组结构**改为**按租户分组的对象结构**：

```javascript
// 修改前（数组）
uploadQueue = [
  { id: 1, name: 'file1.txt', ... },
  { id: 2, name: 'file2.txt', ... }
]

// 修改后（对象）
uploadQueue = {
  'admin': [
    { id: 1, name: 'file1.txt', tenantId: 'admin', ... }
  ],
  'admin1': [
    { id: 2, name: 'file2.txt', tenantId: 'admin1', ... }
  ]
}
```

同时新增了 `currentUploadQueue`（computed 属性）来获取当前租户的队列：

```javascript
@computed
get currentUploadQueue() {
  const tenantId = this.getCurrentTenantId();
  return this.uploadQueue[tenantId] || [];
}
```

但是 `UploadPanel.js` 仍在直接使用 `uploadQueue`，导致尝试对对象进行数组操作时出错。

## 修复方案

将 `UploadPanel.js` 中所有使用 `uploadQueue` 的地方改为使用 `currentUploadQueue`。

### 修改位置

1. **第 231 行** - 从 store 解构
   ```javascript
   // 修改前
   const { uploadQueue, ... } = uploadCoreStore;
   
   // 修改后
   const { currentUploadQueue, ... } = uploadCoreStore;
   ```

2. **第 239 行** - 计算统计信息
   ```javascript
   // 修改前
   const { ... } = calculateStats(uploadQueue);
   
   // 修改后
   const { ... } = calculateStats(currentUploadQueue);
   ```

3. **第 255 行** - 判断队列为空
   ```javascript
   // 修改前
   {uploadQueue.length === 0 ? (
   
   // 修改后
   {currentUploadQueue.length === 0 ? (
   ```

4. **第 292 行** - List 数据源
   ```javascript
   // 修改前
   <List dataSource={uploadQueue} ... />
   
   // 修改后
   <List dataSource={currentUploadQueue} ... />
   ```

5. **第 304 行** - 判断队列有数据
   ```javascript
   // 修改前
   {uploadQueue.length > 0 && (
   
   // 修改后
   {currentUploadQueue.length > 0 && (
   ```

## 修复结果

修复后，`UploadPanel` 组件能够正确显示当前租户的传输列表，不再出现错误。

## 验证

```bash
✓ 无语法错误
✓ 无 lint 错误
✓ 传输列表正常显示
```

## 影响范围

- **文件**: `spug_web/src/pages/document/UploadPanel.js`
- **修改行数**: 5 处
- **影响功能**: 传输面板显示

## 相关文档

- `tests/前端队列租户隔离完成报告.md` - 前端队列改造详细说明

---

**修复人员**: Auto AI Assistant
**修复时间**: 2026-03-01
**文档版本**: v1.0

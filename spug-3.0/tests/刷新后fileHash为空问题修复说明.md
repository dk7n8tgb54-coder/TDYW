# 刷新后 fileHash 为空问题修复说明

## 问题描述
刷新页面后，已上传/暂停的任务需要重新选择文件才能继续上传，这是因为：
1. 创建传输记录时 `file_hash` 参数为空（MD5 还未计算）
2. 刷新后从后端恢复记录时，`fileHash` 为 null
3. 前端检测到无 `fileHash`，显示"重新选择文件"按钮

## 修复方案

### 1. 前端：上传开始后更新后端 file_hash
**文件**: `spug_web/src/pages/document/stores/UploadCoreStore.js`
**位置**: 第 640-650 行（MD5 计算完成后）

**修改内容**:
```javascript
// 【P0修复】更新后端传输记录的 file_hash，确保刷新后能续传
if (uploadItem.transferId) {
  try {
    const { http } = await import('libs');
    await http.post(`/api/document/transfers/${uploadItem.transferId}/update_hash/`, {
      file_hash: fileHash
    });
    console.log('[传输] 更新传输记录 file_hash:', uploadItem.transferId, fileHash);
  } catch (error) {
    console.error('[传输] 更新 file_hash 失败:', error);
    // 不阻塞上传流程，静默处理
  }
}
```

### 2. 后端：新增更新 file_hash 接口
**文件**: `data/backend/apps/document/views.py`
**类名**: `TransferHashUpdateView`
**位置**: 插入在 `TransferFailView` 之前（第 3069 行）

**功能**:
- 权限检查：只能更新自己的传输记录
- 格式验证：file_hash 必须是 32 位十六进制字符串
- 幂等性：支持多次更新（如 MD5 重新计算）
- 记录日志：记录新旧 hash 便于追踪

**API 端点**: `POST /api/document/transfers/<transfer_id>/update_hash/`

**URL 配置**:
**文件**: `data/backend/apps/document/urls.py`
**位置**: 第 36 行后新增
```python
path('transfers/<int:transfer_id>/update_hash/', TransferHashUpdateView.as_view()),  # 【P0修复】更新 file_hash 接口
```

## 验证步骤

### 测试场景：刷新后恢复任务（有 fileHash）

1. **上传一个大文件（>20MB）**
   - 观察控制台日志：`[传输] 更新传输记录 file_hash: 123 xxx`
   - 上传几个分片后暂停

2. **刷新页面**
   - 观察传输列表是否恢复
   - 检查任务是否显示「开始」按钮（绿色播放图标）

3. **点击「开始」按钮**
   - 检查是否直接从断点续传（不提示重新选择文件）
   - 检查进度是否正确增长

**预期结果**:
- ✓ MD5 计算完成后更新后端 `file_hash`
- ✓ 刷新后 `fileHash` 不为空
- ✓ 点击"开始"直接续传，无需重新选择文件

### 测试场景：刷新后恢复任务（无 fileHash - 旧数据兼容）

1. **上传一个大文件**
   - 在 MD5 计算完成前直接关闭页面（模拟旧数据场景）
   - 或者手动清空数据库记录的 `file_hash` 字段

2. **刷新页面**
   - 观察传输列表是否恢复
   - 检查任务是否显示"重新选择文件"按钮

3. **点击"重新选择文件"按钮**
   - 选择原文件
   - 检查是否自动开始上传
   - 检查是否从断点续传

**预期结果**:
- ✓ 显示"重新选择文件"按钮
- ✓ 点击后弹出文件选择对话框
- ✓ 选择文件后自动开始上传
- ✓ 从断点续传

## 技术细节

### 为什么创建记录时 file_hash 为空？
- 用户选择文件后立即创建传输记录（状态：PENDING）
- 此时 MD5 计算还未开始，`file_hash` 未知
- 后端设计允许 `file_hash` 为空（`blank=True, null=True`）

### 为什么不能在创建记录前计算 MD5？
- 大文件 MD5 计算耗时较长（可能几十秒）
- 用户需要立即看到任务已创建
- 异步计算 MD5 更符合用户体验

### 为什么需要单独的更新接口？
- 前端异步计算 MD5，需要独立的上传接口
- 不依赖上传进度更新接口（避免逻辑耦合）
- 支持多次更新（如 MD5 重新计算）

## 风险评估

| 风险 | 等级 | 说明 | 缓解措施 |
|------|------|------|------|
| 后端更新失败 | 🟢 低 | 前端静默处理，不阻塞上传流程 |
| MD5 格式错误 | 🟢 低 | 后端验证 MD5 格式（32位十六进制） |
| 并发更新冲突 | 🟢 低 | Django `update_fields=['file_hash']` 原子更新 |
| 权限绕过 | 🟢 低 | 严格的权限检查（用户 + 租户） |

**总体风险**: 🟢 低（可控）

## 总结

✅ **核心问题已解决**：
- MD5 计算完成后立即更新后端 `file_hash`
- 刷新后从后端恢复的记录包含 `fileHash`
- 用户可以直接点击"开始"续传，无需重新选择文件

✅ **向后兼容**：
- 旧数据（无 `file_hash`）仍支持重新选择文件
- 新数据（有 `file_hash`）直接续传
- 无破坏性变更

✅ **代码质量**：
- 后端接口完整（权限、验证、日志）
- 前端错误处理完善（静默处理失败）
- 独立接口，职责清晰

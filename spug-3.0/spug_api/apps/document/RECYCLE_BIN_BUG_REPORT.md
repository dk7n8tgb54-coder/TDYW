# 资料库回收站功能检查报告

**生成时间**: 2026-06-04
**检查范围**: 回收站恢复/删除功能（前后端）
**状态**: ✅ 部分修复

---

## 问题总览

| 序号 | 问题类型 | 严重程度 | 影响功能 | 状态 |
|------|----------|----------|----------|------|
| 1 | `current_folder_id` 参数从未传递 | 🔴 高危 | 恢复文件-当前浏览模式 | ✅ 已修复（通过移除该功能） |
| 2 | 批量恢复/删除权限校验可能存在问题 | 🟡 中危 | 批量操作 | ⚠️ 待验证 |
| 3 | 前端恢复选项过多，用户希望简化 | 🟢 低危 | UI交互 | ✅ 已修复 |

---

## 已修复问题

### 问题1 & 3: 恢复功能简化为"原位置"模式

**修复日期**: 2026-06-04

**修复内容**:

1. **前端 `RestoreModal.js`**:
   - 移除了"当前浏览的文件夹"和"指定文件夹"选项
   - 只保留"原位置"恢复选项
   - 清理了不再使用的 import（TreeSelect, Spin, FolderOutlined, GlobalOutlined）

2. **前端 `RecycleBinBusinessStore.js`**:
   - `doRestore` 方法简化为只接收 `selectedRows` 和 `idempotentKey` 参数
   - 文件恢复固定使用 `restore_mode='original'`

3. **前端 `stores/index.js`**:
   - 更新 `doRestore` 调用，移除不再需要的参数

4. **前端 `service.js`**:
   - 更新 `restoreFiles` 函数文档注释

5. **后端 `restore.py`**:
   - 移除 `target_folder_id` 和 `current_folder_id` 参数
   - 简化 `_restore_single_file` 方法，直接恢复到原位置
   - 删除不再需要的方法：`_restore_file`, `_restore_private_file`, `_restore_public_file`, `_get_folder`, `_resolve_target_folder`
   - 清理不再使用的 import

**修改文件清单**:

| 文件 | 修改类型 |
|------|----------|
| `spug_api/apps/document/views/recycle_bin/restore.py` | 重构简化 |
| `spug_web/src/pages/document/recycle-bin/RestoreModal.js` | UI简化 |
| `spug_web/src/pages/document/recycle-bin/stores/RecycleBinBusinessStore.js` | 逻辑简化 |
| `spug_web/src/pages/document/recycle-bin/stores/index.js` | 调用简化 |
| `spug_web/src/pages/document/recycle-bin/service.js` | 文档更新 |

---

## 待验证问题

### 问题2: 批量操作权限校验

**说明**: 批量删除时，私有空间文件有租户校验，但公共空间文件没有租户校验。需在实际环境中验证是否存在跨租户删除风险。

**建议**: 如发现批量删除问题，可考虑：
1. 对公共空间文件增加创建者或管理员权限校验
2. 批量操作前先筛选出用户有权限操作的文件

---

## 测试建议

1. ✅ **恢复文件 - 原位置模式**: 选择已删除文件，点击恢复，验证是否成功恢复到原位置
2. ✅ **恢复文件 - 当前浏览模式**: 已移除该选项
3. ✅ **恢复文件 - 指定文件夹模式**: 已移除该选项
4. ⚠️ **批量恢复**: 选择多个文件，点击批量恢复 - 验证是否正常
5. ⚠️ **删除文件**: 选择文件，点击彻底删除 - 验证权限检查是否正常
6. ⚠️ **批量删除**: 选择多个文件，点击批量删除 - 验证是否正常

---

## 附录：相关文件清单

| 文件路径 | 说明 |
|----------|------|
| `spug_api/apps/document/views/recycle_bin/restore.py` | 恢复文件视图（已简化） |
| `spug_api/apps/document/views/recycle_bin/delete.py` | 删除文件视图 |
| `spug_api/apps/document/views/recycle_bin/folder_restore.py` | 恢复文件夹视图 |
| `spug_api/apps/document/views/recycle_bin/folder_delete.py` | 删除文件夹视图 |
| `spug_web/src/pages/document/recycle-bin/stores/RecycleBinBusinessStore.js` | 回收站业务逻辑Store（已简化） |
| `spug_web/src/pages/document/recycle-bin/RestoreModal.js` | 恢复弹窗组件（已简化） |
| `spug_web/src/pages/document/recycle-bin/service.js` | API服务调用 |

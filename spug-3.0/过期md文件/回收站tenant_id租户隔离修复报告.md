# 回收站 tenant_id 租户隔离修复报告

## 修复目标

使用 `tenant_id` 字段实现资料库回收站的租户隔离。

## 模型确认

`DocumentFilePrivate` 和 `DocumentFilePublic` 模型确实包含 `tenant_id` 字段：

```python
# models.py 第111行
tenant_id = models.CharField(max_length=50, default='', help_text='租户标识')
```

## 修复内容

### 1. 列表查询 - 单空间筛选 (`_get_paginated_results` 方法)

**文件**: `spug_api/apps/document/views/recycle_bin.py` (第135-158行)

**修改前**:
```python
if not user.is_supper:
    qs = qs.filter(created_by=user)
```

**修改后**:
```python
if not user.is_supper:
    user_tenant_id = getattr(user, 'tenant_id', '')
    qs = qs.filter(tenant_id=user_tenant_id)
```

### 2. 列表查询 - 全部空间筛选 (`_get_paginated_results` 方法)

**文件**: `spug_api/apps/document/views/recycle_bin.py` (第160-237行)

**修改前**:
```python
if not user.is_supper:
    private_qs = private_qs.filter(created_by=user)
    public_qs = public_qs.filter(created_by=user)
```

**修改后**:
```python
user_tenant_id = getattr(user, 'tenant_id', '')

if not user.is_supper:
    private_qs = private_qs.filter(tenant_id=user_tenant_id)
    public_qs = public_qs.filter(tenant_id=user_tenant_id)
```

### 3. 统计视图 - 私有文件统计 (`RecycleBinStatsView` 方法)

**文件**: `spug_api/apps/document/views/recycle_bin.py` (第828-844行)

**修改前**:
```python
if not request.user.is_supper:
    private_queryset = private_queryset.filter(
        Q(created_by=request.user) |
        Q(tenant_id=user_tenant_id, created_by=request.user)
    )
```

**修改后**:
```python
if not request.user.is_supper:
    private_queryset = private_queryset.filter(tenant_id=user_tenant_id)
```

### 4. 统计视图 - 公共空间统计 (`RecycleBinStatsView` 方法)

**文件**: `spug_api/apps/document/views/recycle_bin.py` (第860-874行)

**修改前**:
```python
public_queryset = DocumentFilePublic.all_objects.filter(
    is_deleted=True
).filter(
    Q(created_by=request.user) |
    Q(tenant_id=user_tenant_id, created_by=request.user)
)
```

**修改后**:
```python
public_queryset = DocumentFilePublic.all_objects.filter(
    is_deleted=True,
    tenant_id=user_tenant_id
)
```

## 租户隔离逻辑

### 非管理员用户
- 只能看到 `tenant_id` 与自己 `user.tenant_id` 匹配的文件
- 不再使用 `created_by` 过滤，实现真正的租户隔离

### 管理员用户 (is_supper=True)
- 可以看到所有租户的文件
- 不过滤 `tenant_id`

## 操作步骤

1. **容器已重启** (后端修复已生效)
   ```powershell
   docker-compose -f dev/docker-compose.yml restart spug
   ```

2. **清空浏览器缓存** (Ctrl+Shift+R)

3. **测试验证**
   - 删除私密空间文件
   - 检查回收站"全部空间"是否正确显示
   - 检查"私密空间"筛选是否正确
   - 检查"公共空间"筛选是否正确

## 预期结果

- **全部空间**: 显示当前租户下私密空间 + 公共空间的所有已删除文件
- **私密空间**: 仅显示当前租户下私密空间的已删除文件
- **公共空间**: 仅显示当前租户下公共空间的已删除文件
- **统计数据**: 正确显示当前租户的文件统计

## 注意事项

1. 此修复假设所有文件记录的 `tenant_id` 字段已正确设置
2. 如果历史数据的 `tenant_id` 为空字符串，可能需要数据修复
3. 权限检查（如恢复、删除）仍使用 `created_by` 判断文件所有者

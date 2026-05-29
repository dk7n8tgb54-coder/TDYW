# 资料库模块 Bug 检查报告

**检查范围**: `e:/TDYW/spug-3.0/spug_api/apps/document/` 整个模块  
**检查日期**: 2026-03-31  
**检查人**: AI Code Reviewer

---

## 一、严重级别 (Critical)

### 1. 文件下载时内存占用过高（可能导致OOM）
**文件**: `views/file/download.py` 第58-75行

```python
with open(file.file_path, 'rb') as f:
    response = HttpResponse(f.read())  # 【问题】大文件会一次性读入内存
```

**问题描述**: 使用 `f.read()` 一次性读取整个文件到内存，对于大文件（如GB级别）会导致内存溢出。

**修复建议**:
```python
from django.http import StreamingHttpResponse

def file_iterator(file_path, chunk_size=1024*1024):
    with open(file.file_path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk

response = StreamingHttpResponse(
    file_iterator(file.file_path),
    content_type=file.file_type
)
```

---

### 2. 文件夹下载时内存占用过高（ZIP打包）
**文件**: `views/folder/download.py` 第53-61行

```python
zip_buffer = io.BytesIO()  # 【问题】内存中构建ZIP，大文件夹会OOM
with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
    ...
response = HttpResponse(zip_buffer.read())  # 【问题】再次全量读取
```

**问题描述**: 整个ZIP文件在内存中构建，对于包含大量文件的文件夹会导致内存溢出。

**修复建议**: 使用临时文件或流式ZIP生成，或限制打包文件夹大小。

---

### 3. 异常捕获过于宽泛导致隐藏真实错误
**文件**: `views/file/copy.py` 第36-37行

```python
except Exception:
    return None, '参数错误'  # 【问题】隐藏了真实异常信息
```

**问题描述**: 捕获所有异常并返回模糊的"参数错误"，不利于问题排查，可能掩盖严重错误。

**修复建议**:
```python
except json.JSONDecodeError as e:
    logger.error(f'解析JSON失败: {e}')
    return None, '参数格式错误'
except Exception as e:
    logger.error(f'解析参数失败: {e}', exc_info=True)
    return None, '参数错误'
```

---

### 4. 软删除文件夹时未检查子文件夹权限
**文件**: `views/folder/views.py` 第318-379行 `_delete_folder` 方法

```python
# 递归软删除子文件夹
sub_folders_query = FolderModel.objects.filter(parent=folder, is_deleted=False)
if request_user and not is_public:
    sub_folders_query = apply_tenant_filter(sub_folders_query, request_user, strict_mode=True)
sub_folders_count = sub_folders_query.count()

if sub_folders_count > 0:
    for sub_folder in sub_folders_query:
        self._delete_folder(sub_folder, ...)  # 【问题】递归时权限检查可能不完整
```

**问题描述**: 递归删除子文件夹时，虽然应用了租户过滤，但没有像顶层文件夹那样进行公共空间权限检查（`check_public_space_permission`）。

**修复建议**: 在递归调用前添加公共空间权限检查。

---

## 二、高优先级 (High)

### 5. 文件移动时潜在的竞态条件
**文件**: `views/file/move.py` 第74-91行

```python
# 移动操作：只改 folder_id，不移动物理文件
file.folder = target
file.name = generate_unique_logical_name(...)  # 【问题】非原子操作
file.save(update_fields=['folder', 'name', 'updated_at'])
```

**问题描述**: 检查同名冲突和保存之间有时间窗口，高并发下可能出现重复文件名。

**修复建议**: 使用数据库事务和唯一约束保证原子性。

---

### 6. 回收站恢复时未验证目标文件夹权限
**文件**: `views/recycle_bin/restore.py` 第139-156行

```python
elif mode == 'custom' and target_folder_id:
    try:
        target_folder = DocumentFolderPrivate.all_objects.get(id=target_folder_id)
        file_obj.folder = target_folder  # 【问题】未检查用户是否有权限写入目标文件夹
    except DocumentFolderPrivate.DoesNotExist:
        ...
```

**问题描述**: 恢复到自定义文件夹时，没有验证用户是否有权限向该文件夹写入。

**修复建议**: 添加目标文件夹权限检查。

---

### 7. 分片上传缺少大小校验
**文件**: `views/upload/validators.py` 第234-263行 `save_chunk_file`

```python
with open(chunk_path, 'wb+') as f:
    for chunk in chunk_file.chunks():
        f.write(chunk)  # 【问题】未校验实际写入大小
```

**问题描述**: 没有验证实际写入的分片大小是否与预期一致，可能被恶意利用写入超大文件。

**修复建议**: 添加分片大小校验和累计大小限制。

---

### 8. 搜索功能潜在的SQL注入风险
**文件**: `views/search.py` 第82-85行

```python
folders_query = FolderModel.objects.filter(
    id__in=folder_ids_to_search,
    name__icontains=keyword  # 【问题】虽然Django ORM有防护，但需注意特殊字符
)
```

**问题描述**: 虽然Django ORM对 `icontains` 有基本防护，但建议对keyword进行清理。

**修复建议**: 添加关键词长度限制和特殊字符过滤。

---

## 三、中优先级 (Medium)

### 9. 限流功能被禁用
**文件**: `views/recycle_bin/utils.py` 第49-84行

```python
def check_rate_limit(user_id, rate_limit_config):
    # TEMPORARILY DISABLED FOR LOAD TESTING
    # 压测完成后请恢复原始限流逻辑
    return True  # 【问题】限流被完全禁用
```

**问题描述**: 限流功能被临时禁用，可能导致系统被滥用。

**修复建议**: 恢复限流逻辑或添加配置开关。

---

### 10. 文件复制时未验证源文件存在性
**文件**: `views/file/copy.py` 第157-161行

```python
@staticmethod
def copy_physical_file(source_path, target_path):
    shutil.copy2(source_path, target_path)  # 【问题】未检查源文件是否存在
```

**问题描述**: 没有检查源物理文件是否存在，可能导致异常。

**修复建议**:
```python
if not os.path.exists(source_path):
    raise FileNotFoundError(f'源文件不存在: {source_path}')
```

---

### 11. 文件夹复制时可能的循环引用
**文件**: `views/folder/folder_copier.py` 第129-166行

```python
def copy_folder(self, source_folder, target_parent):
    # 检查是否复制到自身或子文件夹
    if is_child_folder(target_id, source_folder.id, ...):  # 【问题】只在顶层检查
        ...
    # 递归复制子文件夹时不再检查
    self._copy_child_folders(source_folder, new_folder)
```

**问题描述**: 虽然顶层检查了循环引用，但深层递归时如果数据结构异常仍可能出问题。

**修复建议**: 在递归过程中维护已访问集合。

---

### 12. 传输记录创建时缺少幂等性校验
**文件**: `views/transfer/create.py` 第44-62行

```python
transfer = DocumentTransfer.objects.create(
    tenant_id=tenant_id,
    user=request_user,
    ...
)  # 【问题】重复提交会创建多条记录
```

**问题描述**: 没有幂等性校验，网络重试时可能创建重复记录。

**修复建议**: 添加幂等键或基于file_hash+user的去重逻辑。

---

## 四、低优先级 (Low)

### 13. 日志中的潜在信息泄露
**文件**: 多个文件

```python
logger.info(f'[Document] File path: {file.file_path}')  # 【问题】可能泄露服务器路径
```

**问题描述**: 日志中记录完整文件路径，可能泄露服务器内部结构。

**修复建议**: 使用相对路径或脱敏处理。

---

### 14. 缓存键构建可能冲突
**文件**: `views/recycle_bin/list.py` 第59行

```python
cache_key = f'recycle_bin:{request.user.id}:{cache_version}:{form.space}:{form.keyword or ""}:{form.page}:{page_size}'
```

**问题描述**: keyword可能包含特殊字符，影响缓存键。

**修复建议**: 对keyword进行哈希或清理。

---

### 15. 软删除文件时未更新相关统计
**文件**: `views/folder/views.py`

**问题描述**: 软删除文件夹后，相关统计缓存可能不一致。

**修复建议**: 确保 `invalidate_cache` 在所有删除操作后被调用。

---

## 五、代码质量建议

### 16. 重复代码
多个视图中都有类似的权限检查代码，建议提取到装饰器。

### 17. 魔法数字
多处使用硬编码的数字（如分页大小、超时时间），建议提取为常量。

### 18. 缺少类型注解
核心函数缺少类型注解，不利于代码维护和IDE支持。

---

## 总结

| 严重程度 | 数量 | 主要问题 |
|---------|------|---------|
| Critical | 4 | 内存溢出风险、异常隐藏 |
| High | 4 | 竞态条件、权限绕过 |
| Medium | 4 | 功能禁用、缺少校验 |
| Low | 4 | 信息泄露、缓存问题 |

**建议优先修复**:
1. 文件下载和文件夹下载的内存问题（Critical）
2. 异常捕获过于宽泛的问题（Critical）
3. 限流功能恢复（Medium）

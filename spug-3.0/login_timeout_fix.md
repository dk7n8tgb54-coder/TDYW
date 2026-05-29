# 登录超时问题修复方案

## 问题现象
- 登录界面点击登录后显示"请求异常:请求超时，文件较大请重试"
- 所有账号都受影响
- 问题在 views.py 迁移后出现

## 根本原因

**document_utils.py 在模块级别导入了 Models 和 tenant_utils**，导致：

```python
# 问题代码（修改前）
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic
)
from apps.libs.tenant_utils import is_superuser
```

当 Django 启动时：
1. `wsgi.py` 启动 APScheduler
2. Scheduler 导入 document 模块
3. document 模块导入 views
4. views 导入 document_utils
5. **document_utils 立即导入 models（数据库操作）**
6. 导致启动延迟，登录请求超时

## 已应用的修复

### 修复 1: document_utils.py - 延迟导入模型

**修改前:**
```python
from apps.document.models import (
    DocumentFolderPrivate, DocumentFilePrivate,
    DocumentFolderPublic, DocumentFilePublic
)
from apps.libs.tenant_utils import is_superuser
```

**修改后:**
```python
# 【性能优化】延迟导入模型，避免启动时加载
def _get_models():
    """延迟导入模型"""
    from apps.document.models import (
        DocumentFolderPrivate, DocumentFilePrivate,
        DocumentFolderPublic, DocumentFilePublic
    )
    return DocumentFolderPrivate, DocumentFilePrivate, DocumentFolderPublic, DocumentFilePublic
```

**函数中使用延迟导入:**
```python
def get_folder_model(is_public=False):
    DocumentFolderPrivate, _, DocumentFolderPublic, _ = _get_models()
    return DocumentFolderPublic if is_public else DocumentFolderPrivate

def get_file_model(is_public=False):
    _, DocumentFilePrivate, _, DocumentFilePublic = _get_models()
    return DocumentFilePublic if is_public else DocumentFilePrivate

def is_global_admin(user):
    from apps.libs.tenant_utils import is_superuser
    return is_superuser(user)
```

## 验证修复

### 1. 语法检查
```bash
cd spug_api
python -m py_compile apps/document/libs/document_utils.py
```

### 2. 重启服务
```bash
# Docker 方式
docker-compose restart api

# 或手动方式
cd spug_api
python manage.py runserver
```

### 3. 测试登录
- 访问登录页面
- 输入账号密码
- 验证是否能正常登录

## 如果问题仍然存在

### 方案 A: 临时禁用 APScheduler 自动启动

编辑 `spug_api/spug/wsgi.py`，注释掉 scheduler 启动代码：

```python
# 临时注释掉以下代码
# try:
#     import fcntl
#     import tempfile
#     lock_file = tempfile.gettempdir() + '/spug_scheduler.lock'
#     ...
```

### 方案 B: 增加前端超时时间

编辑 `spug_web/src/libs/http.js`:

```javascript
// 修改第49行
request.timeout = request.timeout || 60000;  // 从30000改为60000
```

### 方案 C: 检查 Redis 连接

```bash
# 检查 Redis 是否正常
docker exec -it spug_redis redis-cli ping

# 应该返回 PONG
```

## 监控建议

修复后建议监控：

1. **启动时间**: 检查 Django 启动是否变快
2. **登录响应时间**: 检查登录接口响应时间
3. **文件上传功能**: 确保迁移后功能正常

## 相关文件

- `spug_api/apps/document/libs/document_utils.py` - 已修复
- `spug_api/spug/wsgi.py` - 如需可临时修改
- `spug_web/src/libs/http.js` - 如需可修改超时时间

## 总结

**根本原因**: document_utils.py 模块级别导入 Models 导致启动延迟
**解决方案**: 改为延迟导入（函数内导入）
**修复状态**: ✅ 已完成
**验证步骤**: 重启服务 → 测试登录

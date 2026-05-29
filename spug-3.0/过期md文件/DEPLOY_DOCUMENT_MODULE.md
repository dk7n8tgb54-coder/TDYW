# 资料管理模块部署指南

## 快速开始

### 1. 数据库初始化

#### 方法一：直接执行SQL（推荐）

```bash
# 连接到Spug数据库
mysql -u root -p spug

# 执行初始化脚本
source spug_api/apps/document/init.sql
```

#### 方法二：使用Django migrate

```bash
cd spug_api

# 生成迁移文件（如果有django migrations）
python manage.py makemigrations document

# 执行迁移
python manage.py migrate
```

### 2. 创建存储目录

```bash
# 创建文件存储目录
mkdir -p spug_api/storage/documents

# 设置权限（Linux环境）
chmod 755 spug_api/storage/documents
```

### 3. 重启服务

```bash
# 重启API服务
cd spug_api
python manage.py runserver

# 重启前端服务
cd spug_web
npm start
```

### 4. 权限配置

登录Spug系统，进入：**系统管理 > 角色管理**

为需要使用资料管理的角色添加以下权限：

1. **资料查看** → 查看资料
2. **文件夹管理** → 新建文件夹、删除文件夹、移动文件夹
3. **文件管理** → 上传文件、下载文件、删除文件、复制文件

## 验证安装

1. 登录Spug系统
2. 左侧菜单应该出现"资料管理"选项（在主机管理下方）
3. 点击进入，应该可以看到文件夹树和文件列表
4. 测试创建文件夹、上传文件等功能

## 目录结构说明

```
spug_api/apps/document/
├── __init__.py           # 包初始化文件
├── models.py            # 数据模型（文件夹和文件）
├── views.py             # API视图（处理CRUD操作）
├── urls.py              # URL路由配置
├── init.sql             # 数据库初始化SQL脚本
└── README.md            # 详细使用说明

spug_web/src/pages/document/
├── index.js             # 主页面组件
├── store.js             # MobX状态管理
├── FolderTree.js        # 文件夹树组件
├── FolderTree.module.less # 样式文件
├── FileTable.js         # 文件列表组件
├── UploadModal.js       # 上传弹窗组件
├── PreviewModal.js      # 预览弹窗组件
└── PreviewModal.module.less # 预览样式
```

## API端点

### 文件夹管理
- `GET /api/document/folder/` - 获取文件夹列表
- `POST /api/document/folder/` - 创建文件夹
- `DELETE /api/document/folder/?id=<id>` - 删除文件夹
- `POST /api/document/move/` - 移动文件夹

### 文件管理
- `GET /api/document/folder/?id=<folder_id>` - 获取文件列表
- `POST /api/document/upload/` - 上传文件
- `GET /api/document/download/?id=<file_id>` - 下载文件
- `DELETE /api/document/file/?id=<file_id>` - 删除文件
- `GET /api/document/preview/?id=<file_id>` - 预览文件
- `POST /api/document/copy/` - 复制文件

## 常见问题

### 1. 菜单不显示

**问题**: 左侧菜单看不到"资料管理"选项

**解决**:
- 检查前端路由配置：`spug_web/src/routes.js`
- 检查权限配置：确保当前角色有 `document.view` 权限

### 2. 文件上传失败

**问题**: 上传文件时提示错误

**解决**:
- 检查存储目录是否存在：`spug_api/storage/documents`
- 检查目录权限：确保有写入权限
- 检查文件大小：建议单个文件不超过500MB

### 3. 数据库错误

**问题**: 操作时报数据库表不存在

**解决**:
- 执行初始化SQL：`source spug_api/apps/document/init.sql`
- 检查数据库连接配置

### 4. 权限错误

**问题**: 提示无权访问

**解决**:
- 进入系统管理 → 角色管理
- 为相应角色添加资料管理权限
- 退出重新登录

## 卸载说明

如需卸载资料管理模块，请按以下步骤操作：

1. **删除数据库表**:
```sql
DROP TABLE IF EXISTS spug_document_file;
DROP TABLE IF EXISTS spug_document_folder;
```

2. **删除路由配置**:
编辑 `spug_api/spug/urls.py`，删除 `path('document/', include('apps.document.urls'))`

3. **删除前端路由**:
编辑 `spug_web/src/routes.js`，删除资料管理相关路由

4. **删除文件**:
```bash
rm -rf spug_api/apps/document
rm -rf spug_web/src/pages/document
```

5. **删除权限配置**:
编辑 `spug_web/src/pages/system/role/codes.js`，删除document相关配置

## 技术支持

如有问题，请查看详细文档：`spug_api/apps/document/README.md`

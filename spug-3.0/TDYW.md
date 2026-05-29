# TDYW 项目文档

本项目基于 Spug 运维自动化平台进行定制开发，主要服务于排班管理、文档管理、设备管理等功能。

---

## 技术栈详情

### 后端技术栈

**核心框架**
- **Python 3.x** - 编程语言
- **Django 2.2.28** - Web 框架
- **Django REST Framework** - API 开发
- **Django Channels 2.3.1** - WebSocket 支持（实时通信）

**数据库与缓存**
- **MariaDB 10.8.2** - 关系型数据库（MySQL 兼容）
- **Redis** - 缓存、WebSocket 消息队列

**部署与运维**
- **Docker & Docker Compose** - 容器化部署
- **Nginx** - 反向代理和静态文件服务
- **Gunicorn** - WSGI 应用服务器

**关键库与工具**
- `apscheduler` - 任务调度器
- `paramiko` - SSH 客户端
- `GitPython` - Git 操作
- `django-redis` - Redis 缓存支持
- `openpyxl` - Excel 文件处理
- `python-ldap` - LDAP 认证支持
- `user_agents` - 用户代理解析
- `requests` - HTTP 请求库

### 前端技术栈

**核心框架**
- **React 16.13.1** - UI 框架
- **Ant Design 4.21.5** - UI 组件库
- **MobX 5.15.6** - 状态管理
- **React Router 5.2.0** - 路由管理

**构建工具**
- **Webpack** - 模块打包
- **Babel** - JavaScript 转译
- **LESS** - CSS 预处理器

**关键依赖**
- `@ant-design/icons` - 图标库
- `axios` - HTTP 客户端
- `mobx-react` - MobX React 绑定
- `bizcharts` - 数据可视化
- `ace-builds` / `react-ace` - 代码编辑器
- `xterm` / `xterm-addon-fit` - 终端模拟
- `react-player` - 音视频播放
- `moment` - 日期时间处理
- `lodash` - 工具函数库
- `history` - 路由历史管理

### 系统架构

```
┌─────────────────────────────────────────────────┐
│                   Nginx                          │
│              (反向代理 + 静态文件)                 │
└──────────────────┬──────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌──────────────┐      ┌──────────────┐
│  React 前端   │      │ Django 后端   │
│   (Port 80)  │◄────►│  (API 服务)   │
└──────────────┘      └──────┬───────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              ┌──────────┐        ┌──────────┐
              │ MariaDB  │        │  Redis   │
              │   数据库   │        │  缓存    │
              └──────────┘        └──────────┘
```

### 目录结构

**后端开发目录 (`spug_api/`)**
```
spug_api/
├── spug/                 # Django 核心配置
│   ├── settings.py       # 配置文件
│   ├── urls.py           # 主路由
│   └── routing.py        # WebSocket 路由
├── apps/                 # 业务应用模块
│   ├── account/          # 用户认证、权限管理
│   ├── exec/             # 运行日志、排班、故障记录、设备履历
│   ├── document/         # 文档管理（支持租户隔离）
│   ├── config/           # 配置中心
│   ├── home/             # 仪表盘
│   ├── setting/          # 系统设置
│   ├── app/              # 应用管理
│   ├── notify/           # 通知管理
│   ├── repository/       # 代码仓库管理
│   └── file/             # 文件操作
├── libs/                 # 共享工具库
│   ├── middleware.py     # 认证中间件
│   ├── tenant_middleware.py  # 租户中间件
│   ├── decorators.py     # 装饰器
│   ├── ssh.py            # SSH 客户端
│   └── gitlib.py         # Git 操作
├── consumer/             # WebSocket 消费者
├── repos/                # Git 仓库存储
├── storage/              # 文件存储
├── tests/                # 测试文件
└── tools/                # 工具脚本
```

**前端开发目录 (`spug_web/src/`)**
```
spug_web/src/
├── pages/                # 页面组件
│   ├── exec/
│   │   ├── schedule/     # 排班管理
│   │   ├── device_resume/# 设备履历
│   │   └── interference_statistics/
│   ├── document/         # 文档管理
│   │   ├── stores/       # MobX 状态管理
│   │   ├── UploadCoreStore.js  # 上传核心逻辑
│   │   ├── UploadUIStore.js    # 上传UI状态
│   │   └── NavigationStore.js  # 导航状态
│   └── ...
├── components/           # 通用组件
├── libs/                 # 工具库
│   ├── http.js           # HTTP 客户端封装
│   └── utils.js          # 工具函数
├── layout/               # 布局组件
│   ├── index.js          # 主布局
│   └── layout.module.less
└── routes.js             # 路由配置
```

### 数据流转

**认证流程**
```
用户登录 → Token 验证 (middleware) → 权限检查 → 请求处理
                    ↓
              租户隔离过滤
```

**WebSocket 实时通信**
```
客户端 ←→ Nginx ←→ Django Channels ←→ Redis ←→ 消费者
```

**文件上传**
```
前端分片上传 → UploadCoreStore → 后端接收 → 按文件夹结构存储至 storage/documents/
                ↓                            ↓
            租户目录隔离            文件夹结构组织
                                      - 文件夹文件: storage/documents/folder_{id}/
                                      - 根目录文件: storage/documents/
```

### 多租户架构

- **租户标识**: `tenant_id` 字段
- **数据隔离**: 所有查询自动过滤 `request.user.tenant_id`
- **权限控制**: 基于角色的访问控制（RBAC）

### 核心功能模块

1. **排班管理**
   - 班次调整（换班、替班）
   - 值班日历
   - 批量调整

2. **文档管理**
   - 文件/文件夹管理
   - 分片上传
   - 多租户隔离
   - 预览功能
   - **按文件夹结构存储**：文件按照 `folder_{id}/` 目录组织存储
   - **安全校验**：文件名和文件夹名包含路径遍历和非法字符检测

3. **设备管理**
   - 设备信息管理
   - 设备履历
   - 运行日志

4. **权限系统**
   - 用户管理
   - 角色管理
   - 权限分配

---

## 常用命令

### 前端开发 (spug_web)
```bash
cd spug_web
npm start                    # 启动开发服务器（支持热重载）
npm run build               # 构建生产版本
npm test                    # 运行测试
```

### 后端开发 (spug_api)
```bash
cd spug_api
python manage.py runserver    # 启动 Django 开发服务器
python manage.py makemigrations  # 创建迁移文件
python manage.py migrate      # 应用数据库迁移
python manage.py createsuperuser  # 创建超级管理员
```

### Docker (全栈)
```bash
docker-compose up -d          # 启动所有服务
docker-compose down          # 停止所有服务
docker-compose logs -f spug  # 查看 spug 容器日志
docker-compose restart spug    # 重启 spug 容器
```

### 前端构建与部署
```bash
# 构建前端并同步到挂载卷
cd spug_web
npm run build
# 文件将同步到 spug_web/build（映射到容器中）
```

### 数据库操作
```bash
# 直接访问 MySQL
docker exec -it spug-db mysql -uspug -pspug.cc spug

# 重置管理员密码
python data/backend/reset_pass.py

# 执行 SQL 脚本
python data/backend/run_sql.py < your_script.sql
```

### 密码使用环境变量

项目支持通过环境变量配置数据库密码，提升安全性和灵活性：

**环境变量配置文件**：`.env`

**使用方法**：
1. 复制 `.env.example` 为 `.env` 文件
2. 根据需要修改 `.env` 中的密码配置
3. 在 `docker-compose.yml` 中通过 `env_file` 引用 `.env` 文件

**配置示例**：
```bash
# .env 文件内容
MYSQL_DATABASE=spug
MYSQL_USER=spug
MYSQL_PASSWORD=your_secure_password  # 修改为安全密码
MYSQL_ROOT_PASSWORD=your_root_password  # 修改为安全密码
DJANGO_SECRET_KEY=change_me_to_random_secret_key_in_production
```

**重要注意事项**：
- ⚠️ `.env` 文件包含敏感信息，已在 `.gitignore` 中配置，不会被提交到版本控制系统
- 🔒 生产环境部署时，请务必使用强密码（建议使用 `openssl rand -base64 32` 生成随机密钥）
- 📝 密码修改后需要重启容器才能生效：`docker-compose down && docker-compose up -d`

---

## 开发流程

1. **后端修改:**
   - 编辑 `spug_api/` 目录中的文件
   - 创建迁移文件：`python manage.py makemigrations`
   - 应用迁移：`python manage.py migrate`
   - **重要**：修改后端代码后需要重启容器才能生效：`docker-compose restart spug`
   - 通过卷挂载，更改会自动反映到容器中

2. **前端修改:**
   - 编辑 `spug_web/src/` 目录中的文件
   - 使用 `npm start` 时自动支持热重载
   - 生产环境构建：`npm run build`
   - 构建产物同步到 `spug_web/build`

3. **数据库修改:**
   - 使用迁移进行架构变更
   - 一次性任务可使用自定义 SQL 脚本
   - 重大变更前先备份：`mysqldump`

4. **调试:**
   - 后端日志：`docker logs -f spug`
   - 数据库日志：`docker logs -f spug-db`
   - 前端开发：浏览器控制台 + React DevTools
   - Django DEBUG 模式：在 `spug/settings.py` 中设置

---

## 配置文件

- `data/backend/spug/settings.py` - Django 设置（数据库、缓存、密钥）
- `docker-compose.yml` - 服务编排、环境变量
- `spug_web/package.json` - 前端依赖和脚本
- `.env` - 环境变量（如果需要，从模板创建）

**数据库连接:**
- Docker 环境：`MYSQL_HOST=db`（容器名）
- 本地开发：`MYSQL_HOST=127.0.0.1`
- 凭证通过 docker-compose.yml 中的环境变量设置

**开发环境映射关系 (docker-compose.yml):**
```
宿主机路径                          容器内路径                              用途
E:/TDYW/spug-3.0/data/mysql       /var/lib/mysql                          MySQL 数据文件
E:/TDYW/spug-3.0/spug_web/build   /data/spug/spug_web/build              前端构建产物
E:/TDYW/spug-3.0/data/repos       /data/repos                            代码仓库存储
E:/TDYW/spug-3.0/spug_api         /data/spug/spug_api                    后端代码目录
E:/TDYW/spug-3.0/data/document-files /data/spug/spug_api/storage/documents 资料库文件存储
E:/TDYW/spug-3.0/config/dev/nginx.conf /etc/nginx/nginx.conf            Nginx 配置文件
```

**重要说明:**
- `data/document-files` 是资料库模块文件的实际存储位置（映射自容器内的 `/data/spug/spug_api/storage/documents`）
- 容器内的代码路径是 `/data/spug/spug_api`，对应宿主机的 `spug_api`
- 开发时修改 `spug_api` 中的文件会实时同步到容器内（通过 Bind Mount）

---

## 重要注意事项

1. **开发目录**：`spug_api/` 是后端开发目录，`spug_web/src/` 是前端开发目录
2. **前端开发使用 `npm start`**：开发过程中使用 `npm start` 启动前端服务（支持热重载），修改后自动生效，无需执行 `npm run build`
3. **前端部署才需构建**：仅在部署到生产环境或容器时才需要执行 `npm run build`
4. **数据库架构变更使用迁移**，避免手动 SQL
5. **调试时首先查看容器日志**：`docker logs spug`
6. **权限键遵循模式**：`{module}.{entity}.{action}`
7. **所有视图都需要多租户过滤** - 确保 `tenant_id` 被过滤

---

## 资料库模块权限规则

### 多租户隔离规则

#### 私有空间隔离
- **超级管理员 (`is_supper=True`)**：可查看所有租户的文件
- **全局管理员 (`is_global_admin=True`)**：只能查看和操作自己租户的文件（按租户过滤）
- **普通用户**：只能查看和操作自己租户的文件（按租户过滤）

#### 公共空间权限规则

公共空间的数据隔离规则如下：

| 操作 | 普通用户 | 全局管理员 | 超级管理员 |
|-----|---------|-----------|-----------|
| 查看（列表） | ✅ 所有人可查看 | ✅ 所有人可查看 | ✅ 所有人可查看 |
| 下载 | ✅ 所有人可下载 | ✅ 所有人可下载 | ✅ 所有人可下载 |
| 预览（图片/PDF/视频） | ✅ 所有人可预览 | ✅ 所有人可预览 | ✅ 所有人可预览 |
| 重命名 | ❌ 仅操作自己创建的 | ❌ 仅操作自己创建的 | ✅ 可操作所有 |
| 删除 | ❌ 仅删除自己创建的 | ❌ 仅删除自己创建的 | ✅ 可删除所有 |
| 复制 | ❌ 仅复制自己创建的 | ❌ 仅复制自己创建的 | ✅ 可复制所有 |
| 移动 | ❌ 仅移动自己创建的 | ❌ 仅移动自己创建的 | ✅ 可移动所有 |

### 错误提示规范

公共空间权限错误提示遵循友好提示原则：

- `公共空间中只能删除自己创建的文件/文件夹`
- `公共空间中只能重命名自己创建的文件/文件夹`
- `公共空间中只能复制自己创建的文件/文件夹`
- `公共空间中只能移动自己创建的文件/文件夹`

### 实现细节

**租户过滤函数位置**：`spug_api/apps/libs/tenant_utils.py`

```python
def apply_tenant_filter(queryset, request_user):
    """
    应用租户过滤到QuerySet
    只有超级管理员不过滤，全局管理员和普通用户都按租户过滤
    """
    if is_supper:
        # 超级管理员不过滤
        return queryset

    # 全局管理员和普通用户都按租户过滤
    tenant_id = getattr(request_user, 'tenant_id', 'admin')
    return queryset.filter(tenant_id=tenant_id)
```

**视图层应用位置**：`spug_api/apps/document/views.py`

所有接口在查询私有空间数据时，都应调用：
```python
if not is_public:
    queryset = apply_tenant_filter(queryset, request.user)
```

### 文件存储结构

```
storage/documents/
├── public/                    # 公共空间（所有人可见）
│   ├── folder_{id}/          # 文件夹文件
│   └── *.pdf                # 根目录文件
└── private/                  # 私有空间（按租户隔离）
    └── user-{user_id}/       # 每个用户独立目录
        ├── folder_{id}/      # 文件夹文件
        └── *.pdf            # 根目录文件
```

### 安全特性

1. **路径遍历防护**：`is_safe_path()` 验证路径合法性
2. **文件名校验**：检测路径遍历符号（`..`）和非法字符
3. **租户越权告警**：过滤拦截所有数据时记录警告日志
4. **审计日志**：所有关键操作记录操作类型、用户、租户、资源信息

### 安全增强与逻辑修复

#### 后端修复 (2026-02-28)

**P0 级别修复（严重漏洞）：**

1. **`_is_child_folder` 无限循环防护**
   - 添加 `visited_ids` 集合防止循环引用
   - 添加递归深度限制（从配置文件 `MAX_FOLDER_RECURSION_DEPTH` 读取，默认 100）
   - 位置：`views.py:972-1010` 和 `views.py:1087-1122`
   - 影响：防止恶意或异常数据导致服务器 CPU 100%

2. **`_is_child_folder` 租户归属验证**
   - 私有空间始终应用 `apply_tenant_filter`
   - 确保循环引用检查只在同一租户内进行
   - 防止信息泄露，暴露其他租户的文件夹结构

3. **秒传检查租户越权修复**
   - 私有空间：先按租户过滤，再精确匹配文件哈希
   - 避免使用 `icontains` 模糊匹配跨租户查询
   - 位置：`views.py:2028-2048`

4. **ZIP 下载循环检测**
   - `_add_folder_to_zip` 添加 `visited` 集合
   - 防止文件夹下载功能被滥用导致无限递归
   - 位置：`views.py:1214-1260`

**P1 级别修复（高危漏洞）：**

5. **文件夹重命名重名检查租户过滤**
   - 私有空间添加 `apply_tenant_filter`
   - 避免因其他租户同名文件夹导致的错误判断
   - 位置：`views.py:1279-1292`

6. **文件重命名重名检查租户过滤**
   - 私有空间添加 `apply_tenant_filter`
   - 避免因其他租户同名文件导致的错误判断
   - 位置：`views.py:1341-1354`

7. **创建文件夹 parent_id 验证**
   - 添加类型转换和正数校验
   - 拒绝负数、零或非整数值的 parent_id
   - 位置：`views.py:317-330`

#### 配置增强 (2026-02-28)

在 `settings.py` 中新增文档模块配置项：

```python
# 文件夹递归操作最大深度限制（防止循环引用导致无限递归）
MAX_FOLDER_RECURSION_DEPTH = 100

# 文件上传最大大小（字节，默认 10GB）
MAX_DOCUMENT_FILE_SIZE = 10 * 1024 * 1024 * 1024

# 秒传缓存超时时间（秒，默认 24 小时）
DOCUMENT_QUICK_UPLOAD_CACHE_TIMEOUT = 86400

# 分片文件清理时间（秒，默认 24 小时）
DOCUMENT_CHUNK_CLEANUP_AGE = 24 * 3600
```

**增强点：**
- 可配置化：递归深度、文件大小限制等可从配置文件调整
- 维护性：集中管理文档模块参数，便于运维调整

#### 日志增强 (2026-02-28)

**循环引用检测日志：**
- 循环触发时记录为 `warning` 级别
- 包含用户名、folder_id、parent_id 等关键信息
- 示例：`[Document] 检测到循环引用，folder_id=123 已被访问！user=admin, parent_id=456`

**递归深度超限日志：**
- 超过最大深度时记录为 `warning` 级别
- 便于监控潜在的异常数据
- 示例：`[Document] _is_child_folder 超过最大递归深度: 100，可能存在循环引用！user=admin, child_id=123, parent_id=456`

**秒传检查结构化日志：**
- 私有空间：记录租户过滤结果、匹配数量
- 公共空间：记录命中状态
- 示例：`[Document] 秒传检查-租户过滤: user=admin, tenant=test, hash=abc123..., size=1024, 匹配数量=1, 命中=True`

**审计日志增强：**
- 文件上传审计包含租户信息
- 秒传缓存更新包含用户和租户信息
- 便于后续追溯和排查

#### 前端修复 (2026-02-28)

1. **Explorer.js 权限检查完善**
   - 处理 `created_by_id` 为 null 的情况
   - 避免因数据迁移或历史数据导致的编辑失败
   - 位置：`Explorer.js:256-261`

2. **FolderTree.js 边界条件处理**
   - 添加 `Array.isArray` 类型检查
   - 处理 null/undefined 值和空数组情况
   - 位置：`FolderTree.js:113-130`

#### 新增修复 (2026-02-28 晚)

**P1 级别修复（高危漏洞）：**

8. **文件复制同名检查租户过滤**
   - 私有空间：在 `FileCopyView.post` 的同名检查中添加 `apply_tenant_filter`
   - 防止因其他租户同名文件导致错误添加后缀
   - 位置：`views.py:814-832`
   - 影响：确保租户隔离，不同租户的同名文件不会互相影响

9. **文件夹复制同名检查租户过滤**
   - 私有空间：在 `FolderCopyView._copy_folder_recursive` 的同名检查中添加 `apply_tenant_filter`
   - 防止因其他租户同名文件夹导致错误添加后缀
   - 位置：`views.py:928-944`
   - 影响：确保租户隔离，不同租户的同名文件夹不会互相影响

10. **文件夹移动同名检查租户过滤**
    - 私有空间：在 `FolderMoveView.post` 的同名检查中添加 `check_tenant_unique_name`
    - 防止因其他租户同名文件夹导致覆盖
    - 位置：`views.py:1118-1136`
    - 影响：确保租户隔离，不同租户的同名文件夹不会互相覆盖

#### 新增工具函数 (2026-02-28 晚)

11. **租户级同名检查工具函数**
    - 新增 `check_tenant_unique_name` 函数
    - 位置：`tenant_utils.py:210-244`
    - 用途：统一处理租户内的资源名称唯一性检查
    - 调用示例：
      ```python
      is_unique, qs = check_tenant_unique_name(
          FolderModel,
          {'parent_id': target_id, 'name': folder.name},
          request.user,
          is_public
      )
      ```

#### 修复统计

- **P0 级别**：4 个严重漏洞
- **P1 级别**：6 个高危漏洞
- **配置增强**：4 个新增配置项
- **日志增强**：3 处结构化日志优化
- **前端修复**：2 个边界条件处理
- **新增工具函数**：1 个（`check_tenant_unique_name`）
- **总计**：16 项优化完成
- **新增语法错误**：0 个

#### 测试建议

修复后应重点测试以下场景：

**核心安全测试：**
1. **循环引用检测**：手动创建 A→B→C→A 的文件夹结构，验证不会死循环
2. **租户隔离**：验证不同租户无法互相访问文件，秒传不跨租户
3. **复制操作同名检查**：
   - 同一租户内：创建文件「test.docx」，复制到同一文件夹，应添加「副本_」前缀
   - 不同租户：租户A和租户B都创建文件「test.docx」，租户A复制自己的文件，不应因租户B的同名文件而添加额外后缀
   - 多次复制：同一租户内多次复制，应正确添加数字后缀（副本_test.docx, 副本_test_1.docx）
4. **移动操作同名检查详细验证步骤**：

   **环境准备：**
   - 租户A账号创建：文件夹「test」（parent_id=1，根目录下）、目标文件夹「target」（parent_id=null）
   - 租户B账号创建：文件夹「test」（parent_id=1）、目标文件夹「target」（parent_id=null）

   **正向验证（租户内同名检测）：**
   - 租户A在「test」文件夹下创建子文件夹「child1」
   - 租户A尝试将「test」移动到「target」下 → ✅ 移动成功（target下无同名）
   - 租户A在根目录下再次创建文件夹「test2」
   - 租户A尝试将「test2」移动到「target」下 → ✅ 移动成功
   - 租户A再次创建文件夹「test」（因前面移动到target，根目录无test了）
   - 租户A将「test」移动到「target」下 → ✅ 报错「目标位置已存在同名文件夹」

   **租户隔离验证（跨租户不互影响）：**
   - 租户A在「test」下创建子文件夹「a_only」
   - 租户B在「test」下创建子文件夹「b_only」
   - 租户A尝试将「test」移动到「target」下 → ✅ 应根据租户A在target下的同名情况判断，与租户B无关
   - 租户B尝试将「test」移动到「target」下 → ✅ 应根据租户B在target下的同名情况判断，与租户A无关

   **反向验证（根目录同名检查）：**
   - 租户A在根目录创建「root_test」
   - 租户B在根目录创建「root_test」
   - 租户A将某文件夹移动到根目录，命名为「root_test」 → ❌ 报错（租户A已存在）
   - 租户B将某文件夹移动到根目录，命名为「root_test」 → ❌ 报错（租户B已存在）
   - 但租户A的报错不应受租户B影响

5. **边角条件**：测试空文件夹列表、无效 parent_id、null 值

**性能测试：**
6. **递归深度限制**：修改配置 `MAX_FOLDER_RECURSION_DEPTH` 降低阈值测试
7. **循环检测**：创建深层嵌套文件夹，验证循环引用检测不误判

**日志验证：**
8. **审计日志**：检查关键操作的日志是否包含必要信息（租户、用户、操作类型）
9. **租户过滤日志**：验证 `apply_tenant_filter` 的日志输出是否正确
10. **警告日志**：触发异常情况（如越权拦截、循环引用），检查是否记录 warning 级别日志

### 前后端交互设计 (2026-02-28)

#### 后端接口设计

**返回字段规范**:

所有文件夹/文件查询接口统一返回以下字段:

```python
# 文件夹字段
{
    'id': f.id,                          # 整数类型，文件夹ID
    'name': f.name,                       # 字符串，文件夹名称
    'parent_id': f.parent_id,             # 整数或null，父文件夹ID
    'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),  # 字符串，创建时间
    'created_by': f.created_by.nickname if f.created_by else None,  # 字符串或null，创建者昵称
    'created_by_id': f.created_by_id       # 整数，创建者ID
}

# 文件字段
{
    'id': f.id,                          # 整数类型，文件ID
    'name': f.name,                       # 字符串，文件名
    'size': f.file_size,                  # 整数，文件大小（字节）
    'file_type': f.file_type,             # 字符串，文件类型（MIME类型）
    'created_at': f.created_at.strftime('%Y-%m-%d %H:%M:%S'),  # 字符串，创建时间
    'created_by': f.created_by.nickname if f.created_by else None,  # 字符串或null，创建者昵称
    'created_by_id': f.created_by_id       # 整数，创建者ID
}
```

**接口返回示例**:

```json
{
  "folders": [
    {
      "id": 202,
      "name": "技术文档",
      "parent_id": null,
      "created_at": "2026-02-28 10:30:00",
      "created_by": "张三",
      "created_by_id": 123
    }
  ],
  "files": [
    {
      "id": 456,
      "name": "readme.pdf",
      "size": 1024,
      "file_type": "application/pdf",
      "created_at": "2026-02-28 10:35:00",
      "created_by": "张三",
      "created_by_id": 123
    }
  ]
}
```

#### 前端数据处理

**工具函数**:

1. **`generateKey(id, type)`**: 生成字符串类型的唯一key
   - 用途: Ant Design Tree/Table 的 key 属性
   - 实现: `utils/keyUtils.js`
   - 示例: `generateKey(123, 'folder') => 'folder-123'`

2. **`parseRawId(key)`**: 从key解析原始ID
   - 用途: 提取原始ID用于API调用
   - 实现: `utils/keyUtils.js`
   - 示例: `parseRawId('folder-123') => 123`

**数据转换**:

```javascript
// 后端响应处理
const folders = (res.folders || []).map(f => ({
  ...f,
  isFolder: true,
  key: generateKey(f?.id, 'folder'),  // 生成字符串key
  rawId: f?.id                         // 保留原始ID
}));

const files = (res.files || []).map(f => ({
  ...f,
  isFolder: false,
  key: generateKey(f?.id, 'file'),
  rawId: f?.id
}));
```

**树形结构构建**:

```javascript
buildTreeData = (parentId, folders) => {
  // 边界检查
  if (!Array.isArray(folders)) return [];

  // 构建映射，跳过无效数据
  const folderMap = new Map();
  folders.forEach(f => {
    if (!f || !f.id) return;
    folderMap.set(f.id, {
      id: f.id,
      name: f.name || '未命名',
      parent_id: f.parent_id,
      created_at: f.created_at,
      created_by: f.created_by,
      created_by_id: f.created_by_id
    });
  });

  // 递归构建树
  const children = [];
  for (const [, folder] of folderMap) {
    const isChild = parentId === null ? !folder.parent_id : folder.parent_id === parentId;
    if (isChild) {
      children.push(folder);
    }
  }

  return children.map(f => ({
    key: generateKey(f.id, 'folder'),
    rawId: f.id,
    title: f.name,
    children: this.buildTreeData(f.id, folders)
  }));
};
```

#### 错误处理机制

**后端错误处理**:

```python
try:
    # 业务逻辑
    return json_response(data)
except Exception as e:
    logger.error(f'[Document] Error: {e}')
    return json_response(error=str(e))
```

**前端错误处理**:

```javascript
try {
  const res = await http.get('/api/document/folder/', { params });
  // 处理数据
  this.setState({ data: res });
} catch (error) {
  console.error('[Component] API error:', error);
  this.setState({ data: [], error: error.message });
  // 显示空状态或错误提示
}
```

**关键特性**:
- 所有 API 调用都有 try-catch 包装
- 错误不抛出，避免未处理的 Promise rejection
- 失败时显示友好的空状态
- 详细的错误日志记录

#### 空状态提示

**公共空间空状态**:

```jsx
<Empty
  description={
    <div>
      <div style={{ fontSize: 16, marginBottom: 8 }}>暂无公共共享文件</div>
      <div style={{ fontSize: 14, color: '#999' }}>
        快来上传第一个文件，与全平台用户共享吧
      </div>
    </div>
  }
/>
```

**私有空间空状态**:

```jsx
<Empty
  description={
    <div>
      <div style={{ fontSize: 16, marginBottom: 8 }}>暂无文件</div>
      <div style={{ fontSize: 14, color: '#999' }}>
        点击上传按钮开始上传你的第一个文件
      </div>
    </div>
  }
/>
```

**文件夹内容空状态**:

```jsx
<Empty
  image={null}
  description={<span style={{ color: '#999', fontSize: 12 }}>文件夹为空</span>}
/>
```

#### 异常数据处理

**边界检查**:

```javascript
// 确保数据类型正确
if (!Array.isArray(folders)) {
  console.warn('[Component] folders is not an array:', folders);
  return [];
}

// 跳过无效数据
folders.forEach(f => {
  if (!f || !f.id) return;
  // 处理有效数据
});

// 处理null值
name: f.name || '未命名'
created_by: f.created_by || null
```

**循环引用检测**:

```javascript
// 检查 parent_id 是否指向自身
const hasLoopRef = f.parent_id === f.id;
if (hasLoopRef) {
  console.warn('[Component] 检测到循环引用:', f.name);
}
```

**去重处理**:

```javascript
// 使用 Map 基于 key 去重
const seen = new Map();
const items = [...folders, ...files].filter(item => {
  if (seen.has(item.key)) {
    console.warn('[Component] 检测到重复ID:', item.key);
    return false;
  }
  seen.set(item.key, true);
  return true;
});
```

#### 类型统一性

| 字段 | 后端类型 | 前端处理 | 说明 |
|------|---------|---------|------|
| id | int | number | 原始ID保持数字类型 |
| parent_id | int\|null | number\|null | 保持原始类型 |
| name | str | string | 字符串类型 |
| created_at | str | string | 格式化后的时间字符串 |
| created_by_id | int | number | 数字类型 |

**关键点**:
- 后端 ID 都是整数类型
- 前端使用 `rawId` 保留原始数字类型
- 前端使用 `key` 属性为字符串类型(满足组件要求)
- 通过工具函数进行类型转换

### 代码规范与可维护性优化 (2026-02-28)

#### 资料库模块租户过滤全场景检查清单

| 业务场景 | 是否需租户过滤 | 已验证状态 | 备注 | 修复位置 |
|---------|--------------|-----------|------|---------|
| 文件夹查询 | 是 | ✅ 已验证 | 核心场景，所有查询接口已覆盖 | views.py:263, 275, 292 |
| 文件查询 | 是 | ✅ 已验证 | 核心场景，所有查询接口已覆盖 | views.py:281, 298 |
| 文件上传 | 是 | ✅ 已验证 | 通过 `create_model_instance` 自动设置租户 | views.py:616-623 |
| 秒传检查 | 是 | ✅ 已修复 | P0级别，避免跨租户秒传 | views.py:2053-2082 |
| 文件复制（同名检查） | 是 | ✅ 已修复 | P1级别，避免跨租户影响 | views.py:842-867 |
| 文件夹复制（同名检查） | 是 | ✅ 已修复 | P1级别，避免跨租户影响 | views.py:962-986 |
| 文件移动（同名检查） | 是 | ⚠️ 基于文件系统 | 物理路径隔离，已通过路径检查 | views.py:1243-1250 |
| 文件夹移动（同名检查） | 是 | ✅ 已修复 | P1级别，新增检查避免覆盖 | views.py:1118-1136 |
| 文件重命名（同名检查） | 是 | ✅ 已验证 | 已修复过，避免跨租户影响 | views.py:1486-1495 |
| 文件夹重命名（同名检查） | 是 | ✅ 已验证 | 已修复过，避免跨租户影响 | views.py:1419-1428 |
| 文件删除 | 是 | ✅ 已验证 | 通过租户过滤确保只能删除自己租户的文件 | views.py:501-502 |
| 文件夹删除 | 是 | ✅ 已验证 | 通过租户过滤确保只能删除自己租户的文件夹 | views.py:404-405 |
| 文件下载 | 是 | ✅ 已验证 | 私有空间通过租户过滤隔离 | views.py:651-652 |
| 文件预览 | 是 | ✅ 已验证 | 私有空间通过租户过滤隔离 | views.py:698-699 |
| 文件夹下载（ZIP） | 是 | ✅ 已验证 | 递归复制时应用租户过滤 | views.py:1305, 1363-1364, 1376-1377 |
| 循环引用检测 | 是 | ✅ 已验证 | P0级别，确保同一租户内检测 | views.py:1056-1061, 1154-1160 |
| 磁盘使用率查询 | 是 | ✅ 已验证 | 按租户统计磁盘使用情况 | views.py:2197-2198 |

**关键发现：**
1. 文件夹移动操作**缺少同名检查**，已在本次修复中添加（P1级别）
2. 文件移动的同名检查基于**物理文件系统**，通过路径隔离实现（私有空间按用户ID隔离目录）
3. 所有核心场景已覆盖租户过滤，无遗漏

#### 新增工具函数

**租户级同名检查工具** (`tenant_utils.py:210-244`):

```python
def check_tenant_unique_name(model, filter_kwargs, request_user, is_public=False):
    """
    检查当前租户内资源名称是否唯一

    Args:
        model: 模型类（DocumentFolder或DocumentFile）
        filter_kwargs: 基础过滤条件（如 folder_id、name）
        request_user: 当前请求用户
        is_public: 是否为公共空间

    Returns:
        tuple: (是否唯一, 匹配的资源QuerySet)
    """
    queryset = model.objects.filter(**filter_kwargs)

    # 私有空间应用租户过滤
    if not is_public:
        queryset = apply_tenant_filter(queryset, request_user)

    is_unique = queryset.count() == 0

    return is_unique, queryset
```

**使用场景：**
- 文件夹移动同名检查
- 可扩展到其他需要同名检查的场景

**公共空间权限检查工具** (`views.py:50-70`):

```python
def check_public_space_permission(request_user, resource_obj, resource_type='file', operation='操作'):
    """
    检查公共空间权限（仅管理员或创建人可操作）

    Args:
        request_user: 当前请求用户
        resource_obj: 资源对象（文件夹或文件）
        resource_type: 资源类型，'folder' 或 'file'
        operation: 操作类型，用于错误提示

    Returns:
        bool: True表示有权限，False表示无权限
    """
    # 超级管理员可以操作所有资源
    if getattr(request_user, 'is_supper', False):
        return True

    # 检查是否为创建人
    if getattr(resource_obj, 'created_by_id', None) != request_user.id:
        logger.warning(
            f'[Document] User {request_user.username} attempting to {operation}他人的公共'
            f'{resource_type} id:{resource_obj.id}'
        )
        return False

    return True
```

#### 重复代码消除

**优化前**: 10处重复的权限检查逻辑

```python
# 优化前：每处都重复以下代码
if form.is_public and not getattr(request.user, 'is_supper', False) and folder.created_by_id != request.user.id:
    logger.warning(f'[Document] User {request.user.username} attempting to delete...')
    return json_response(error='公共空间中只能删除自己创建的文件夹')
```

**优化后**: 统一使用工具函数

```python
# 优化后：简洁明了
if form.is_public and not check_public_space_permission(request.user, folder, 'folder', '删除'):
    return json_response(error='公共空间中只能删除自己创建的文件夹')
```

#### 优化统计

- **新增工具函数**: 2 个 (`check_public_space_permission`, `check_tenant_unique_name`)
- **消除重复代码**: 10 处权限检查逻辑统一
- **减少代码行数**: 约 50 行
- **提高可维护性**: 权限逻辑集中管理,易于修改和测试
- **预防同类漏洞**: 通过工具函数避免后续新增场景遗漏租户过滤

#### 优化位置

| 操作 | 原位置 | 优化后 |
|-----|--------|--------|
| 文件夹删除 | `views.py:382-384` | 使用工具函数 |
| 文件删除 | `views.py:479-481` | 使用工具函数 |
| 文件复制 | `views.py:768-771` | 使用工具函数 |
| 文件夹复制 | `views.py:891-894` | 使用工具函数 |
| 文件夹移动 | `views.py:1073-1076` | 使用工具函数 |
| 文件移动 | `views.py:1204-1207` | 使用工具函数 |
| 文件夹重命名 | `views.py:1407-1410` | 使用工具函数 |
| 文件重命名 | `views.py:1475-1478` | 使用工具函数 |

#### 代码重复清理

**P1 级别修复（高危逻辑错误）**:

10. **`_is_child_folder` 方法重复逻辑删除**
   - 删除 `FolderMoveView._is_child_folder` 中多余的循环检测代码
   - 问题: `while True` 循环中存在重复的循环检测和深度检查逻辑
   - 位置: `views.py:1170-1184` (已删除)
   - 影响: 修复逻辑错误,避免重复检查和潜在的数据库重复查询

**重复代码分析**:

```python
# 修复前: while循环中有两段重复的检查逻辑
while True:
    # 第一次检查 (行1136-1142)
    if child_id in visited_ids:
        logger.warning(...)
        return True
    visited_ids.add(child_id)

    # ... 查询数据库 ...

    # 第二次检查 (行1170-1176) ❌ 完全重复!
    child_id = child.parent_id
    if child_id in visited_ids:  # 重复检测
        logger.warning(...)
        return True
    visited_ids.add(child_id)  # 重复添加
```

```python
# 修复后: 只在循环开头检查一次
while True:
    # 唯一的检查位置
    if child_id in visited_ids:
        logger.warning(...)
        return True
    visited_ids.add(child_id)

    # ... 查询数据库 ...

    # 更新child_id,进入下一次循环
    child_id = child.parent_id  # 循环会自动检查新值
```

#### 命名规范

**变量命名**:
- ✅ 使用有意义的名称: `source_folder`, `target_parent`, `existing_file`
- ✅ 避免单字母变量: 除了循环变量 `i`, `j`, `f`

**函数命名**:
- ✅ 清晰表达意图: `_is_child_folder`, `check_public_space_permission`
- ✅ 动词开头: `get`, `check`, `build`, `create`
- ✅ 私有方法使用下划线前缀: `_delete_file`, `_copy_folder_recursive`

#### 注释规范

**函数注释**: 使用标准的三重引号文档字符串

```python
def check_public_space_permission(request_user, resource_obj, resource_type='file', operation='操作'):
    """
    检查公共空间权限（仅管理员或创建人可操作）

    Args:
        request_user: 当前请求用户
        resource_obj: 资源对象（文件夹或文件）
        resource_type: 资源类型，'folder' 或 'file'
        operation: 操作类型，用于错误提示

    Returns:
        bool: True表示有权限，False表示无权限
    """
```

**行内注释**: 解释关键逻辑

```python
# 私有空间：添加租户过滤
if not is_public:
    query = apply_tenant_filter(query, request.user)
```


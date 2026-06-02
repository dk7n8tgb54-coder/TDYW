# 资料库模块代码结构说明

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户操作界面                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 文件列表  │  │ 文件夹树  │  │ 传输列表  │  │ 上传面板  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │ API请求
┌──────────────────────────▼──────────────────────────────────┐
│                      后端API层                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 文件管理  │  │ 文件夹管理 │  │ 分片上传  │  │ 传输管理  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │ 调用
┌──────────────────────────▼──────────────────────────────────┐
│                      业务逻辑层                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 文件服务  │  │ 清理服务  │  │ 合并任务  │  │ 权限检查  │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、后端代码结构（Django）

```
spug_api/apps/document/
├── models.py              # 数据模型（文件、文件夹、传输记录）
├── urls.py                # URL路由配置
├── constants.py           # 常量定义（状态枚举、默认值）
│
├── views/                 # API视图层（处理HTTP请求）
│   ├── base.py            # 基础工具函数
│   ├── disk.py            # 网盘容量统计
│   ├── search.py          # 文件搜索
│   │
│   ├── file/              # 文件管理
│   │   ├── views.py       # 文件列表、详情
│   │   ├── copy.py        # 文件复制
│   │   ├── move.py        # 文件移动
│   │   ├── rename.py      # 文件重命名
│   │   ├── download.py    # 文件下载
│   │   └── preview.py     # 文件预览
│   │
│   ├── folder/            # 文件夹管理
│   │   ├── views.py       # 文件夹列表、创建
│   │   ├── copy.py        # 文件夹复制
│   │   ├── move.py        # 文件夹移动
│   │   ├── rename.py      # 文件夹重命名
│   │   └── download.py    # 文件夹下载（打包）
│   │
│   ├── upload/            # 分片上传
│   │   ├── chunk.py       # 接收分片
│   │   ├── merge.py       # 合并分片
│   │   ├── resume.py      # 断点续传检查
│   │   ├── status.py      # 合并状态查询
│   │   └── validators.py  # 上传验证
│   │
│   ├── transfer/          # 传输管理
│   │   ├── create.py      # 创建传输记录
│   │   ├── cancel.py      # 取消传输
│   │   ├── list.py        # 传输列表
│   │   └── status.py      # 状态更新
│   │
│   └── recycle_bin/       # 回收站
│       ├── list.py        # 回收站列表
│       ├── restore.py     # 恢复文件/文件夹
│       └── delete.py      # 彻底删除
│
├── services/              # 业务服务层（封装复杂逻辑）
│   ├── file_upload_service.py    # 文件上传服务
│   ├── folder_copy_service.py    # 文件夹复制服务
│   ├── cleanup_service.py        # 清理服务
│   ├── merge_orchestrator.py     # 合并流程编排
│   └── chunk_cleanup_service.py  # 分片清理服务
│
├── tasks/                 # Celery异步任务
│   ├── merge.py           # 分片合并任务（核心）
│   ├── batch.py           # 批量操作任务
│   └── cleanup.py         # 定时清理任务
│
└── libs/                  # 工具库
    ├── document_utils.py  # 文档相关工具
    ├── naming_utils.py    # 命名规范工具
    ├── permission_utils.py # 权限检查工具
    ├── celery_lock.py     # Redis分布式锁
    └── mime_utils.py      # 文件类型工具
```

---

## 三、前端代码结构（React）

```
spug_web/src/pages/document/
├── index.js               # 资料库主页面
├── index.module.less      # 主页面样式
│
├── Explorer/              # 文件浏览器（核心组件）
│   ├── index.js           # 文件列表展示
│   ├── utils.js           # 文件操作工具函数
│   └── components/        # 子组件
│
├── FolderTree.js          # 文件夹树形导航
├── UploadPanel.js         # 上传面板
├── PreviewModal.js        # 文件预览弹窗
│
├── components/            # 公共组件
│   ├── ContextMenu.js     # 右键菜单
│   ├── FileTypeIcon.js    # 文件类型图标
│   ├── SearchBox.js       # 搜索框
│   ├── TransferItem.js    # 传输列表项
│   └── TransferList.js    # 传输列表
│
├── recycle-bin/           # 回收站页面
│   ├── index.js           # 回收站主页面
│   ├── service.js         # 回收站API调用
│   └── stores/            # 回收站状态管理
│
├── stores/                # 状态管理（MobX）
│   ├── index.js           # 状态统一导出
│   ├── upload/            # 上传状态管理
│   └── navigation/        # 导航状态管理
│
└── utils/                 # 工具函数
    ├── upload-utils.js    # 上传相关工具
    └── keyUtils.js        # 键盘快捷键
```

---

## 四、核心流程图解

### 1. 大文件分片上传流程

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  前端选择 │────▶│ 创建传输 │────▶│ 循环上传 │────▶│ 请求合并 │
│   文件   │     │   记录   │     │   分片   │     │   分片   │
└──────────┘     └──────────┘     └──────────┘     └────┬─────┘
                                                        │
                              ┌─────────────────────────┘
                              ▼
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ 合并完成 │◀────│ Celery   │◀────│ 后端接收 │◀────│ 提交任务 │
│ 通知前端 │     │ 执行任务  │     │ 合并请求 │     │ 到队列   │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
```

**说明**：
- 大文件被切成多个小块（默认5MB/块）
- 每个分片独立上传，支持断点续传
- 全部分片上传完成后，后端异步合并
- Celery任务负责实际的文件合并操作

---

### 2. 三层命名体系

```
用户看到的名字              数据库存储的名字           磁盘上的文件名
┌──────────────┐           ┌──────────────┐          ┌──────────────┐
│              │           │              │          │              │
│  测试文档.pdf  │  ──────▶  │  测试文档.pdf  │  ────▶  │ 测试文档_123 │
│              │           │   (logical)  │          │  _45678.pdf  │
│ (display_name)│           │              │          │ (physical)   │
└──────────────┘           └──────────────┘          └──────────────┘
        │                          │                       │
        └──────────────────────────┴───────────────────────┘
                           解决重名问题
```

**说明**：
- `display_name`：用户看到的原始文件名
- `logical_name`：数据库存储的逻辑名（可能添加序号区分）
- `physical_name`：磁盘实际存储名（添加时间戳和随机数，确保唯一）

---

## 五、关键概念速查

| 概念 | 说明 |
|------|------|
| **公共空间** | 所有租户共享的文件空间 |
| **私有空间** | 仅当前租户可见的文件空间 |
| **传输记录** | 记录大文件上传进度和状态 |
| **分片** | 大文件被切分成的小块 |
| **Celery** | 异步任务队列，处理耗时操作（如合并） |
| **Redis锁** | 防止多线程/多进程同时操作同一文件 |
| **回收站** | 逻辑删除，可恢复 |

---

## 六、租户隔离说明

```
租户A的空间                    租户B的空间
┌──────────────┐              ┌──────────────┐
│  我的文档/    │              │  项目资料/    │
│  ├── a.pdf   │   ❌隔离❌   │  ├── x.pdf   │
│  └── b.doc   │  ──────────  │  └── y.doc   │
└──────────────┘              └──────────────┘
        │                              │
        └──────────┐    ┌──────────────┘
                   ▼    ▼
              ┌──────────────┐
              │   公共空间    │  ✅ 共享
              │  ├── 公告.pdf│
              │  └── 手册.doc│
              └──────────────┘
```

**说明**：每个租户只能访问自己的私有空间 + 公共空间，无法访问其他租户的私有空间。

---

## 七、ER 图（实体关系图）

### 7.1 模型关系总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         资料库模块 ER 图                              │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │       User       │
    │     (用户表)      │
    ├──────────────────┤
    │ PK id            │
    │    username      │
    │    tenant_id     │
    └────────┬─────────┘
             │ 1:N
             │
    ┌────────▼─────────┐       ┌──────────────────┐
    │ DocumentFolder   │       │  DocumentFile    │
    │   (文件夹表)      │◄──────┤    (文件表)       │
    ├──────────────────┤  1:N  ├──────────────────┤
    │ PK id            │       │ PK id            │
    │    name          │       │    name          │
    │ FK parent_id     │       │    display_name  │
    │    tenant_id     │       │    physical_name │
    │    is_deleted    │       │ FK folder_id     │
    │    created_by    │       │    file_size     │
    └──────────────────┘       │    file_path     │
                               │    tenant_id     │
                               │    is_deleted    │
                               └──────────────────┘
                                        │
                                        │ N:1
                                        │
                               ┌────────▼─────────┐
                               │ DocumentTransfer │
                               │   (传输记录表)    │
                               ├──────────────────┤
                               │ PK id            │
                               │    file_name     │
                               │    file_hash     │
                               │    status        │
                               │ FK user_id       │
                               │    tenant_id     │
                               │    total_chunks  │
                               │    celery_task_id│
                               └──────────────────┘
```

**图例说明**：
- `PK`：主键（Primary Key）
- `FK`：外键（Foreign Key），建立表之间的关联
- `1:N`：一对多关系（如一个文件夹可以有多个文件）
- `N:1`：多对一关系（如多个传输记录对应一个用户）

### 7.2 模型结构详解

#### 7.2.1 私有空间模型

```
┌─────────────────────────────────────────────────────────────────┐
│                    DocumentFolderPrivate                         │
│                      (私有文件夹表)                               │
├─────────────────────────────────────────────────────────────────┤
│ 字段名          │ 类型          │ 说明                          │
├─────────────────┼───────────────┼───────────────────────────────┤
│ id              │ AutoField     │ 主键，自增                     │
│ name            │ Char(200)     │ 文件夹名称                     │
│ parent_id       │ ForeignKey    │ 父文件夹ID（自关联，树形结构）   │
│ created_by_id   │ ForeignKey    │ 创建人ID（关联User表）          │
│ tenant_id       │ Char(50)      │ 租户标识（租户隔离字段）         │
│ is_deleted      │ Boolean       │ 软删除标记                     │
│ deleted_at      │ DateTime      │ 删除时间                       │
│ created_at      │ DateTime      │ 创建时间                       │
│ updated_at      │ DateTime      │ 更新时间                       │
└─────────────────┴───────────────┴───────────────────────────────┘
                              │
                              │ 1:N
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DocumentFilePrivate                           │
│                       (私有文件表)                                │
├─────────────────────────────────────────────────────────────────┤
│ 字段名          │ 类型          │ 说明                          │
├─────────────────┼───────────────┼───────────────────────────────┤
│ id              │ AutoField     │ 主键，自增                     │
│ physical_name   │ Char(100)     │ 物理文件名（磁盘存储用）         │
│ name            │ Char(100)     │ 逻辑文件名（API交互用）          │
│ display_name    │ Char(128)     │ 显示文件名（用户看到）           │
│ folder_id       │ ForeignKey    │ 所属文件夹ID                   │
│ file_path       │ Char(500)     │ 完整存储路径                   │
│ file_size       │ BigInteger    │ 文件大小（字节）                │
│ file_type       │ Char(100)     │ 文件MIME类型                   │
│ created_by_id   │ ForeignKey    │ 上传人ID                       │
│ tenant_id       │ Char(50)      │ 租户标识                       │
│ is_deleted      │ Boolean       │ 软删除标记                     │
│ is_pending_clean│ Boolean       │ 待清理标记（删除失败时）         │
│ created_at      │ DateTime      │ 上传时间                       │
│ updated_at      │ DateTime      │ 更新时间                       │
└─────────────────┴───────────────┴───────────────────────────────┘
```

#### 7.2.2 公共空间模型

公共空间模型与私有空间结构相同，只是**没有 tenant_id 字段**（所有人共享）。

```
DocumentFolderPublic  ──►  公共文件夹表
DocumentFilePublic     ──►  公共文件表
```

#### 7.2.3 传输记录模型

```
┌─────────────────────────────────────────────────────────────────┐
│                    DocumentTransfer                              │
│                      (传输记录表)                                 │
├─────────────────────────────────────────────────────────────────┤
│ 字段名            │ 类型          │ 说明                        │
├───────────────────┼───────────────┼─────────────────────────────┤
│ id                │ AutoField     │ 主键，自增                   │
│ tenant_id         │ Char(50)      │ 租户标识（带索引）            │
│ user_id           │ ForeignKey    │ 用户ID                       │
│ transfer_type     │ Char(20)      │ 传输类型：UPLOAD/DOWNLOAD    │
│ status            │ Char(20)      │ 状态：PENDING/COMPLETED等    │
│ file_name         │ Char(255)     │ 文件名                       │
│ file_size         │ BigInteger    │ 文件大小                     │
│ file_hash         │ Char(100)     │ 文件MD5哈希（带索引）         │
│ folder_id         │ Integer       │ 目标文件夹ID                 │
│ is_public         │ Boolean       │ 是否公共空间                 │
│ total_chunks      │ Integer       │ 总分片数                     │
│ uploaded_chunks   │ Integer       │ 已上传分片数                 │
│ progress          │ Integer       │ 进度百分比                   │
│ celery_task_id    │ Char(100)     │ Celery任务ID（带索引）        │
│ created_at        │ DateTime      │ 创建时间（带索引）            │
│ completed_at      │ DateTime      │ 完成时间                     │
└───────────────────┴───────────────┴─────────────────────────────┘
```

### 7.3 关键设计说明

#### 树形结构实现
采用**邻接表模型**（Parent ID 方式）：
```python
parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)
```
- **优点**：实现简单，插入/移动性能高
- **缺点**：递归查询深度受限（默认1000层）
- **适用性**：企业文件层级通常<10层，完全够用

#### 三层命名体系
```
用户上传: "测试文档.pdf"
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│  display_name   │────►│  测试文档.pdf     │  (用户看到)
│  (显示名)        │     │                  │
└─────────────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│     name        │────►│  测试文档.pdf     │  (API交互)
│  (逻辑名)        │     │                  │
└─────────────────┘     └──────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────────────┐
│  physical_name  │────►│ 测试文档_1699123456789_  │  (磁盘存储)
│  (物理名)        │     │ a1b2c3.pdf               │
└─────────────────┘     └──────────────────────────┘
```

---

## 八、数据库索引检查报告

### 8.1 索引检查方法

```bash
# 方法1: 查看 Django 生成的 SQL
python manage.py sqlmigrate document 0001_initial

# 方法2: 直接在数据库中查看
# MySQL:
SHOW INDEX FROM spug_document_folder_private;

# PostgreSQL:
\d spug_document_folder_private
```

### 8.2 各表索引现状

#### DocumentFolderPrivate / DocumentFolderPublic

| 字段 | 索引类型 | 状态 | 说明 |
|------|---------|------|------|
| `id` | 主键索引 | ✅ 自动创建 | 默认主键 |
| `parent_id` | 外键索引 | ✅ 自动创建 | ForeignKey 默认索引 |
| `tenant_id` | 普通索引 | ❌ **缺失** | 高频过滤字段 |
| `is_deleted` | 普通索引 | ❌ **缺失** | 软删除过滤 |

**建议添加的索引**：
```python
class Meta:
    indexes = [
        models.Index(fields=['tenant_id', 'is_deleted', 'parent_id'], 
                     name='idx_folder_tenant_parent'),
    ]
```

#### DocumentFilePrivate / DocumentFilePublic

| 字段 | 索引类型 | 状态 | 说明 |
|------|---------|------|------|
| `id` | 主键索引 | ✅ 自动创建 | 默认主键 |
| `folder_id` | 外键索引 | ✅ 自动创建 | ForeignKey 默认索引 |
| `tenant_id` | 普通索引 | ❌ **缺失** | 高频过滤字段 |
| `is_deleted` | 普通索引 | ❌ **缺失** | 软删除过滤 |
| `name` | 普通索引 | ❌ **缺失** | 搜索优化 |

**建议添加的索引**：
```python
class Meta:
    indexes = [
        models.Index(fields=['tenant_id', 'is_deleted', 'folder_id'], 
                     name='idx_file_tenant_folder'),
        models.Index(fields=['name'], 
                     name='idx_file_name'),  # 文件名搜索
    ]
```

#### DocumentTransfer（✅ 索引已优化）

| 字段 | 索引类型 | 状态 | 说明 |
|------|---------|------|------|
| `id` | 主键索引 | ✅ 自动创建 | 默认主键 |
| `tenant_id` | 普通索引 | ✅ 已添加 | `db_index=True` |
| `status` | 普通索引 | ✅ 已添加 | `db_index=True` |
| `file_hash` | 普通索引 | ✅ 已添加 | `db_index=True` |
| `created_at` | 普通索引 | ✅ 已添加 | `db_index=True` |
| `celery_task_id` | 普通索引 | ✅ 已添加 | `db_index=True` |
| `tenant_id + user` | 复合索引 | ✅ 已添加 | Meta.indexes |
| `tenant_id + status` | 复合索引 | ✅ 已添加 | Meta.indexes |
| `tenant_id + file_hash` | 复合索引 | ✅ 已添加 | Meta.indexes |

**评价**：传输记录表索引已充分优化 👍

### 8.3 索引优化建议汇总

| 优先级 | 表名 | 建议添加索引 | 预期收益 |
|--------|------|-------------|---------|
| **P1** | DocumentFolderPrivate | `(tenant_id, is_deleted, parent_id)` | 文件夹列表查询加速 |
| **P1** | DocumentFolderPublic | `(is_deleted, parent_id)` | 公共文件夹查询加速 |
| **P1** | DocumentFilePrivate | `(tenant_id, is_deleted, folder_id)` | 文件列表查询加速 |
| **P1** | DocumentFilePublic | `(is_deleted, folder_id)` | 公共文件查询加速 |
| **P2** | DocumentFilePrivate | `(name)` | 文件名搜索加速 |
| **P2** | DocumentFilePublic | `(name)` | 文件名搜索加速 |

### 8.4 索引优化代码实现

如需添加缺失索引，修改 `models.py`：

```python
class DocumentFolderPrivate(models.Model):
    # ... 现有字段 ...
    
    class Meta:
        db_table = 'spug_document_folder_private'
        verbose_name = '文档文件夹(私有)'
        ordering = ['-created_at']
        # 新增复合索引
        indexes = [
            models.Index(
                fields=['tenant_id', 'is_deleted', 'parent_id'], 
                name='idx_folder_private_tenant_parent'
            ),
        ]

class DocumentFilePrivate(models.Model):
    # ... 现有字段 ...
    
    class Meta:
        db_table = 'spug_document_file_private'
        verbose_name = '文档文件(私有)'
        ordering = ['-created_at']
        # 新增复合索引
        indexes = [
            models.Index(
                fields=['tenant_id', 'is_deleted', 'folder_id'], 
                name='idx_file_private_tenant_folder'
            ),
            models.Index(
                fields=['name'], 
                name='idx_file_private_name'
            ),
        ]
```

**注意**：添加索引后需要执行迁移：
```bash
python manage.py makemigrations document
python manage.py migrate
```

### 8.5 索引检查总结

| 评估项 | 状态 | 说明 |
|--------|------|------|
| DocumentTransfer | ✅ 良好 | 索引已充分优化 |
| DocumentFolder | ⚠️ 需优化 | 缺少 tenant_id + is_deleted 复合索引 |
| DocumentFile | ⚠️ 需优化 | 缺少 tenant_id + is_deleted + folder_id 复合索引 |

**总体评价**：传输记录表索引完善，文件夹和文件表需要补充复合索引以优化列表查询性能。

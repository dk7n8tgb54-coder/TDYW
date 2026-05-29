# spug_api/apps/exec 文件夹说明

`exec` 文件夹是 **运行管理模块** 的后端代码，负责处理所有与运行相关的业务逻辑。

## 文件结构

```
exec/
├── __init__.py              # Python包初始化文件
├── models.py               # 数据模型定义（14.88 KB）
├── views.py                # 视图控制器（28.35 KB）
├── urls.py                # URL路由配置
├── executors.py           # SSH执行器（2.74 KB）
├── management/            # Django管理命令
│   └── commands/
│       └── runworker.py  # Worker进程启动命令
└── migrations/           # 数据库迁移文件
    └── 0002_add_recorder_to_runlog.py
```

## 文件详解

### 1. `__init__.py`
**作用**: Python包初始化文件
- 标识此目录为一个Python包
- 文件为空，仅包含版权声明

### 2. `models.py` (14.88 KB)
**作用**: 定义所有运行管理相关的数据表模型

**包含的模型**:
- `RunLog` - 运行日志表
- `FaultRecord` - 故障记录表
- `FaultPart` - 故障件表
- `Interference` - 干扰信息表
- `UpgradeRecord` - 升级记录表
- `DutyRecord` - 值班记录表
- `HandoverRecord` - 交接班记录表
- `ScheduleStaff` - 排班人员表
- `ScheduleShift` - 班次规则表
- `ScheduleShiftTime` - 班次时间配置表
- `Schedule` - 排班表
- `ScheduleSwap` - 换班记录表
- `ScheduleSubstitute` - 替班记录表

每个模型包含:
- 字段定义（如 `name`, `status`, `created_at` 等）
- `__str__()` 方法（用于后台显示）
- `Meta` 类（配置表名、排序等）
- 类方法（如查询方法、统计方法等）

### 3. `views.py` (28.35 KB)
**作用**: 处理HTTP请求的视图控制器

**包含的视图类**:
- `RunLogView` - 运行日志接口
- `FaultRecordView` - 故障记录接口
- `FaultPartView` - 故障件管理接口
- `InterferenceView` - 干扰信息接口
- `UpgradeRecordView` - 升级记录接口
- `DutyRecordView` - 值班记录接口
- `HandoverRecordView` - 交接班接口
- `ScheduleView` - 排班管理接口
- `ScheduleStaffView` - 排班人员接口
- `ScheduleShiftView` - 班次规则接口
- `ScheduleSwapView` - 换班记录接口
- `ScheduleSubstituteView` - 替班记录接口

每个视图类包含:
- `get()` - 处理GET请求（查询数据）
- `post()` - 处理POST请求（创建数据）
- `put()` - 处理PUT请求（更新数据）
- `delete()` - 处理DELETE请求（删除数据）
- 权限检查（使用 `@permission` 装饰器）
- 数据验证和业务逻辑

### 4. `urls.py` (934 B)
**作用**: 定义URL路由规则，将HTTP请求映射到对应的视图

**路由配置**:
```python
urlpatterns = [
    url(r'runlog/$', RunLogView.as_view()),                    # /api/exec/runlog/
    url(r'faultrecord/$', FaultRecordView.as_view()),          # /api/exec/faultrecord/
    url(r'faultpart/$', FaultPartView.as_view()),              # /api/exec/faultpart/
    url(r'interference/$', InterferenceView.as_view()),         # /api/exec/interference/
    url(r'upgrade/$', UpgradeRecordView.as_view()),             # /api/exec/upgrade/
    url(r'duty/$', DutyRecordView.as_view()),                   # /api/exec/duty/
    url(r'handover/$', HandoverRecordView.as_view()),          # /api/exec/handover/
    url(r'schedule/$', ScheduleView.as_view()),                 # /api/exec/schedule/
    url(r'schedule/staff/$', ScheduleStaffView.as_view()),      # /api/exec/schedule/staff/
    url(r'schedule/shift/$', ScheduleShiftView.as_view()),      # /api/exec/schedule/shift/
    url(r'schedule/swap/$', ScheduleSwapView.as_view()),        # /api/exec/schedule/swap/
    url(r'schedule/substitute/$', ScheduleSubstituteView.as_view()), # /api/exec/schedule/substitute/
    url(r'schedule/auto/$', ScheduleView.as_view()),            # /api/exec/schedule/auto/
]
```

### 5. `executors.py` (2.74 KB)
**作用**: SSH命令执行器，用于远程执行命令

**主要功能**:
- `exec_worker_handler(job)` - Worker任务处理器，从Redis队列获取任务
- `Job` 类 - SSH任务执行器
  - 连接到远程服务器
  - 执行命令
  - 将结果发送到Redis频道（实时反馈）
  - 支持环境变量注入
  - 支持多种解释器（bash、python）

**使用场景**:
- 运行日志需要远程执行命令
- 任务调度需要执行自动化脚本
- 其他需要SSH执行的场景

### 6. `management/commands/runworker.py` (3.23 KB)
**作用**: Django管理命令，启动Worker进程

**功能**:
- 从Redis队列中获取执行任务
- 调用 `executors.py` 中的执行器处理任务
- 作为独立的后台进程运行

**启动方式**:
```bash
python manage.py runworker
```

**运行场景**:
- 在Docker容器中作为守护进程运行
- 处理异步执行任务
- 避免阻塞主Web进程

### 7. `migrations/0002_add_recorder_to_runlog.py` (395 B)
**作用**: 数据库迁移文件

**功能**:
- 为 `RunLog` 表添加 `recorder` 字段
- 记录执行操作的记录人

**迁移操作**:
```bash
python manage.py migrate exec
```

## 工作流程

### 典型的请求处理流程

```
1. 前端发送HTTP请求
   ↓
2. Django路由系统 (urls.py)
   ↓
3. 视图控制器处理 (views.py)
   ↓
4. 操作数据模型 (models.py)
   ↓
5. 返回JSON响应给前端
```

### 执行命令流程

```
1. 前端发起执行请求
   ↓
2. 视图创建任务并推入Redis队列
   ↓
3. Worker进程 (runworker.py) 从队列获取任务
   ↓
4. 执行器 (executors.py) 通过SSH执行命令
   ↓
5. 实时结果推送到Redis频道
   ↓
6. 前端通过WebSocket接收实时输出
```

## 与前端的对应关系

| 前端页面 | 后端路由 | 视图类 | 模型 |
|---------|---------|--------|------|
| 运行日志 | /api/exec/runlog/ | RunLogView | RunLog |
| 干扰信息统计 | /api/exec/interference/ | InterferenceView | Interference |
| 升级记录 | /api/exec/upgrade/ | UpgradeRecordView | UpgradeRecord |
| 统计报表 | /api/exec/upgrade/ | UpgradeRecordView | UpgradeRecord |
| 值班记录 | /api/exec/duty/ | DutyRecordView | DutyRecord |
| 交接班 | /api/exec/handover/ | HandoverRecordView | HandoverRecord |
| 排班日历 | /api/exec/schedule/ | ScheduleView | Schedule |
| 故障处置记录 | /api/exec/faultrecord/ | FaultRecordView | FaultRecord |
| 故障件管理 | /api/exec/faultpart/ | FaultPartView | FaultPart |

## 扩展说明

### 添加新功能

如果需要添加新的运行管理功能：

1. 在 `models.py` 中定义新的数据模型
2. 在 `views.py` 中创建视图类
3. 在 `urls.py` 中添加路由
4. 生成数据库迁移文件
5. 执行迁移

### 注意事项

1. **权限控制**: 所有视图都应使用 `@permission` 装饰器进行权限检查
2. **数据验证**: 在视图的 `post()` 和 `put()` 方法中验证用户输入
3. **错误处理**: 使用Django的异常处理机制，返回友好的错误信息
4. **日志记录**: 重要操作应记录日志，便于排查问题

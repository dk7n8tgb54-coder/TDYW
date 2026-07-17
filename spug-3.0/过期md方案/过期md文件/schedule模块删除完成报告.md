# Schedule模块（定时任务计划）删除完成报告

## 概述
本报告详细记录了 `apps/schedule` 模块（定时任务计划模块）的完整删除过程。

**注意**：本项目中有两个"schedule"相关功能：
- **apps/schedule** - 定时任务计划模块（已删除，本次删除目标）
- **apps/exec/schedule** - 排班管理模块（保留，exec模块内的排班功能）

## 删除清单

### 1. 后端代码删除
- ✅ `spug_api/apps/schedule/` - 整个schedule模块目录
  - `__init__.py`
  - `models.py` - Task, History模型定义
  - `views.py` - Schedule, HistoryView视图及相关API
  - `urls.py` - schedule路由配置
  - `executors.py` - 任务执行器
  - `scheduler.py` - APScheduler调度器
  - `utils.py` - 失败通知工具函数
  - `builtin.py` - 内置定时任务（数据清理）
  - `management/commands/runscheduler.py` - schedule管理命令

### 2. 配置文件修改
- ✅ `spug_api/spug/settings.py`
  - 从INSTALLED_APPS中移除 `'apps.schedule'`
  - 删除配置项：
    - `SCHEDULE_KEY = 'spug:schedule'`
    - `SCHEDULE_WORKER_KEY = 'spug:schedule:worker'`

- ✅ `spug_api/spug/urls.py`
  - 移除路由：`path('schedule/', include('apps.schedule.urls'))`

### 3. 相关引用清理
- ✅ `spug_api/apps/exec/views.py`
  - 移除 `@auth` 装饰器中的 `schedule.schedule.add|schedule.schedule.edit|monitor.monitor.add|monitor.monitor.edit` 权限码
  - 保留 `exec.template.view|exec.task.do` 权限码

- ✅ `spug_api/apps/exec/management/commands/runworker.py`
  - 移除导入：`from apps.schedule.executors import schedule_worker_handler`
  - 移除常量：`SCHEDULE_WORKER_KEY = settings.SCHEDULE_WORKER_KEY`
  - 移除 `queue_monitor()` 消息中的"任务计划"字样
  - 移除 `run()` 中的 SCHEDULE_WORKER_KEY 相关处理逻辑
  - 简化 blpop 队列列表，只保留 EXEC_WORKER_KEY

- ✅ `spug_api/apps/home/views.py`
  - 移除导入：`from apps.schedule.models import Task`
  - 移除 `get_statistic()` 函数中的 `task: Task.objects.count()`

### 4. 工具脚本删除
- ✅ `spug_api/tools/start-scheduler.sh` - 定时任务调度服务启动脚本

### 5. 前端代码检查
- ✅ 前端无定时任务计划相关引用（排班管理功能使用的是 `exec.schedule` 权限码，属于exec模块，已保留）

## 修改详情

### settings.py修改
```python
# 删除前
INSTALLED_APPS = [
    'apps.account',
    'apps.setting',
    'apps.exec',
    'apps.schedule',  # 删除
    'apps.config',
    # ...
]

# 删除后
INSTALLED_APPS = [
    'apps.account',
    'apps.setting',
    'apps.exec',
    # ...
]
```

```python
# 删除前
TOKEN_TTL = 8 * 3600
SCHEDULE_KEY = 'spug:schedule'  # 删除
SCHEDULE_WORKER_KEY = 'spug:schedule:worker'  # 删除
EXEC_WORKER_KEY = 'spug:exec:worker'

# 删除后
TOKEN_TTL = 8 * 3600
EXEC_WORKER_KEY = 'spug:exec:worker'
```

### urls.py修改
```python
# 删除前
urlpatterns = [
    path('account/', include('apps.account.urls')),
    path('exec/', include('apps.exec.urls')),
    path('schedule/', include('apps.schedule.urls')),  # 删除
    # ...
]

# 删除后
urlpatterns = [
    path('account/', include('apps.account.urls')),
    path('exec/', include('apps.exec.urls')),
    # ...
]
```

### exec/views.py修改
```python
# 删除前
class TemplateView(View):
    @auth('exec.template.view|exec.task.do|schedule.schedule.add|schedule.schedule.edit|\
    monitor.monitor.add|monitor.monitor.edit')
    def get(self, request):
        # ...

# 删除后
class TemplateView(View):
    @auth('exec.template.view|exec.task.do')
    def get(self, request):
        # ...
```

### runworker.py修改
```python
# 删除前
from apps.schedule.executors import schedule_worker_handler
# ...
EXEC_WORKER_KEY = settings.EXEC_WORKER_KEY
SCHEDULE_WORKER_KEY = settings.SCHEDULE_WORKER_KEY
# ...
self.rds.delete(EXEC_WORKER_KEY, SCHEDULE_WORKER_KEY)
# ...
key, job = self.rds.blpop([EXEC_WORKER_KEY, SCHEDULE_WORKER_KEY])
# ...
if key == SCHEDULE_WORKER_KEY:
    future = self._executor.submit(schedule_worker_handler, job)

# 删除后
EXEC_WORKER_KEY = settings.EXEC_WORKER_KEY
# ...
self.rds.delete(EXEC_WORKER_KEY)
# ...
key, job = self.rds.blpop(EXEC_WORKER_KEY)
# ...
if key == EXEC_WORKER_KEY:
    future = self._executor.submit(exec_worker_handler, job)
```

## Schedule模块功能概述（已删除）

### 核心模型
1. **Task** - 定时任务
   - 支持的触发器类型：
     - date（一次性）
     - calendarinterval（日历间隔）
     - cron（UNIX cron表达式）
     - interval（普通间隔）
   - 任务参数：
     - 执行解释器（sh, python等）
     - 执行命令
     - 目标主机
     - 失败通知配置

2. **History** - 任务执行历史
   - 执行状态（执行中、成功、失败）
   - 执行时间
   - 输出内容

### 核心组件
1. **Scheduler** - 使用APScheduler进行定时调度
2. **Executors** - 执行定时任务
3. **Worker** - 异步执行任务
4. **Builtin Tasks** - 内置定时任务
   - 每日数据清理（30天前历史、7天前通知等）
   - 每分钟轮询任务

### 数据库表
- `tasks` - 定时任务配置表
- `task_histories` - 任务执行历史表

## 排班管理模块（保留）

**重要说明**：排班管理功能位于 `apps/exec/schedule`，属于exec模块，**本次未删除**。

排班管理相关文件（保留）：
- `spug_api/apps/exec/models.py` - 包含排班相关模型
- `spug_api/apps/exec/urls.py` - 排班相关路由
- `spug_web/src/pages/exec/schedule/` - 排班管理前端页面
  - `CalendarView.js` - 排班日历
  - `BasisView.js` - 基础数据
  - `SwapList.js` - 换班管理
  - `SubstituteList.js` - 替班管理
  - `StaffList.js` - 人员管理
  - `ShiftList.js` - 班次管理

排班管理使用的权限码（保留）：
- `schedule.schedule.view` - 排班查看
- `schedule.staff.view` - 人员查看
- `schedule.shift.view` - 班次查看

这些权限码虽然在命名上与已删除的定时任务计划模块相似，但它们实际上是排班管理模块的权限，完全独立于定时任务计划功能。

## 影响分析

### 移除的功能
1. 定时任务计划功能（一次性、cron、间隔调度）
2. 定时任务执行历史查看
3. 定时任务失败通知
4. 内置数据清理定时任务
5. 仪表盘中的任务统计

### 保留的功能
- 排班管理功能（exec模块内）
- 执行模块（exec）
- 其他所有功能模块

### 兼容性说明
- ✅ 前端无定时任务计划相关引用
- ✅ 排班管理功能完全保留
- ✅ 数据库表 `tasks`、`task_histories` 可手动清理（如需要）
- ✅ Redis中的调度队列会自动清理（worker启动时清空）

## 验证清单

- [x] 所有schedule模块文件已删除
- [x] settings.py配置已清理
- [x] urls.py路由已移除
- [x] 其他模块中的schedule引用已清理
- [x] 前端无相关引用
- [x] 工具脚本已删除
- [x] 排班管理功能已验证保留

## 总结

`apps/schedule` 定时任务计划模块已完全删除，包括：
- 后端代码（8个Python文件）
- 配置项（2个Redis key配置）
- URL路由（1个）
- 相关引用（exec、home模块）
- 工具脚本（1个）

**排班管理功能（apps/exec/schedule）已完整保留**，包括前端页面、后端API和权限配置。

删除过程已完成，系统不再包含定时任务计划功能。排班管理功能正常运行，无依赖问题。

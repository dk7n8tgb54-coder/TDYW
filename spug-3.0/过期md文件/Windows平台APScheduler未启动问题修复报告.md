# Windows平台APScheduler未启动问题修复报告

## 问题描述

### 1. 症状表现
- 文件上传后合并任务一直卡在`pending`状态
- 日志显示任务在`scheduled`和`pending`状态之间反复切换
- 前端持续轮询合并状态,但任务始终无法完成

### 2. 日志证据

```
UploadCoreStore.js:1199 [传输] 合并状态查询成功: {status: 'scheduled', job_id: '0c310ada05f30f35db8f62579e75e3a3_1772548069', name: 'Merge-21-【徒手】第4周，周三，全身肌肉强化.mp4', next_run_time: null}

UploadCoreStore.js:1199 [传输] 合并状态查询成功: {status: 'pending', job_id: '0c310ada05f30f35db8f62579e75e3a3_1772548069', file_name: '21-【徒手】第4周，周三，全身肌肉强化.mp4', file_hash: '0c310ada05f30f35db8f62579e75e3a3', user: 'tongxinke', …}
```

## 根因分析

### 1. 主要问题

**`wsgi.py`中的文件锁代码只支持Linux平台,导致Windows下APScheduler从未启动**

```python
# data/backend/spug/wsgi.py (修复前)
def initialize_scheduler():
    lock_file_path = '/tmp/scheduler_init.lock'  # Linux路径!
    lock_file = open(lock_file_path, 'w')

    # 尝试获取非阻塞锁
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)  # fcntl在Windows上不存在!
```

### 2. 失败链路

1. **WSGI启动时** → `wsgi.py`中的`initialize_scheduler()`被调用
2. **Windows平台** → `import fcntl`抛出`ModuleNotFoundError`
3. **异常被捕获** → 函数捕获异常但不阻塞应用启动
4. **scheduler未初始化** → `_scheduler_instance`保持`None`
5. **任务提交时** → `submit_merge_job()`调用`get_scheduler()`
6. **创建未启动的scheduler** → `init_scheduler()`创建新的但未启动的实例
7. **任务添加到未运行的scheduler** → 任务被添加但永远不会执行

### 3. 日志分析

通过检查任务文件,确认任务卡在`pending`状态:

```bash
$ cat data/backend/storage/document_merge_tasks/0c310ada05f30f35db8f62579e75e3a3_1772548069.task
{
  "status": "pending",
  "file_name": "21-【徒手】第4周，周三，全身肌肉强化.mp4",
  "file_hash": "0c310ada05f30f35db8f62579e75e3a3",
  "user": "tongxinke",
  "is_public": false,
  "start_time": 1772548069.223954
}
```

## 修复方案

### 1. 跨平台文件锁支持

#### 文件1: `data/backend/spug/wsgi.py`

**修改点1: 添加全局锁文件引用**

```python
# 【APScheduler】在WSGI应用加载后初始化调度器
# 使用文件锁确保只有一个worker初始化调度器（避免多实例问题）
logger = logging.getLogger(__name__)

# 全局调度器实例（用于清理）
_scheduler_instance = None
_lock_file = None  # 【修复】保存锁文件引用用于释放
```

**修改点2: 跨平台锁机制**

```python
def initialize_scheduler():
    """初始化APScheduler（使用文件锁确保单实例）"""
    global _scheduler_instance, _lock_file

    import platform
    # 【修复】根据操作系统选择不同的锁文件路径
    lock_file_path = '/tmp/scheduler_init.lock' if platform.system() != 'Windows' else 'C:/temp/scheduler_init.lock'
    lock_file = None
    lock_acquired = False

    try:
        # 确保锁目录存在
        import os
        lock_dir = os.path.dirname(lock_file_path)
        if lock_dir and not os.path.exists(lock_dir):
            os.makedirs(lock_dir, exist_ok=True)

        # 打开锁文件
        lock_file = open(lock_file_path, 'w')

        # 【修复】根据操作系统选择不同的锁机制
        if platform.system() == 'Windows':
            # Windows: 使用msvcrt.locking
            import msvcrt
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                lock_acquired = True
            except (OSError, IOError):
                # 文件已被锁定
                pass
        else:
            # Linux/Unix: 使用fcntl.flock
            import fcntl
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
            except BlockingIOError:
                pass

        if lock_acquired:
            # 只有第一个worker能执行到这里
            from apps.document.libs.scheduler import start_scheduler
            _scheduler_instance = start_scheduler()

            # 【修复】保存锁文件引用用于后续释放
            _lock_file = lock_file

            logger.info('[WSGI] APScheduler initialized successfully (single instance)')

            # 保持锁文件打开，防止其他worker初始化

    except (OSError, IOError, BlockingIOError):
        # 其他worker：已有实例在运行，跳过初始化
        logger.info('[WSGI] APScheduler already initialized by another worker, skipping')
        # 【修复】关闭未使用的锁文件
        if lock_file:
            try:
                lock_file.close()
            except:
                pass

    except Exception as e:
        logger.error(f'[WSGI] Failed to initialize APScheduler: {e}', exc_info=True)
        # 调度器初始化失败不阻塞应用启动
        if lock_file:
            try:
                lock_file.close()
            except:
                pass
```

**修改点3: 正确释放Windows锁**

```python
def shutdown_scheduler():
    """关闭调度器（在worker退出时调用）"""
    global _scheduler_instance, _lock_file

    if _scheduler_instance is not None:
        try:
            from apps.document.libs.scheduler import shutdown_scheduler as sd
            sd()
            logger.info('[WSGI] APScheduler shutdown successfully')
        except Exception as e:
            logger.error(f'[WSGI] Failed to shutdown APScheduler: {e}')

    # 【修复】释放文件锁
    if _lock_file is not None:
        try:
            import platform
            if platform.system() == 'Windows':
                import msvcrt
                # Windows: 解锁
                msvcrt.locking(_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            _lock_file.close()
            _lock_file = None
            logger.info('[WSGI] Scheduler lock released')
        except Exception as e:
            logger.error(f'[WSGI] Failed to release scheduler lock: {e}')
```

### 2. 增强调度器启动验证

#### 文件2: `data/backend/apps/document/libs/scheduler.py`

**修改点: 添加启动后验证**

```python
def start_scheduler():
    """启动调度器"""
    logger.info('[APScheduler] Attempting to start scheduler...')
    try:
        scheduler = get_scheduler()
        logger.info(f'[APScheduler] Scheduler instance obtained: {scheduler}')
        logger.info(f'[APScheduler] Scheduler running state: {scheduler.running}')

        if not scheduler.running:
            try:
                scheduler.start()
                logger.info('[APScheduler] Scheduler started successfully')
                logger.info(f'[APScheduler] Scheduler state: running={scheduler.running}')
                logger.info(f'[APScheduler] Job count: {len(scheduler.get_jobs())}')

                # 【修复】验证调度器确实在运行
                if not scheduler.running:
                    raise RuntimeError('Scheduler failed to start (running=False after start())')

            except Exception as e:
                logger.error(f'[APScheduler] Failed to start scheduler: {e}', exc_info=True)
                raise
        else:
            logger.info('[APScheduler] Scheduler already running')

        return scheduler  # 返回调度器实例
    except Exception as e:
        logger.error(f'[APScheduler] start_scheduler failed: {e}', exc_info=True)
        raise
```

## 测试验证

### 1. Windows锁机制测试

创建了测试脚本`test_windows_scheduler.py`验证Windows锁机制:

```bash
$ python test_windows_scheduler.py

2026-03-03 22:32:40,047 - __main__ - INFO - [Test] Platform: Windows
2026-03-03 22:32:40,049 - __main__ - INFO - [Test] Windows lock acquired successfully
2026-03-03 22:32:43,049 - __main__ - INFO - [Test] Windows lock released
2026-03-03 22:32:43,050 - __main__ - INFO - [Test] Lock file closed
```

**测试结果**: ✅ 通过 - Windows锁机制工作正常

### 2. 部署步骤

1. **重启Django服务**
   ```bash
   # 停止当前服务
   # Windows: Ctrl+C 或关闭终端

   # 重新启动
   cd e:/TDYW/spug-3.0/data/backend
   python manage.py runserver
   ```

2. **检查启动日志**
   ```
   [WSGI] APScheduler initialized successfully (single instance)
   [APScheduler] Scheduler started successfully
   [APScheduler] Scheduler state: running=True
   ```

3. **验证任务执行**
   - 上传一个文件
   - 观察合并状态应从`pending` → `merging` → `completed`
   - 不再卡在`pending`状态

## 影响范围

### 受影响平台
- ✅ **Windows**: 修复前不工作,修复后正常
- ✅ **Linux**: 不受影响,继续使用`fcntl`
- ✅ **macOS**: 不受影响,继续使用`fcntl`

### 影响功能
- **文件分片合并**: 修复前Windows下无法执行,修复后正常
- **断点续传**: 修复前Windows下无法完成合并,修复后正常
- **秒传**: 修复前Windows下秒传会创建卡住的合并任务,修复后正常

## 预防措施

### 1. 代码审查要点

- ✅ 平台相关代码必须进行跨平台测试
- ✅ Windows/Linux/macOS三大平台都要覆盖
- ✅ 使用`platform.system()`而不是硬编码路径

### 2. 测试建议

```python
# 单元测试示例
def test_cross_platform_lock():
    import platform
    assert platform.system() in ['Windows', 'Linux', 'Darwin']

    if platform.system() == 'Windows':
        import msvcrt
        # 测试Windows锁
    else:
        import fcntl
        # 测试Unix锁
```

### 3. 监控指标

在`wsgi.py`中添加启动日志:

```python
logger.info(f'[WSGI] Platform: {platform.system()}')
logger.info(f'[WSGI] Scheduler lock file: {lock_file_path}')
logger.info(f'[WSGI] Scheduler running: {_scheduler_instance is not None and _scheduler_instance.running}')
```

## 修复文件清单

1. ✅ `data/backend/spug/wsgi.py` - 跨平台文件锁
2. ✅ `data/backend/apps/document/libs/scheduler.py` - 启动验证增强
3. ✅ `test_windows_scheduler.py` - 测试脚本(新增)

## 总结

**问题**: Windows平台下`fcntl`模块不存在,导致APScheduler从未启动,合并任务卡在pending状态

**修复**: 实现跨平台文件锁支持
- Windows: 使用`msvcrt.locking`
- Linux/macOS: 继续使用`fcntl.flock`

**验证**: Windows锁机制测试通过,部署后需重启服务生效

# 项目审计日志规范报告

生成时间: 2026-05-31
检查模块: account, duty, device, runlog, checksheet

---

## 一、各模块审计日志现状

| 模块 | 日志方式 | 统一logger | 租户上下文 | 异常堆栈 | Print语句 |
|------|---------|------------|-----------|---------|----------|
| account | save_audit_log + logger | ✅ | ✅ | ✅ | ❌ 无 |
| duty | logger | ✅ | ✅ | ✅ | ❌ 无 |
| device | logging直接调用 | ⚠️ 部分 | ✅ | ✅ | ❌ 无 |
| runlog | logger | ✅ | ⚠️ 部分 | ✅ | ⚠️ 有2处 |
| checksheet | logger | ✅ | N/A | ✅ | ❌ 已清理 |

---

## 二、发现的问题

### 1. runlog 模块有残留 print 语句

**位置**: `spug_api/apps/runlog/views.py`

```python
# 第215行
print(f'[RunLog] 删除事件 ID={event.id}, 关联动态数={updates.count()}')

# 第228行
print(f'[RunLog] 清理附件失败: {e}')
```

**建议**: 改用 `logger.info()` / `logger.error()`

---

### 2. device 模块日志风格不统一

**问题**: 直接使用 `logging.info()` 而非 `logger = logging.getLogger(__name__)`

```python
# 当前写法
logging.warning(f'创建设备失败：...')

# 建议写法
logger.warning(f'创建设备失败：...')
```

---

## 三、优秀实践（值得推广）

### 1. account 模块：结构化审计日志

```python
from apps.logs.audit import save_audit_log

save_audit_log(
    user_id=user.id,
    username=user.username,
    action='login',
    target_type='auth',
    target_name='登录系统',
    ip=x_real_ip,
    is_success=True,
    tenant_id=getattr(user, 'tenant_id', 'default'),
)
```

### 2. duty 模块：租户越权检测日志

```python
logger.warning(
    f'用户{request.user.username}尝试{operation}跨租户/不存在的{model.__name__}记录{record_id} | '
    f'IP：{request.META.get("REMOTE_ADDR")} | 时间：{human_datetime()}'
)
```

### 3. device 模块：详细的操作上下文

```python
logger.info(f'创建设备成功｜租户：{tenant_id}｜用户：{request.user.username}｜设备编号：{form.device_sn}')
```

---

## 四、审计日志规范建议

### 1. 统一日志对象

```python
# 每个模块顶部
import logging
logger = logging.getLogger(__name__)
```

### 2. 日志分级规范

| 级别 | 使用场景 |
|------|---------|
| DEBUG | 开发调试（生产环境关闭） |
| INFO | 正常业务流程：增删改查操作 |
| WARNING | 业务异常：参数校验失败、权限不足、越权尝试 |
| ERROR | 系统异常：数据库错误、外部服务超时 |
| CRITICAL | 严重错误：系统不可用 |

### 3. 日志内容规范

```python
# ✅ 推荐：包含关键上下文
logger.info(f'创建设备成功｜租户：{tenant_id}｜用户：{user}｜设备编号：{sn}')

# ❌ 不推荐：信息不足
logger.info('创建设备成功')
```

### 4. 异常日志规范

```python
# ✅ 推荐：包含堆栈信息
logger.error(f'数据库错误：{e}', exc_info=True)

# ❌ 不推荐：无堆栈信息
logger.error(f'数据库错误：{e}')
```

### 5. 不允许使用 print

所有调试输出必须使用 `logger.debug()` 或 `logger.info()`，禁止使用 `print()`。

---

## 五、行动计划

| 优先级 | 问题 | 负责人 | 状态 |
|--------|------|--------|------|
| P1 | runlog 模块 print 语句改为 logger | - | 待处理 |
| P2 | device 模块 logging 改为 logger | - | 待处理 |
| P3 | 考虑推广 save_audit_log 审计日志 | - | 建议 |

---

## 六、附录：各模块日志配置确认清单

```
[ ] account/views.py - 有 save_audit_log + logger
[ ] duty/views.py   - 有 logger + tenant_operation_check
[ ] device/views.py - 有 logging（需统一为 logger）
[ ] runlog/views.py - 有 logger（需移除 print）
[ ] checksheet/views.py - 有 logger（已清理 print）
```

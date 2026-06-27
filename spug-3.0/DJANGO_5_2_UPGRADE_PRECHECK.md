# Django 5.2 LTS 升级预检报告

生成时间：2026-06-27

## 结论

当前平台不建议从 Django 2.2.28 直接跳到 Django 5.2 LTS。建议按 LTS 阶段升级：

```text
Django 2.2.28 -> Django 3.2.x -> Django 4.2.x -> Django 5.2 LTS
```

本项目业务代码中明显的旧 Django API 不算多，主要风险集中在依赖矩阵、Channels/ASGI、Celery Beat、MySQL 驱动和时间处理。升级可以做，但需要按阶段验证，不适合只改 `requirements.txt`。

## 当前状态

后端当前核心依赖：

```text
Django==2.2.28
asgiref==3.2.10
channels==2.3.1
channels_redis==2.4.1
daphne==2.5.0
django-redis==4.10.0
celery==5.2.7
django-celery-results==2.4.0
django-celery-beat==2.2.1
mysqlclient==1.4.6
pymysql==1.1.2
```

当前容器基础环境使用 Python 3.10。Django 5.2 LTS 支持 Python 3.10，因此最终目标版本和当前 Python 大版本兼容。

已执行预检命令：

```bash
python -Wa manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
```

结果：

```text
System check identified no issues
No changes detected
No planned migration operations
```

注意：`python -Wa manage.py check` 发现当前 Django 2.2 在 Python 3.10 下有 `distutils` 和 `six` 导入相关警告。这属于旧依赖栈的兼容信号，升级依赖后应消失。

## 必须处理的兼容点

### 1. URL 路由旧写法

以下文件仍使用 `django.conf.urls.url`：

```text
spug_api/apps/account/urls.py
spug_api/apps/device/urls.py
spug_api/apps/interference/urls.py
spug_api/apps/logs/urls.py
spug_api/apps/radio_license/urls.py
spug_api/apps/setting/urls.py
```

Django 4.0 移除了 `django.conf.urls.url`。升级到 Django 4.2/5.2 前必须改为 `django.urls.re_path` 或 `path`。

建议最小改法：

```python
from django.urls import re_path

urlpatterns = [
    re_path(r'^login/$', login),
]
```

### 2. Settings 中的旧配置

`spug_api/spug/settings.py` 中存在：

```python
USE_L10N = True
```

`USE_L10N` 在新版本 Django 中已废弃/移除，应在升级链路中删除并验证日期、数字格式展示。

### 3. 时间库 pytz

发现：

```text
spug_api/libs/helper.py
```

使用：

```python
from pytz import timezone
```

Django 4+ 默认转向 `zoneinfo`。项目当前 `USE_TZ = False`，短期可降低影响，但升级到 5.2 时建议统一梳理时间处理策略：

```text
保持 USE_TZ=False：重点验证本地时间、Celery Beat、日志时间。
切换 USE_TZ=True：需要做更完整的数据和业务评估，不建议和框架升级同批完成。
```

### 4. 默认主键类型

部分 app 已配置 `default_auto_field = 'django.db.models.AutoField'`，但不是所有 app 都统一。Django 3.2 起默认主键变为 `BigAutoField`。

建议在 `settings.py` 增加全局配置，避免升级后生成大量无意义迁移：

```python
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
```

### 5. unique_together

以下模型仍有 `unique_together`：

```text
spug_api/apps/checksheet/models.py
spug_api/apps/setting/models.py
spug_api/apps/upgrade/models.py
```

Django 5.2 仍可工作，但长期建议迁移为 `UniqueConstraint`。这不是第一阶段阻断项，建议升级稳定后再做结构性清理。

## 依赖升级建议

不要单独升级 Django。以下依赖需要作为一组处理：

```text
Django
asgiref
channels
channels_redis
daphne
django-redis
django-celery-results
django-celery-beat
django-timezone-field
mysqlclient
celery/kombu
```

建议目标方向：

```text
Django: 5.2.x LTS
channels: 4.x
channels_redis: 4.x
daphne: 4.x
asgiref: 跟随 Django/Channels 约束
django-redis: 5.x 或 6.x
django-celery-results: 2.5+ 或兼容 Django 5 的当前稳定版
django-celery-beat: 2.6+ 或兼容 Django 5 的当前稳定版
mysqlclient: 2.2+
```

实际版本应通过独立升级分支中的 `pip install` 解析结果确认，不能只按上面的范围硬写。

## 分阶段升级方案

### 阶段 0：升级前基线

目标：确认当前 2.2 状态干净，建立可回归基线。

执行：

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python -Wa manage.py check
```

需要补充或确认的回归场景：

```text
登录/退出
用户、角色、租户
设备管理
干扰记录导入/导出
资料库上传、分片合并、预览、回收站
运行日志
日检查单
系统升级管理
操作审计日志
无线电执照、附件、提醒、定时扫描
WebSocket 连接
Celery worker、beat、专用队列
```

### 阶段 1：Django 2.2 -> 3.2

目标：先进入仍较接近旧项目结构的 LTS 版本。

重点：

```text
增加 DEFAULT_AUTO_FIELD
升级 Django 到 3.2.x
升级兼容的 django-celery-beat/results、django-redis、mysqlclient
运行 check、migrate、核心接口回归
处理新增 warning
```

### 阶段 2：Django 3.2 -> 4.2

目标：处理真正的断点，尤其是移除旧 URL API。

必须完成：

```text
django.conf.urls.url -> django.urls.re_path/path
删除 USE_L10N
检查 ASGI/Channels 入口
升级 channels/channels_redis/daphne 到兼容版本
验证 WebSocket 和 Celery Beat
```

### 阶段 3：Django 4.2 -> 5.2 LTS

目标：进入长期支持版本，锁定后续平台更新基础。

重点：

```text
确认所有第三方包支持 Django 5.2
清理 Django 5.2 下的 warning
验证迁移历史可从空库完整执行
验证生产镜像构建
验证 supervisor 下所有进程启动
```

## 高风险链路

### Channels / WebSocket

当前：

```text
channels==2.3.1
channels_redis==2.4.1
daphne==2.5.0
```

这组依赖跨度大。升级到 Channels 4 后，ASGI 初始化、认证中间件、routing 行为都需要验证。

重点文件：

```text
spug_api/spug/asgi.py
spug_api/spug/routing.py
spug_api/consumer/routing.py
```

### Celery Beat

当前使用：

```text
django-celery-results
django-celery-beat
django-timezone-field
USE_TZ = False
DJANGO_CELERY_BEAT_TZ_AWARE = False
```

升级时必须验证：

```text
周期任务是否还按 Asia/Shanghai 执行
数据库里的 PeriodicTask 是否正常加载
document 队列和 radio_license 队列是否仍路由正确
```

### MySQL 驱动

当前：

```text
mysqlclient==1.4.6
pymysql==1.1.2
```

Django 5.2 建议升级 `mysqlclient` 到 2.2+。同时验证：

```text
utf8mb4
STRICT_TRANS_TABLES
连接超时参数
大文件上传相关 max_allowed_packet
gevent/gunicorn 下连接关闭行为
```

### 文件上传和预览

资料库模块涉及：

```text
分片上传
后台合并
回收站
kkFileView 预览
本地 storage 路径
Celery 清理任务
```

升级期间需要做真实文件回归，不只跑单元测试。

## 建议的成功标准

每个阶段升级完成后，应满足：

```text
python manage.py check 无错误
python manage.py makemigrations --check --dry-run 输出 No changes detected
python manage.py migrate --plan 无非预期迁移
空库 migrate 可完整执行
容器镜像可重新构建
supervisor 管理的所有进程 RUNNING
前端主要页面可登录访问
WebSocket 可连接
Celery worker 可消费任务
Celery Beat 可下发周期任务
文件上传/合并/预览成功
导出功能成功
```

## 建议优先改动清单

1. 提交当前已补齐的 migration 文件，确保 2.2 基线干净。
2. 新建升级分支，例如 `codex/django-5-2-upgrade`。
3. 在 2.2 下先改 `django.conf.urls.url` 为 `re_path`，这个改动向后兼容。
4. 在 2.2 下增加 `DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'`，避免 3.2 引入主键迁移噪音。
5. 删除或规划删除 `USE_L10N`。
6. 建立一份最小回归脚本/清单，覆盖登录、文件、Celery、WebSocket。
7. 按 3.2、4.2、5.2 分阶段升级依赖和代码。

## 不建议同批做的事

以下改动建议不要和 Django 大版本升级放在同一批：

```text
切换 USE_TZ=True
重构所有 unique_together 为 UniqueConstraint
重构认证/权限体系
重构文件存储结构
大规模前端改造
数据库字符集或表结构清理
```

这些改动本身都有业务风险，应在 Django 5.2 稳定后单独规划。

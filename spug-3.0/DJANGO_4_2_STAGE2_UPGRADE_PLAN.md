# 阶段 2：Django 3.2 -> 4.2 升级方案

生成时间：2026-06-27

## 目标

本阶段只做一件事：把后端从 Django 3.2.x 升级到 Django 4.2.x，并保持现有业务行为不变。

阶段 2 的定位是“跨过 Django 4 的主要断点”。本阶段完成后，项目应具备继续升级到 Django 5.2 LTS 的基础。

推荐总路线仍然是：

```text
Django 2.2.28 -> Django 3.2.x -> Django 4.2.x -> Django 5.2 LTS
```

官方依据：

- Django 4.2 是 LTS 版本。
- Django 4.2 支持 Python 3.8、3.9、3.10、3.11、3.12。
- Django 4.2 支持 MariaDB 10.4+，当前 MariaDB 10.8.2 满足版本要求。
- Django 4.0 起移除了 `django.conf.urls.url` 等旧 API，阶段 2 必须保证这些断点已清理。

参考：

- https://docs.djangoproject.com/en/4.2/releases/4.2/
- https://docs.djangoproject.com/en/4.2/howto/upgrade-version/
- https://docs.djangoproject.com/en/4.2/ref/databases/#mariadb-notes

## 本阶段边界

### 要做

```text
确认 Django 3.2 阶段基线干净
升级 Django 到 4.2.x
升级必要的后端依赖
清理 Django 4 下会直接阻断启动的旧 API
验证 Channels / ASGI / WebSocket
验证 Celery / Celery Beat
验证 MySQL 连接和迁移
构建阶段 2 测试镜像
完成核心业务回归
```

### 暂不做

```text
不升级到 Django 5.2
不升级前端 React/antd/构建链
不升级 MariaDB
不切换 USE_TZ=True
不重构认证/权限/文件模块
不把 unique_together 大规模改为 UniqueConstraint
不系统性重写 Dockerfile
```

说明：阶段 2 可以对 Dockerfile 做“让镜像能构建和启动”的最小修补，但不要在本阶段换基础镜像、换 Python 大版本、重写 entrypoint 或重写 supervisor。

## 当前阶段 1 后状态

当前 `spug_api/requirements.txt` 已进入 Django 3.2 范围：

```text
Django>=3.2,<3.3
asgiref>=3.3.2,<4
channels==2.3.1
channels_redis==2.4.1
daphne==2.5.0
django-redis>=5.0,<6.0
mysqlclient>=2.0,<3
```

当前容器实测 Django 版本：

```text
3.2.25
```

阶段 1 已经处理过的内容应包括：

```text
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
部分/全部 django.conf.urls.url -> django.urls.re_path
Django 3.2 下 check、makemigrations dry-run、migrate plan 通过
```

进入阶段 2 前，必须确认以上状态真实成立。

## 升级前基线确认

在当前 Django 3.2 环境执行：

```bash
cd /data/spug/spug_api
python -m django --version
python manage.py check
python -Wa manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
```

期望：

```text
Django 版本为 3.2.x
System check identified no issues
No changes detected
No planned migration operations
```

如果 `python -Wa manage.py check` 出现 `RemovedInDjango40Warning`，需要优先处理。不要带着 Django 4 会移除的 API 进入 4.2。

## 必须清理的 Django 4 断点

### 1. django.conf.urls.url

Django 4.0 起移除 `django.conf.urls.url`。

阶段 1 后当前扫描结果已经没有发现业务 url 文件继续使用它；阶段 2 仍需复查：

```bash
grep -R "django.conf.urls import url" -n spug_api
grep -R "url(r" -n spug_api/apps spug_api/spug
```

PowerShell 可用：

```powershell
Get-ChildItem -Path spug_api -Recurse -Filter *.py |
  Select-String -Pattern "django\.conf\.urls import url|url\(r"
```

如仍存在，做等价替换：

```python
from django.urls import re_path

urlpatterns = [
    re_path(r'^login/$', login),
]
```

不要修改 URL 正则、接口路径或 view。

### 2. USE_L10N

当前 `spug_api/spug/settings.py` 仍存在：

```python
USE_L10N = True
```

Django 4.x 中该配置已无实际必要，并且后续版本会移除相关兼容。阶段 2 建议删除该行。

删除后重点回归：

```text
日期时间显示
数字格式
导出文件中的日期/数字
前端表格日期渲染
```

### 3. pytz / zoneinfo

当前发现：

```text
spug_api/libs/helper.py
```

使用：

```python
from pytz import timezone
```

阶段 2 不强制切换到 `zoneinfo`，因为项目当前：

```python
USE_TZ = False
TIME_ZONE = 'Asia/Shanghai'
```

但是需要记录并验证：

```text
Celery Beat 是否按北京时间执行
日志时间是否正确
无线电执照提醒扫描时间是否正确
资料库清理任务时间是否正确
```

如果 Django 4.2 下出现 pytz 相关 warning，再做最小适配；不要在本阶段切换 `USE_TZ=True`。

## 依赖升级建议

阶段 2 的最小目标：

```text
Django>=4.2,<4.3
asgiref>=3.6,<4
```

当前 Channels 2.x 对 Django 4.2 风险较高，建议在阶段 2 将 WebSocket 栈升级到 Channels 3.x，而不是直接到 4.x：

```text
channels>=3,<4
channels_redis>=3,<4
daphne>=3,<4
```

理由：

```text
Channels 2.x 过旧，和 Django 4.2 / Python 3.10 的组合风险较高
Channels 3.x 是过渡版本，改动小于 Channels 4.x
Channels 4.x 留到 Django 5.2 阶段或单独处理更稳
```

其他建议：

```text
django-redis 保持 >=5.0,<6.0，若安装/运行报错再升级
mysqlclient 保持 >=2.0,<3，若构建失败再锁定 2.2.x
django-celery-results 优先保持 2.4.0，若 Django 4.2 兼容问题再升到 2.5.x
django-celery-beat 优先保持 2.2.1，若 Django 4.2 兼容问题再升到 2.5/2.6 兼容版本
django-timezone-field 跟随 django-celery-beat 依赖解析
celery 5.2.7 可暂不动，除非依赖冲突或运行问题
```

建议不要一次性“全包升级到最新版”。阶段 2 的核心是跨到 Django 4.2，不是依赖现代化。

## ASGI / Channels 验证重点

重点文件：

```text
spug_api/spug/asgi.py
spug_api/spug/routing.py
spug_api/consumer/routing.py
```

当前 ASGI 入口使用：

```python
from channels.routing import get_default_application
```

升级 Channels 后如出现导入或启动异常，需要按 Channels 3 的方式做最小适配。

验证内容：

```text
spug-ws 进程能启动
WebSocket 握手成功
认证后的 WebSocket 能连接
实时输出类功能正常
断线重连正常
无明显 403/500/ASGI application loading failure
```

## Celery / Beat 验证重点

阶段 2 需要重点验证：

```text
spug-worker 启动
spug-celery-default 启动
spug-celery-batch 启动
spug-celery-merge 启动
spug-celery-cleanup 启动
spug-celery-radio-license 启动
spug-celery-beat 启动
```

任务回归：

```text
资料库分片合并
资料库批量删除
资料库清理任务
无线电执照到期扫描
Celery Beat 周期任务下发
```

如果 `django-celery-beat` 需要升级，必须运行：

```bash
python manage.py migrate django_celery_beat
python manage.py migrate --plan
```

并确认没有非预期迁移。

## 数据库兼容

当前 MariaDB 10.8.2 满足 Django 4.2 要求。

阶段 2 不升级数据库。

需要验证：

```text
mysqlclient 能安装
数据库连接正常
migrate --plan 正常
大文件相关 max_allowed_packet 配置仍生效
STRICT_TRANS_TABLES 下保存/更新正常
```

## Docker 构建策略

阶段 2 完成代码和依赖修改后，主动构建独立测试镜像：

```bash
docker build -t tdyw:django42-stage2 -f docker/Dockerfile .
```

要求：

```text
不要覆盖 tdyw:0601、tdyw:0623、tdyw:latest
不要 push 镜像
不要改生产 compose
不要系统性重构 Dockerfile
```

如果构建失败，只做必要修补：

```text
pip/setuptools/wheel 太旧
mysqlclient 编译依赖不足
Channels/Daphne 依赖解析失败
系统包缺失
```

## 启动验证

使用阶段 2 镜像启动测试环境后，确认 supervisor 中所有进程 `RUNNING`：

```text
nginx
redis
spug-api
spug-api-upload
spug-ws
spug-worker
spug-celery-batch
spug-celery-merge
spug-celery-radio-license
spug-celery-cleanup
spug-celery-default
spug-celery-beat
```

重点检查日志：

```text
ImportError
ModuleNotFoundError
RemovedInDjango40Warning
RemovedInDjango50Warning
ASGI application loading failure
Celery app import failure
DatabaseError
MigrationSchemaMissing
```

`RemovedInDjango50Warning` 可以作为阶段 3 修复输入，但如果数量很少，也建议本阶段顺手做等价修复。

## 功能回归清单

### 基础

```text
登录
退出
当前用户信息
角色/租户列表
菜单加载
接口鉴权失败时响应格式
```

### 业务模块

```text
设备管理列表
设备履历
干扰记录列表
干扰记录导出
运行日志列表
日检查单列表
系统升级管理列表
操作审计日志列表
无线电执照列表
无线电执照详情
无线电执照附件下载
无线电执照提醒角标
```

### 文件模块

```text
资料库普通上传
资料库分片上传
分片合并
资料库下载
资料库预览
资料库删除
回收站恢复/清理
大文件上传
```

### 异步和实时链路

```text
Celery worker 消费任务
Celery Beat 下发周期任务
WebSocket 建立连接
WebSocket 实时输出
WebSocket 断线重连
```

## 成功标准

阶段 2 完成必须同时满足：

```text
Django 实际版本为 4.2.x
python manage.py check 无错误
python -Wa manage.py check 无 Django 4 阻断 warning
python manage.py makemigrations --check --dry-run 输出 No changes detected
python manage.py migrate --plan 无非预期迁移
阶段 2 测试镜像 tdyw:django42-stage2 构建成功
测试环境可启动
supervisor 所有进程 RUNNING
登录和主要页面可访问
Celery worker/beat 正常
WebSocket 正常
文件上传/合并/预览正常
导出功能正常
```

## 回滚方案

阶段 2 必须在独立分支和测试镜像中进行。

回滚方式：

```bash
git switch Django 3.2 稳定分支
docker compose 改回 Django 3.2 测试镜像或原有镜像
```

如果测试数据库已执行新迁移：

```text
优先恢复测试库快照
不要在生产库直接试验阶段 2
阶段 2 理论上不应引入大量业务表结构迁移
```

## 给 Codex/AI 的执行提示词

可以直接复制下面这段作为阶段 2 实施提示：

```text
请在当前项目中执行“阶段 2：Django 3.2 -> Django 4.2”升级。

要求：
1. 先阅读 DJANGO_5_2_UPGRADE_PRECHECK.md、DJANGO_3_2_STAGE1_UPGRADE_PLAN.md 和 DJANGO_4_2_STAGE2_UPGRADE_PLAN.md。
2. 本阶段只升级后端 Django 3.2.x -> 4.2.x，不要升级到 Django 5.2，不要升级前端，不要升级数据库。
3. 开始前确认当前基线：python -m django --version、python manage.py check、python -Wa manage.py check、makemigrations --check --dry-run、migrate --plan。
4. 确认没有 django.conf.urls.url、url(r...) 旧写法残留；如有，只做等价替换为 django.urls.re_path，不改变 URL 路径和 view。
5. 删除 settings.py 中的 USE_L10N，并回归日期、数字、导出显示。
6. 将 requirements.txt 中 Django 升到 >=4.2,<4.3，并同步升级 asgiref 到兼容范围。
7. 优先将 channels、channels_redis、daphne 作为一组升到 3.x；不要升到 4.x，除非明确证明 3.x 无法兼容。
8. 其他依赖只做必要升级：django-redis、mysqlclient、django-celery-results、django-celery-beat、django-timezone-field 如报错再小步升级。
9. 每类改动后运行 python manage.py check、python -Wa manage.py check、makemigrations dry-run、migrate plan。
10. 完成后主动构建独立测试镜像：docker build -t tdyw:django42-stage2 -f docker/Dockerfile . 不要覆盖现有镜像 tag。
11. 用测试镜像启动验证，确认 nginx、redis、api、upload、ws、worker、celery、beat 全部 RUNNING。
12. 完成登录、文件上传/合并/预览、Celery、WebSocket、导出、无线电执照提醒等核心回归。
13. 最后输出修改文件清单、依赖版本变化、新增 migration 情况、验证命令结果、遗留 warning、阶段 3：Django 4.2 -> 5.2 的待处理项。
```

## 阶段 2 完成后的阶段 3 输入

阶段 2 完成后，应产出：

```text
Django 4.2 可运行分支
依赖版本清单
Channels 当前版本和 WebSocket 回归结果
Celery Beat 回归结果
RemovedInDjango50Warning 清单
是否仍使用 pytz
是否仍保留 USE_TZ=False
是否有待处理第三方依赖兼容问题
```

这些内容将作为阶段 3：Django 4.2 -> 5.2 LTS 的输入。

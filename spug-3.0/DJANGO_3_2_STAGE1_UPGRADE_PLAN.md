# 阶段 1：Django 2.2 -> 3.2 升级方案

生成时间：2026-06-27

## 目标

本阶段只做一件事：把后端从 Django 2.2.28 升级到 Django 3.2.x，并保持现有业务行为不变。

不在本阶段追求 Django 5.2，不升级前端大版本，不重构业务模块，不切换时区策略。

推荐总路线仍然是：

```text
Django 2.2.28 -> Django 3.2.x -> Django 4.2.x -> Django 5.2 LTS
```

官方依据：

- Django 3.2 是 LTS 版本，并支持 Python 3.10（从 3.2.9 起）。
- Django 3.2 引入 `DEFAULT_AUTO_FIELD`，需要显式设置以避免无意义主键迁移。
- 官方升级指南建议逐步升级、先处理废弃警告，再进入下一版本。

参考：

- https://docs.djangoproject.com/en/3.2/releases/3.2/
- https://docs.djangoproject.com/en/3.2/howto/upgrade-version/
- https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

## 本阶段边界

### 要做

```text
补齐并提交当前迁移文件
建立 Django 2.2 基线
添加 DEFAULT_AUTO_FIELD
升级 Django 到 3.2.x
升级必要的后端依赖
修复 Django 3.2 下的启动、检查、迁移、运行问题
完成核心业务回归
```

### 暂不做

```text
不升级到 Django 4.2/5.2
不把 django.conf.urls.url 全部强制改完，除非顺手向后兼容修改
不升级 React/antd/前端构建链
不切换 USE_TZ=True
不重构 unique_together
不升级 Channels 到 4.x
不做大规模认证、权限、文件模块重构
```

说明：`django.conf.urls.url` 在 Django 3.2 仍可运行，但 Django 4.0 会移除。阶段 1 可以先改为 `re_path`，因为它对 Django 2.2/3.2 都兼容；但不要扩大成路由结构重构。

## 当前项目已知状态

当前后端依赖文件：

```text
spug_api/requirements.txt
```

当前核心版本：

```text
Django==2.2.28
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

当前容器使用 Python 3.10。Django 2.2 与 Python 3.10 并不是官方推荐组合，但当前能运行。Django 3.2.x 与 Python 3.10 的组合更合理。

## 升级前必须做的基线确认

在当前 Django 2.2 环境执行：

```bash
cd /data/spug/spug_api
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python -Wa manage.py check
```

期望：

```text
No changes detected
No planned migration operations
System check identified no issues
```

如果发现未提交 migration，先补齐并提交。不要带着“模型和迁移状态不一致”进入升级。

## 建议新建分支

```bash
git checkout -b codex/django-3-2-stage1
```

升级期间不要混入无关业务改动。当前工作区如果已有其他功能改动，建议先提交或单独保存，否则后续定位问题会很痛。

## 代码改动计划

### 1. 增加 DEFAULT_AUTO_FIELD

在 `spug_api/spug/settings.py` 中加入：

```python
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'
```

建议放在 `INSTALLED_APPS` 附近或数据库配置前后。

目的：保持 Django 2.2 时代的 `AutoField` 行为，避免 Django 3.2 引入 `BigAutoField` 后生成大量主键迁移。

验证：

```bash
python manage.py makemigrations --check --dry-run
```

期望仍为：

```text
No changes detected
```

### 2. 可选：提前替换 django.conf.urls.url

这不是 Django 3.2 的硬阻断，但建议在阶段 1 先处理，减少阶段 2 风险。

已发现文件：

```text
spug_api/apps/account/urls.py
spug_api/apps/device/urls.py
spug_api/apps/interference/urls.py
spug_api/apps/logs/urls.py
spug_api/apps/radio_license/urls.py
spug_api/apps/setting/urls.py
```

最小替换方式：

```python
from django.urls import re_path

urlpatterns = [
    re_path(r'^login/$', login),
]
```

注意：

```text
只改 import 和函数名
不要改 URL 正则内容
不要改接口路径
不要改 view
```

验证：

```bash
python manage.py check
```

### 3. 依赖升级

建议先采用最小升级策略：

```text
Django>=3.2,<3.3
asgiref>=3.3.2,<4
mysqlclient>=2.0,<3
```

其他依赖优先不动，除非 pip 解析或运行报错。

如果 Channels 2.x 与 Django 3.2 / asgiref 组合出现依赖冲突，再考虑把 WebSocket 依赖作为一组升到 Channels 3.x：

```text
channels>=3,<4
channels_redis>=3,<4
daphne>=3,<4
```

不要在阶段 1 升到 Channels 4.x。Channels 4 留到 Django 4.2/5.2 阶段处理更稳。

`django-celery-results`、`django-celery-beat`、`django-redis` 暂时以“能通过安装、check、启动、回归”为准。若报 Django 版本不兼容，再小步升级到支持 Django 3.2 的版本。

## Docker 构建注意

当前 Dockerfile 使用 Python 3.10 虚拟环境安装 `spug_api/requirements.txt`。

阶段 1 需要验证：

```bash
docker build -t tdyw:django32-stage1 -f docker/Dockerfile .
```

如果 `mysqlclient` 编译失败，优先检查镜像里是否仍有：

```text
default-libmysqlclient-dev
gcc
g++
pkg-config
```

不要为了绕过编译问题直接删除 `mysqlclient`，因为当前 Django 配置使用 MySQL 后端。

## 数据库迁移策略

阶段 1 正常情况下不应该产生业务表结构迁移。

每次依赖或配置改完后执行：

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
```

如果出现大量 `id` 字段从 `AutoField` 变为 `BigAutoField` 的迁移，说明 `DEFAULT_AUTO_FIELD` 没有正确设置或某些 app 配置不一致，应先修配置，不要应用这些迁移。

## 启动验证

容器启动后确认：

```text
nginx RUNNING
redis RUNNING
spug-api RUNNING
spug-api-upload RUNNING
spug-ws RUNNING
spug-worker RUNNING
spug-celery-batch RUNNING
spug-celery-merge RUNNING
spug-celery-radio-license RUNNING
spug-celery-cleanup RUNNING
spug-celery-default RUNNING
spug-celery-beat RUNNING
```

重点看日志中是否出现：

```text
ImportError
ModuleNotFoundError
RemovedInDjango40Warning
DatabaseError
ASGI application loading failure
Celery app import failure
```

`RemovedInDjango40Warning` 不一定阻断阶段 1，但必须记录，作为阶段 2 的修复清单。

## 功能回归清单

### 基础

```text
登录
退出
当前用户信息
角色/租户列表
菜单加载
```

### 设备与业务模块

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
无线电执照附件下载
无线电执照提醒角标
```

### 文件与异步任务

```text
资料库普通上传
资料库分片上传
分片合并任务
资料库预览
资料库删除/回收站
批量删除/取消任务
Celery worker 消费
Celery Beat 定时任务下发
```

### WebSocket

```text
WebSocket 能建立连接
连接断开后能重连
执行类实时输出正常
无明显 403/500/握手失败
```

## 成功标准

阶段 1 完成必须同时满足：

```text
requirements.txt 已升级到 Django 3.2.x
python manage.py check 无错误
python -Wa manage.py check 无新的致命 warning
python manage.py makemigrations --check --dry-run 输出 No changes detected
python manage.py migrate --plan 无非预期迁移
容器可重新构建
supervisor 所有进程 RUNNING
登录和主要页面可访问
Celery worker/beat 正常
WebSocket 正常
文件上传/合并/预览正常
```

## 回滚方案

如果阶段 1 失败，回滚应只涉及升级分支，不影响主分支。

回滚方式：

```bash
git switch 原分支
docker compose 使用原镜像重新启动
```

如果已经在测试数据库执行过迁移：

```text
优先使用测试库快照恢复
不要在生产库上试验阶段 1
阶段 1 理论上不应产生业务表结构迁移
```

## 给 Codex/AI 的执行提示词

可以直接复制下面这段作为阶段 1 实施提示：

```text
请在当前项目中执行“阶段 1：Django 2.2 -> 3.2”升级。

要求：
1. 先阅读 DJANGO_5_2_UPGRADE_PRECHECK.md 和 DJANGO_3_2_STAGE1_UPGRADE_PLAN.md。
2. 不要升级前端，不要重构业务逻辑，不要直接升到 Django 4/5。
3. 先确认当前 Django 2.2 基线：makemigrations --check --dry-run、migrate --plan、python -Wa manage.py check。
4. 在 settings.py 增加 DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'，避免 BigAutoField 噪音迁移。
5. 将 requirements.txt 中 Django 升到 3.2.x，并同步处理必要依赖。优先最小升级；如 Channels 2 依赖冲突，再把 channels/channels_redis/daphne 升到 3.x，不要升 4.x。
6. 可将 django.conf.urls.url 替换为 django.urls.re_path，但只能做等价替换，不能改变 API 路径。
7. 每一步都运行 check、makemigrations dry-run、migrate plan。
8. 构建并启动容器，确认 supervisor 下 nginx、redis、api、ws、worker、celery、beat 全部 RUNNING。
9. 完成登录、文件上传/合并/预览、Celery、WebSocket、导出功能的回归。
10. 输出最终变更清单、验证结果、遗留 warning 和阶段 2 待处理项。
```

## 阶段 1 完成后的阶段 2 输入

阶段 1 完成后，应产出：

```text
Django 3.2 可运行分支
依赖版本清单
所有新增/修改 migration 状态
RemovedInDjango40Warning 清单
Channels 是否仍为 2.x 或已到 3.x
Celery Beat 和 WebSocket 回归结果
```

这些内容将作为阶段 2：Django 3.2 -> 4.2 的输入。

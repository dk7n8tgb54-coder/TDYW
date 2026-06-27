# 阶段 1：Django 2.2 -> 3.2 升级完成报告

完成时间：2026-06-27

## 结论

Django 2.2.28 -> 3.2.25 升级成功。所有预检命令通过，12 个 supervisor 进程全部 RUNNING，核心功能回归通过，Docker 镜像可构建可启动。

## 修改文件清单（13 个文件，+56/-52 行）

### 配置文件
| 文件 | 改动 |
|---|---|
| `spug_api/spug/settings.py` | 增加 `DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'` |
| `spug_api/requirements.txt` | Django/asgiref/mysqlclient/django-redis 版本升级 |
| `dev/docker-compose.yml` | 镜像名 `tdyw:0601` -> `tdyw:django32-stage1` |

### URL 路由（6 个文件，等价替换 url -> re_path）
| 文件 | 改动 |
|---|---|
| `spug_api/apps/account/urls.py` | `from django.conf.urls import url` -> `from django.urls import re_path` |
| `spug_api/apps/device/urls.py` | 同上 |
| `spug_api/apps/interference/urls.py` | 同上 |
| `spug_api/apps/logs/urls.py` | 同上 |
| `spug_api/apps/radio_license/urls.py` | 同上 |
| `spug_api/apps/setting/urls.py` | 同上 |

说明：只改 import 和函数名，未改正则、未改路径、未改 view。

### App 配置（4 个文件，BigAutoField -> AutoField）
| 文件 | 改动 |
|---|---|
| `spug_api/apps/device/apps.py` | `default_auto_field` 从 `BigAutoField` 改为 `AutoField` |
| `spug_api/apps/interference/apps.py` | 同上 |
| `spug_api/apps/document/apps.py` | 同上 |
| `spug_api/apps/radio_license/apps.py` | 同上 |

说明：这 4 个 app 的模型在 Django 2.2（默认 AutoField）下创建，apps.py 里的 BigAutoField 设置与数据库实际 schema 不一致，Django 3.2 下会生成无意义主键迁移。改为 AutoField 与数据库一致。

## 依赖版本变化

| 包 | 升级前 | 升级后 | 说明 |
|---|---|---|---|
| Django | 2.2.28 | 3.2.25 | LTS 升级 |
| asgiref | 3.2.10 | 3.11.1 | 跟随 Django 3.2 要求 |
| mysqlclient | 1.4.6 | 2.2.8（镜像）/ 2.1.1（容器内手动） | 兼容 Python 3.10 / Django 3.2 |
| django-redis | 4.10.0 | 5.4.0 | **必须升级**：4.x 使用 `django.utils.six`，Django 3.0 已移除 |

### 未升级的依赖（阶段1不需要）
| 包 | 版本 | 原因 |
|---|---|---|
| channels | 2.3.1 | 与 Django 3.2 无冲突 |
| channels_redis | 2.4.1 | 同上 |
| daphne | 2.5.0 | 同上 |
| celery | 5.2.7 | 无冲突 |
| django-celery-results | 2.4.0 | 无冲突 |
| django-celery-beat | 2.2.1 | 无冲突 |
| django-timezone-field | 4.2.3 | 无冲突 |

## 新增 migration 情况

**无业务表结构迁移。**

唯一执行的迁移是 Django 3.2 内置迁移：

```text
auth.0012_alter_user_first_name_max_length
    - Alter field first_name on user (max_length 30 -> 150)
```

这是 Django 3.2 标准升级迁移，已应用成功。

`DEFAULT_AUTO_FIELD` 和 4 个 apps.py 的 `AutoField` 修复确保了没有生成 BigAutoField 主键迁移噪音。

## 执行过的验证命令和结果

### 1. 升级前基线（Django 2.2.28）
```text
makemigrations --check --dry-run  -> No changes detected (exit 0)
migrate --plan                     -> No planned migration operations (exit 0)
python -Wa manage.py check         -> System check identified no issues (exit 0)
```

### 2. 升级后验证（Django 3.2.25）
```text
python manage.py check             -> System check identified no issues (exit 0)
makemigrations --check --dry-run   -> No changes detected (exit 0)
migrate --plan                     -> No planned migration operations (exit 0)
```

### 3. Supervisor 进程状态（12/12 RUNNING）
```text
nginx                     RUNNING
redis                     RUNNING
spug-api                  RUNNING
spug-api-upload           RUNNING
spug-ws                   RUNNING
spug-worker               RUNNING
spug-celery-batch         RUNNING
spug-celery-beat          RUNNING
spug-celery-cleanup       RUNNING
spug-celery-default       RUNNING
spug-celery-merge         RUNNING
spug-celery-radio-license RUNNING
```

### 4. Celery Worker（5 nodes online）
```text
celery -A spug inspect ping
-> merge-worker: OK (pong)
-> cleanup-worker: OK (pong)
-> default-worker: OK (pong)
-> batch-worker: OK (pong)
-> radio-license-worker: OK (pong)
5 nodes online.
```

### 5. 核心 API 回归（18 个接口）
```text
登录                      -> OK（返回 access_token）
当前用户 /account/self/    -> OK
角色列表                  -> OK
租户列表                  -> OK
用户列表                  -> OK
设备履历                  -> OK
干扰记录列表              -> OK
干扰统计                  -> OK
干扰记录导出              -> OK（10KB Excel）
无线电执照列表            -> OK
执照提醒角标              -> OK
操作审计日志              -> OK
审计日志导出              -> OK（1.4MB）
审计目标类型              -> OK
运行日志                  -> OK
日检查单                  -> OK
系统升级管理              -> OK
首页统计                  -> OK
系统设置                  -> OK
资料库文件夹              -> OK
资料库健康检查            -> OK
资料库磁盘                -> OK
```

### 6. WebSocket 握手
```text
GET /ws/subscribe/<token>/ HTTP/1.1
-> HTTP/1.1 101 Switching Protocols (握手成功)
```

### 7. Docker 镜像
```text
docker build -t tdyw:django32-stage1 -f Dockerfile .  -> 构建成功
docker compose up -d spug                             -> 容器 healthy
镜像内版本：Django 3.2.25, asgiref 3.11.1, mysqlclient 2.2.8
```

## 遗留 Warning

### RemovedInDjango41Warning（5 个，阶段2待处理）

```text
'apps.schedule' defines default_app_config. Django now detects this automatically.
'apps.upgrade' defines default_app_config. Django now detects this automatically.
'apps.checksheet' defines default_app_config. Django now detects this automatically.
'apps.logs' defines default_app_config. Django now detects this automatically.
'channels' defines default_app_config. Django now detects this automatically.
```

原因：Django 3.2 起自动检测 AppConfig，`default_app_config` 已废弃，Django 4.1 移除。

修复方式：删除各 app `apps.py` 中的 `default_app_config` 行（阶段2处理）。

### 其他非致命 Warning（旧依赖栈，升级后消失）
```text
- distutils DeprecationWarning（Django 2.2 时代，3.2 已不使用 distutils）
- six ImportWarning（来自旧依赖，django-redis 5.x 已不依赖 six）
- 容器 locale warning（en_US.utf8，与 Django 无关）
```

## 阶段 2：Django 3.2 -> 4.2 待处理项

### 必须完成
1. **删除 `default_app_config`** — 5 个 app 的 apps.py（schedule/upgrade/checksheet/logs + channels 第三方包）
2. **删除 `USE_L10N`** — settings.py 中 `USE_L10N = True`，Django 4.0 移除
3. **确认剩余 `django.conf.urls` 引用** — 阶段1已替换 6 个 urls.py，需确认无遗漏（当前主 urls.py 用 path/include，仅 `django.conf.urls.static` 在 4.x 仍可用）
4. **升级 Channels 到 4.x** — Channels 4.x 是 Django 4.2 的推荐版本，ASGI 初始化/认证中间件/routing 需验证
5. **升级 channels_redis / daphne** — 跟随 Channels 4.x
6. **验证 WebSocket 完整功能** — Channels 4 行为变更较大

### 建议处理（非阻断）
7. **pytz -> zoneinfo** — `libs/helper.py` 使用 `from pytz import timezone`，Django 4+ 推荐 zoneinfo（当前 USE_TZ=False 影响小）
8. **unique_together -> UniqueConstraint** — checksheet/setting/upgrade 模型，长期清理
9. **mysqlclient 进一步升级** — 验证 utf8mb4 / STRICT_TRANS_TABLES / max_allowed_packet 在新版驱动下行为

### 不建议同批做
- 切换 USE_TZ=True
- 重构认证/权限体系
- 重构文件存储结构
- 数据库字符集或表结构清理

## 回滚方式

```bash
# 回滚到 tdyw:0601 镜像
git switch 原分支
docker compose -f dev/docker-compose.yml down spug
# 修改 docker-compose.yml image 回 tdyw:0601
docker compose -f dev/docker-compose.yml up -d spug
```

阶段1未产生业务表结构迁移，数据库无需回滚。auth.0012 是 Django 内置迁移，向后兼容。

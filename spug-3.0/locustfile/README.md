# 资料库压测套件（locust）

> 对齐 2026-06 后的真实接口（**回收站已于 2026-06-23 移除**，旧脚本里的 `/recycle-bin/*` 全部 404，已从本套件删除）。

---

## 0. 当前环境状态（重要，先读）

压测目标：**生产容器 `tdyw`**（镜像 `tdyw:0719`），映射到宿主机 80（HTTP）/ 443（HTTPS）端口。

```
docker ps  →  tdyw / tdyw-db / kkfileview
```

- `tdyw` 容器提供完整的 HTTP 服务（nginx + gunicorn + celery），`http://localhost` 可达。
- **`tdyw-test` 容器已不存在**（2026-07-20 确认），之前的"方案 B 打 tdyw-test 8080"已废弃。
- 压测直接打 `http://localhost`（即 `-H http://localhost`）。
- 生产服务器远程压测用 `-H https://192.168.40.118`。

---

## 1. 文件清单

### 主脚本（上线前必补 🔴）
| 文件 | 作用 |
|---|---|
| `account_login_stress.py` | **登录并发脚本**：高并发打 `/api/account/login/`，测登录吞吐与延迟 |
| `document_stress.py` | **主脚本**：资料库 CRUD + 普通上传 + 分片上传/合并（含断点续传）+ 传输列表 + 磁盘使用 + DB 连接池健康 |
| `locustfile_document.py` | 高并发锁竞争：同名合并/分片锁/公共空间专项 |
| `locustfile_folder_depth.py` | 文件夹深度嵌套：极限深度/递归查询/深层移动复制 |
| `locustfile_pdf_export.py` | PDF 导出并发：部门值班日志（**8G 最易 OOM**） |
| `locustfile_download.py` | 大文件下载：小/中/大文件 + 文件夹打包 |
| `locustfile_kkfileview_preview.py` | kkFileView 预览：预览令牌/office URL/普通预览（**LibreOffice OOM**） |
| `locustfile_audit_log.py` | 审计日志：深页/时间筛选/action 筛选/导出（哈希链 O(n)） |
| `locustfile_mixed_workload.py` | 混合负载：登录+查列表+上传+下载+审计日志+首页统计（模拟早高峰） |

### 上线后可补脚本（🟡 选跑）
| 文件 | 作用 |
|---|---|
| `locustfile_multi_tenant.py` | 多租户并发：验证 tenant_id 索引效率/数据隔离 |
| `locustfile_permission_cache.py` | 权限缓存击穿：超管改角色触发缓存失效风暴 |
| `locustfile_celery_queue.py` | Celery 队列积压：merge + pack 任务堆积 |
| `locustfile_bulk_upload.py` | 小文件批量上传高峰：几千个 10KB 文件持续上传（Gunicorn/DB/磁盘） |
| `locustfile_websocket.py` | WebSocket 推送：Channels 连接上限（需 websockets 库） |
| `locustfile_soak_test.py` | 8h+ 长时间稳定性：内存/连接/磁盘泄漏 |

### 辅助文件
| 文件 | 作用 |
|---|---|
| `_common.py` | 共用工具：登录/请求头/账号轮询 |
| `SLA_THRESHOLDS.md` | SLA 阈值定义 + 监控命令 + 报告模板 |
| `run_all_locust.sh` | 统一 runner：`--all` / `--only` / `--list` |
| `tools/create_stress_accounts.py` | 创建专用压测账号 + 角色（幂等） |
| `tools/verify_api.py` | 冒烟测试：真实 HTTP 走一遍 login→建文件夹→上传→分片→合并→清理 |
| `README.md` | 本文件 |

### 旧脚本（保留备用，未列入 runner）
| 文件 | 作用 |
|---|---|
| `locustfile_device.py` | 设备 CRUD（与 mixed_workload 重叠） |
| `locustfile_interference.py` | 干扰记录 CRUD |
| `locustfile_runlog.py` | 运行日志 CRUD |
| `locustfile_pagination.py` | 通用分页 |

### 已删除的旧脚本（2026-07-20）
- `document_stress_test.py`（v1，含已删除的回收站接口）
- `document_stress_test_v2.py`（v2，含回收站）
- `document_stress_test_v3.py`（v3，字段 bug，场景已被 document_stress.py 覆盖）
- `locustfile.py`（回收站）、`locustfile_recycle_bin.py`（回收站）、`运行命令行.txt`（端口/接口已过期）

---

## 2. 压测环境

### 打生产容器 `tdyw`（localhost:80）
- 启动 `tdyw` 容器栈（`docker compose up -d`，或你平时的启动方式）。
- 端口：`localhost:80`（HTTP）/ `localhost:443`（HTTPS）。
- 运行：`-H http://localhost`。
- 账号需在 `tdyw` 库建（见第 3 节）。
- **注意**：压测会写真实数据库、占真实业务资源。虽然专用账号在独立租户 `stress` 下数据隔离，但 DB 负载是共享的。建议在低峰期跑，或停掉业务后跑全量压测。
- 生产服务器远程压测：`-H https://192.168.40.118`。

---

## 3. 专用压测账号

需在 `tdyw` 库创建（用 `tools/create_stress_accounts.py`）：

```
租户隔离标识: stress
账号: st_press_01 .. st_press_05
密码: Stress@2026
角色: 压测专用角色（仅授予 document.document.* 需要的权限：
      view / create_folder / upload / delete / download / move / copy / rename）
```

创建/同步到目标环境（在目标容器内执行）：
```bash
docker cp locustfile/tools/create_stress_accounts.py tdyw:/tmp/csa.py
docker exec -i tdyw python /data/spug/spug_api/manage.py shell < /tmp/csa.py
```

> **账号锁定提醒**：`apps/account/views.py` 的 `login` 有防暴破限流——
> IP 级 1 小时内失败 ≥30 次拒绝；用户级 15 分钟内失败 ≥5 次锁 15 分钟。
> 本套件**只用正确密码**，不会产生失败计数，可安全高并发；切勿在脚本里填错密码。

---

## 4. 如何运行

### 4.1 环境准备(推荐 Docker,零安装)

```bash
# Docker 模式:无需装任何依赖,直接用 locust 官方镜像
# 首次运行自动拉取镜像(~50MB),之后有缓存
./run_all_locust.sh --list          # 先看看有哪些脚本
./run_all_locust.sh                 # 跑上线前必补(推荐)
```

如果不想用 Docker,也可以本地装(WSL 需用虚拟环境避免 zope namespace 冲突):
```bash
python3 -m venv ~/locust-venv
source ~/locust-venv/bin/activate
pip install locust websockets
./run_all_locust.sh --local         # --local 标志用本地 Python 跑
```

### 4.2 运行方式

```bash
# 统一 runner(批量跑所有脚本,推荐)
./run_all_locust.sh --list          # 列出所有脚本
./run_all_locust.sh                 # 跑上线前必补(9 个)
./run_all_locust.sh --all           # 跑全部(14 个)
./run_all_locust.sh --only pdf_export  # 只跑指定脚本

# 单脚本运行(Web 模式,手动调并发)
python -m locust -f locustfile/document_stress.py -H http://localhost

# 命令行无人值守模式
python -m locust -f locustfile/document_stress.py -H http://localhost \
    --headless -u 50 -r 10 -t 10m --csv=document_stress
```

- 不要直接敲 `locust`（命令可能没进 PATH），用 `python -m locust`。
- 并发用户默认在 5 个专用账号间轮询复用（各自拿到独立 token）。

---

## 5. 脚本修正点（相对旧 v3 脚本）

| 问题 | 旧 v3 | 本套件 |
|---|---|---|
| 回收站任务 | 打已删除的 `/recycle-bin/*` 全 404 | 已彻底移除 |
| 普通上传字段 | 错用 `parent_id` | 改为 `folder_id`（与 `FileUploadView` 一致） |
| 分片合并字段 | 错用 `parent_id` | 改为 `folder_id`（与 `merge` 视图一致） |
| 合并传 `transfer_id` | 传 uuid 字符串 → 视图 `int()` 解析失败报错 | 不传 `transfer_id`，分片目录按 `file_hash+user` 隔离 |
| 合并后清理 | 合并返回无文件 id，合并产物从不清理 | 每个用户只建**一个根文件夹**，所有操作在其下进行；`on_stop` 级联删除根文件夹（覆盖合并产物） |

---

## 6. 数据清理逻辑

- **每次运行**：每个虚拟用户 `on_start` 建一个 `stress_root_<uuid>` 根文件夹，所有子文件夹/文件都建在它下面；`on_stop` 调 `DELETE /api/document/folder/?id=<root>` 递归硬删其下全部内容（含合并生成的文件）。
- **运行中**：`delete_one_file` 任务会真实列目录→删文件，避免只增不减。
- **遗留分片目录**：若 celery-merge worker 未运行，分片目录（`storage/document_chunks`）可能残留。手动清理：
  ```bash
  docker exec tdyw sh -c 'rm -rf /data/spug/spug_api/storage/document_chunks/*'
  ```
- **紧急全清**：直接删 `stress` 租户下的根文件夹即可，不影响其他租户数据。

---

## 7. 预期指标 / 判定阈值（建议基线，按你机器调）

| 指标 | 目标 |
|---|---|
| 失败率 | < 1%（账号锁定/参数错误除外） |
| P95 响应时间（读接口） | < 500ms |
| P95 响应时间（分片合并触发） | < 2s（合并走 Celery，接口本身返回快） |
| 登录接口 P95 | < 300ms @ 200 并发 |
| DB 连接数 | 不超过 `max_connections` 的 80% |

用 `--csv=xxx` 导出后，失败率>1% 视为不达标（目前 locust 无内置阈值断言，需人眼/后处理）。

---

## 8. 服务端监控命令清单（压测时另开终端）

```bash
# 1. 容器资源（CPU/内存）
docker stats tdyw tdyw-db kkfileview

# 2. DB 连接池（项目自带，无需密码，最直接）
curl -s http://localhost/api/document/health/db-pool/ | python -m json.tool
curl -s http://localhost/api/document/health/db-pool/metrics/ | python -m json.tool

# 3. MySQL 进程/连接（用容器自身环境变量，避免硬编码密码）
docker exec tdyw-db sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SHOW PROCESSLIST; SHOW STATUS LIKE \"Threads_connected\";"'

# 4. 慢查询（进 db 容器开 general/slow log 或事后查）
docker exec tdyw-db sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SHOW GLOBAL STATUS LIKE \"Slow_queries\";"'

# 5. Gunicorn/Celery 日志
docker exec tdyw sh -c 'tail -f /data/spug/spug_api/logs/*.log'
```

> 瓶颈通常在服务端：MariaDB 连接打满、慢查询、Gunicorn worker 饱和、CPU/内存。
> 只有 locust 客户端指标（RPS/响应时间/失败率）看不出“为什么慢”，必须配合上面服务端监控。

---

## 9. 已知限制 / 注意事项

1. **回收站相关接口全部不存在**，不要在任何脚本里再出现 `/recycle-bin/*`。
2. **账号锁定**：只用正确密码；错密码 5 次/15 分钟锁账号。
3. **合并是异步**：`merge_chunks` 返回 `task_id`，文件由 celery-merge worker 落地；压测前确认该 worker 在跑，否则“上传成功”的文件不会出现。
4. **`tdyw` 容器必须运行**：压测前确认 `docker ps` 能看到 `tdyw / tdyw-db / kkfileview` 三个容器，且 `curl http://localhost/api/account/login/` 返回非 502。
5. 分片上传为单线程顺序上传（避免多线程共用 `self.client` session 的线程安全问题）；如需测“单文件并发分片”，后续可加。

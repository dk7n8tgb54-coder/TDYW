# 资料库压测套件（locust）

> 对齐 2026-06 后的真实接口（**回收站已于 2026-06-23 移除**，旧脚本里的 `/recycle-bin/*` 全部 404，已从本套件删除）。

---

## 0. 当前环境状态（重要，先读）

执行 `docker ps` 当前只看到：

```
tdyw-test / tdyw-kkfileview-test / tdyw-db-test
```

- **生产容器 `tdyw` 当前未运行**，`localhost:80` 不可达。
- **`tdyw-test` 容器在跑，但它不提供 HTTP 服务**（supervisord 未拉起 nginx/gunicorn，`supervisorctl` 连不上 socket；容器内 `127.0.0.1:80` 也拒绝连接）。它目前只用于 `manage.py` 命令（迁移/测试），这正是我们能在里面建账号、跑 Django 测试客户端的原因。
- 因此**现在还不能直接 `python -m locust` 打到任何地址**。必须先让一个 Web 容器对外提供服务（见第 2 节）。

---

## 1. 文件清单

| 文件 | 作用 |
|---|---|
| `document_stress.py` | **主脚本**：资料库 CRUD + 普通上传 + 分片上传/合并（含断点续传）+ 传输列表 + 磁盘使用 + 上传压力探针 + DB 连接池健康 |
| `account_login_stress.py` | **登录并发脚本**：高并发打 `/api/account/login/`，测登录吞吐与延迟 |
| `tools/create_stress_accounts.py` | 创建专用压测账号 + 角色（幂等，可重复执行） |
| `tools/verify_http.py` | 冒烟测试：真实 HTTP 走一遍 login→建文件夹→上传→分片→合并→清理，验证脚本参数是否正确 |
| `README.md` | 本文件 |

已删除的死脚本：`locustfile.py`（回收站）、`locustfile_recycle_bin.py`（回收站）、`运行命令行.txt`（端口/接口已过期）。

---

## 2. 压测环境：两种方案（二选一，需你拍板）

### 方案 A：打生产 `tdyw`（localhost:80）
- 启动 `tdyw` 容器栈（`docker compose up -d tdyw`，或你平时的启动方式）。
- 优点：开箱即用，端口 `localhost:80`。
- 缺点：**压测会写真实数据库、占真实业务资源**。虽然专用账号在独立租户 `stress` 下数据隔离，但 DB 负载是共享的。
- 运行：`-H http://localhost:80`。
- 账号需在**生产库**建（见第 3 节，目标环境确定后我帮你建到对应库）。

### 方案 B：让 `tdyw-test` 对外提供 HTTP（推荐，完全隔离）
- `tdyw-test` 有**独立数据库** `tdyw-db-test`，与生产零耦合，是最理想的压测环境。
- 当前它没起 Web，需要手动拉起（gunicorn + redis + celery-merge）：
  ```bash
  # 在 tdyw-test 内启动 redis（合并任务依赖）
  docker exec -d tdyw-test redis-server --bind 127.0.0.1 --port 6379

  # 启动 gunicorn（容器 80 端口，对应宿主机 8080）
  docker exec -d tdyw-test gunicorn -c /data/spug/spug_api/gunicorn.conf.py \
      --chdir /data/spug/spug_api -b 0.0.0.0:80 spug.wsgi:application

  # 启动合并 worker（让分片合并真正落地成文件；不启则合并接口仍返回 task_id，只是文件不生成）
  docker exec -d tdyw-test celery -A spug worker -l info -Q document.merge \
      -n merge-worker@%h --concurrency=2 --prefetch-multiplier=1
  ```
  > 注意：`-c` 必须用**绝对路径**（`gunicorn.conf.py` 相对路径在 `docker exec` 下解析不到）。
- 启动后用 `tools/verify_http.py`（把 `BASE` 改成 `http://localhost:8080`）确认连通。
- 运行：`-H http://localhost:8080`。

> 无论选哪个，`tdyw-test` 里已经建好的 `st_press_01..05` 账号只在它的库里；若选方案 A，账号要建到生产库。

---

## 3. 专用压测账号

已在 `tdyw-test` 库创建（方案 B 直接用；方案 A 需重建到生产库）：

```
租户隔离标识: stress
账号: st_press_01 .. st_press_05
密码: Stress@2026
角色: 压测专用角色（仅授予 document.document.* 需要的权限：
      view / create_folder / upload / delete / download / move / copy / rename）
```

重建/同步到其他环境（在目标容器内执行）：
```bash
docker cp locustfile/tools/create_stress_accounts.py <目标容器>:/tmp/csa.py
docker exec <目标容器> cat /tmp/csa.py | docker exec -i <目标容器> \
    python /data/spug/spug_api/manage.py shell
```

> **账号锁定提醒**：`apps/account/views.py` 的 `login` 有防暴破限流——
> IP 级 1 小时内失败 ≥30 次拒绝；用户级 15 分钟内失败 ≥5 次锁 15 分钟。
> 本套件**只用正确密码**，不会产生失败计数，可安全高并发；切勿在脚本里填错密码。

---

## 4. 如何运行（Windows，已装 locust 2.43.3，用 `python -m locust`）

```powershell
# 资料库主压测（Web 模式，手动调并发）
python -m locust -f locustfile/document_stress.py -H http://localhost:8080

# 登录并发压测
python -m locust -f locustfile/account_login_stress.py -H http://localhost:8080

# 命令行无人值守模式
python -m locust -f locustfile/document_stress.py -H http://localhost:8080 `
    --headless -u 50 -r 10 -t 10m --csv=document_stress
```

- 不要直接敲 `locust`（命令没进 Windows PATH），用 `python -m locust`。
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
- **遗留分片目录**：若 celery-merge 没跑（方案 B 未启 worker），分片目录（`storage/document_chunks`）可能残留。手动清理：
  ```bash
  docker exec <容器> sh -c 'rm -rf /data/spug/spug_api/storage/document_chunks/*'
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
docker stats tdyw-test tdyw-db-test

# 2. DB 连接池（项目自带，无需密码，最直接）
curl -s http://localhost:8080/api/document/health/db-pool/ | python -m json.tool
curl -s http://localhost:8080/api/document/health/db-pool/metrics/ | python -m json.tool

# 3. MySQL 进程/连接（用容器自身环境变量，避免硬编码密码）
docker exec tdyw-db-test sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SHOW PROCESSLIST; SHOW STATUS LIKE \"Threads_connected\";"'

# 4. 慢查询（进 db 容器开 general/slow log 或事后查）
docker exec tdyw-db-test sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -e "SHOW GLOBAL STATUS LIKE \"Slow_queries\";"'

# 5. Gunicorn/Celery 日志
docker exec tdyw-test sh -c 'tail -f /data/spug/spug_api/logs/*.log'
```

> 瓶颈通常在服务端：MariaDB 连接打满、慢查询、Gunicorn worker 饱和、CPU/内存。
> 只有 locust 客户端指标（RPS/响应时间/失败率）看不出“为什么慢”，必须配合上面服务端监控。

---

## 9. 已知限制 / 注意事项

1. **回收站相关接口全部不存在**，不要在任何脚本里再出现 `/recycle-bin/*`。
2. **账号锁定**：只用正确密码；错密码 5 次/15 分钟锁账号。
3. **合并是异步**：`merge_chunks` 返回 `task_id`，文件由 celery-merge worker 落地；压测前确认该 worker 在跑，否则“上传成功”的文件不会出现。
4. **`tdyw-test` 默认不提供 HTTP**，需按第 2 节方案 B 手动拉起（或改用方案 A 生产容器）。
5. 分片上传为单线程顺序上传（避免多线程共用 `self.client` session 的线程安全问题）；如需测“单文件并发分片”，后续可加。

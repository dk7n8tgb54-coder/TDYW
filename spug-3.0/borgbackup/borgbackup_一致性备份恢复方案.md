# TDYW BorgBackup 一致性备份与恢复方案

> **场景**：内网 Linux 单机 Docker 部署的 CRUD 系统，数据库与文件均以 Docker volume 保存。单服务器，RAID1（两块 300G 盘，剩余约 166G），约 38 人使用。已有 U 盘 1 个 + 老 PC 1 台可作异地备份目标，borgbackup 已在 Linux 主机安装完成。
>
> 本方案以 [BorgBackup](https://www.borgbackup.org/) 为**归档与容灾终态方案**，继承 `backups/backup_set_create.sh` / `backup_set_restore.sh` 已验证的一致性停写窗口理念。

---

## 1. 方案定位与选型结论

### 1.1 为什么用 Borg（针对本场景）

166G 剩余空间 + 生产 documents/media 数十 GB + 每日全量备份——纯 tar 方案 30 天会撑爆磁盘。Borg 的**块级去重**正好解决空间瓶颈，是 Linux 单机去重备份的事实标准。

| 能力 | 旧 tar 方案 | Borg 方案 |
|---|---|---|
| 跨备份集去重 | 无（每集独立全量） | 块级去重，增量体积 ≈ 实际变化量 |
| 完整性校验 | SHA-256（事后，单文件损坏难定位） | `borg check --verify-data`（端到端，定位并剔除损坏块） |
| 异地传输 | rsync 全集 | `borg create ssh:repo`（只传去重后增量块） |
| 加密 | 需额外工具 | 内置 AES-256（按介质分级启用） |
| 独立可恢复 | 每个 backup_set 独立 | 每个 archive 独立快照（去重对用户透明） |
| 保留策略 | `select_retention_chains.py` | `borg prune`（内置 GFS） |

### 1.2 选型结论（经多轮讨论确定）

1. **数据库层：mariadump 逻辑备份为主，mariabackup 日常砍掉**。38 人小库（几 GB），逻辑 dump 几分钟出活、产物小、可跨版本可单表恢复；物理备份的"大库快速恢复"价值用不上，反而吃空间 + 增加运维负担。mariabackup 仅在库涨到几十 GB 且 RTO 严格时再引入。
2. **归档层：Borg 为终态方案**。不是过渡，不是辅助，是日常备份的归档后端。
3. **tar 不作每日并行**。纯 borg 没有重大缺陷，每日双跑两套是维护负担。tar 降为**季度手动导出**（`borg export-tar`）的低频异构冗余，详见 §11。
4. **本地 repo 加密**：`--encryption=repokey-blake2`。虽同机，加密能兜底"repo 被直接拷走/硬盘维修/误传"场景；passphrase 从 0600 文件 `source` 进环境变量，不进 argv。
5. **单一本地 repo**：目前只用 `/data/borg_repo` 一个加密 repo。U 盘 `borg export-tar` 导出 tar 作为可选的物理带离副本（见 §6.2），不作为日常自动任务。

### 1.3 不变的核心原则（继承自 backup_set 方案）

1. **同一停写窗口**：DB dump 与 documents/media 快照必须来自同一"应用已冻结"时间点。Borg 不能跨过冻结逻辑直接备份运行中数据。
2. **禁止直接备份运行中的 `/var/lib/mysql`**：InnoDB 运行时不一致，必须用 `mariadb-dump --single-transaction` 导出。
3. **密码只从 0600/0400 cnf 读取**：MariaDB 凭据不进 argv/环境变量/日志；Borg passphrase 从 0600 文件 `source` 进环境变量，不进 argv。
4. **原子发布**：archive 在 `borg create` 成功且 `borg check --repository-only` 通过后才视为有效；失败 archive 立即 `borg delete`。
5. **失败保护**：`trap` 保证任何失败/信号都尝试恢复应用容器；失败 archive 不残留。
6. **单一全量可独立恢复**：每个 archive 都是可独立恢复的完整快照，不依赖父备份。

---

## 2. 一致性原理（与 backup_set 完全一致）

```
acquire .backup.lock
  → preflight（borg repo 可写性、cnf 权限、容器运行、volume 解析、磁盘空间）
  → 停 nginx / spug-api / spug-api-upload / spug-ws（阻断新入口）
  → 停 celery beat（阻断定时任务）
  → graceful stop 全部 celery worker（排空当前任务）
  → 停 tdyw 应用容器（DB 容器保持运行）
  → mariadb-dump --single-transaction（一致性视图导出 DB）
  → 从宿主机只读访问 documents/media volume mountpoint（应用已停，无写入）
  → borg create（dump 文件 + documents 卷 + media 卷 + manifest）→ 一个 archive
  → borg check --repository-only（快速校验）
  → 启动 tdyw + 等待健康检查
  → borg prune（GFS 保留策略）
```

冻结窗口内 DB 与文件都不再被业务写入，dump 与卷快照天然一致。Borg 只是把这一致状态去重存档。

---

## 3. 环境准备

### 3.1 确认 Borg 已安装

```bash
borg --version          # 应 ≥ 1.2.x（推荐 1.2.6+）
command -v borg         # /usr/bin/borg 或 /usr/local/bin/borg
```

> 离线安装包位于 `e:\TDYW\borgbackup_deb\`（58 个 .deb），`sudo dpkg -i *.deb` 安装。**Borg 1.2 与 1.4 仓库格式不兼容**，跨大版本升级前先 `borg transfer` 或保持同版本。

### 3.2 准备本地 Borg 仓库（加密）

单一本地 repo，`repokey-blake2` 加密。虽同机，加密能兜底"repo 被直接拷走/硬盘维修/误传"场景。放 RAID1 上，作为恢复源。

```bash
sudo mkdir -p /data/borg_repo
sudo chown -R $(id -u):$(id -g) /data/borg_repo
sudo chmod 700 /data/borg_repo
BORG_PASSPHRASE='<强随机口令>' borg init --encryption=repokey-blake2 /data/borg_repo
```

> 若 `/data/borg_repo` 已 init 过，跳过本步。init 只做一次。

### 3.3 保护 passphrase

```bash
# passphrase 写入 0600 文件，脚本 source 后进环境变量（不进 argv）
# heredoc 用单引号 'EOF' 包裹，变量不被 shell 解析，可原样写入
sudo install -m 600 /dev/stdin /opt/docker/borgbackup/borg.env <<'EOF'
BORG_REPO=/data/borg_repo
BORG_PASSPHRASE=<强随机口令>
EOF
```

> **passphrase 必须离线保存**（打印纸质 / 另一个 U 盘），与生产机物理分离。repo 加密后，丢失 passphrase = 丢失全部备份。

### 3.4 复用 MariaDB 凭据

直接复用现有 `/opt/docker/borgbackup/tdyw_backup.cnf`（备份）与 `/opt/docker/borgbackup/tdyw_restore.cnf`（恢复），权限 0600。Borg 方案不新增 DB 凭据。

### 3.5 确定 documents/media volume 的宿主机路径

```bash
docker volume ls | grep -E 'documents|media'
docker volume inspect -f '{{.Mountpoint}}' spug_documents   # /var/lib/docker/volumes/spug_documents/_data
docker volume inspect -f '{{.Mountpoint}}' spug_media        # /var/lib/docker/volumes/spug_media/_data
```

脚本通过环境变量 `DOCUMENTS_VOLUME` / `MEDIA_VOLUME` 指定 volume 名，运行时 inspect 解析为宿主路径。**冻结后只读访问**，无需 `--volumes-from`。

---

## 4. 备份方案

### 4.1 流程

```
borg_backup_set_create.sh
  ├─ acquire_maintenance_lock（复用 .backup.lock，与 backup_set 互斥）
  ├─ preflight：borg 命令、本地 repo 可写、cnf 权限、容器运行、volume 解析、磁盘空间、远程连通性
  ├─ DRY_RUN=YES：只 preflight + 打印计划，不冻结不创建 archive
  ├─ freeze_application：停入口→beat→worker→tdyw 容器（DB 保持运行）
  ├─ backup_database_logical：mariadb-dump --single-transaction → database.sql.gz
  ├─ build_manifest：archive 元数据（DB 版本/git commit/冻结时长/volume 路径）
  ├─ borg_create_local：
  │     borg create --stats --compression zstd,3 \
  │       --exclude '*/__pycache__' --exclude '*/.cache' --exclude '*/document_chunks' \
  │       ${BORG_REPO}::tdyw-{now} ${DUMP_FILE} ${docs_mp} ${med_mp} ${MANIFEST}
  ├─ borg_check_archive：borg check --repository-only（快速）
  ├─ restore_application：启动 tdyw + 健康检查
  ├─ borg_prune：本地 GFS 保留
  ├─ borg_push_remote（PUSH_REMOTE=YES 时）：
  │     BORG_REPO=${BORG_REMOTE_REPO} BORG_PASSPHRASE=${BORG_REMOTE_PASSPHRASE} \
  │       borg create ::${ARCHIVE} ${DUMP_FILE} ${docs_mp} ${med_mp} ${MANIFEST}
  │     borg prune --keep-monthly=12 ...（老 PC 保留更宽松）
  └─ trap：失败时 borg delete 未完成 archive + 恢复 app
```

### 4.2 关键设计决策

1. **不打包 tar 中间层**：Borg 直接吃 documents/media 卷的原始目录树，享受文件级 + 块级去重。tar 头部元数据每次变化会破坏去重。
2. **dump 文件单独存为 archive 成员**：恢复时可只 extract dump，不解压整个卷。
3. **archive 命名**：`tdyw-YYYYMMDD-HHMMSS`，时间戳即 backup_set_id。
4. **冻结后第一时间 dump**：缩短应用停机时间。
5. **`--exclude`**：排除 `__pycache__`、`.cache`、`logs`、临时分片 `document_chunks`（与现有 `print_plan` 排除项一致）。
6. **本地 repo 无加密、远程 repo 加密**：按介质分级，本地省 passphrase 管理，远程防外泄。
7. **远程推送独立 archive**：不依赖本地 repo 拷贝，老 PC repo 独立可恢复（即使本地 repo 全毁，老 PC 仍能恢复）。
8. **远程推送在 restore_application 之后**：先恢复生产服务（解冻），再后台推老 PC，缩短业务停机窗口。

### 4.3 备份脚本核心片段

> 落地为 `borgbackup/borg_backup_set_create.sh`，风格对齐 `backups/backup_set_create.sh`（`set -Eeuo pipefail`、`umask 077`、`trap cleanup EXIT`、`flock`）。freeze 部分直接复用 backup_set 的 `stop_supervisor_programs` 逻辑。下面只列 Borg 相关核心片段。

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# ... 变量定义（APP_CONTAINER/DB_CONTAINER/BORG_REPO/BORG_REMOTE_REPO/PUSH_REMOTE 等） ...

# load_borg_env：source /opt/docker/borgbackup/borg.env（0600），校验 BORG_REPO 非空
# resolve_volumes：docker volume inspect 解析 DOCUMENTS_VOLUME/MEDIA_VOLUME 的 Mountpoint
# preflight：borg/docker/flock 命令、容器运行、cnf 权限、本地 repo 可写、磁盘 ≥15%、远程连通性
# freeze_application：复用 backup_set stop_supervisor_programs + docker stop tdyw（DB 保持运行）
# restore_application：docker start/restart tdyw + 等待 healthcheck

backup_database_logical() {
    # mariadb-dump --single-transaction --routines --triggers --events --quick --hex-blob
    # --default-character-set=utf8mb4 --set-charset --skip-lock-tables
    # 通过 --defaults-extra-file=<0600 cnf> 传凭据，gzip -c > database.sql.gz
    # 校验：非空 + gzip -t + zgrep CREATE TABLE
}

borg_create_local() {
    borg create --stats --compression "${BORG_COMPRESSION}" \
        --exclude '*/__pycache__' --exclude '*/.cache' --exclude '*/logs' \
        --exclude '*/document_chunks' \
        "${BORG_REPO}::${ARCHIVE_NAME}" \
        "${DUMP_FILE}" "${DOCS_MP}" "${MED_MP}" "${MANIFEST_FILE}"
    LOCAL_ARCHIVE_CREATED=1
    borg check --repository-only "${BORG_REPO}"
    borg list "${BORG_REPO}::${ARCHIVE_NAME}" >/dev/null
}

borg_push_remote() {
    is_yes "${PUSH_REMOTE}" || return 0
    BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" \
    BORG_RSH="ssh -i /opt/docker/borgbackup/oldpc_ed25519 -o BatchMode=yes" \
        borg create --stats --compression "${BORG_COMPRESSION}" \
        --exclude '*/__pycache__' --exclude '*/.cache' --exclude '*/logs' \
        --exclude '*/document_chunks' \
        "${BORG_REMOTE_REPO}::${ARCHIVE_NAME}" \
        "${DUMP_FILE}" "${DOCS_MP}" "${MED_MP}" "${MANIFEST_FILE}"
    REMOTE_ARCHIVE_CREATED=1
    BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" BORG_RSH="ssh -i ..." \
        borg prune --list "${BORG_REMOTE_REPO}" --prefix 'tdyw-' \
        --keep-within=7d --keep-daily=14 --keep-weekly=8 --keep-monthly=12
}

cleanup() {
    local rc=$?
    trap - EXIT INT TERM; set +e
    # 失败时删除未完成 archive（本地 + 远程）
    [ "${LOCAL_ARCHIVE_CREATED}" -eq 1 ] && [ "${rc}" -ne 0 ] && \
        borg delete --stats "${BORG_REPO}::${ARCHIVE_NAME}" >/dev/null 2>&1 || true
    [ "${REMOTE_ARCHIVE_CREATED}" -eq 1 ] && [ "${rc}" -ne 0 ] && \
        BORG_PASSPHRASE="${BORG_REMOTE_PASSPHRASE}" borg delete --stats "${BORG_REMOTE_REPO}::${ARCHIVE_NAME}" >/dev/null 2>&1 || true
    [ "${APP_NEEDS_RESTART}" -eq 1 ] && restore_application || true
    [ -n "${RUNTIME_DIR}" ] && rm -rf -- "${RUNTIME_DIR}"
    exit "${rc}"
}
trap cleanup EXIT

main() {
    preflight
    is_yes "${DRY_RUN}" && { log "DRY_RUN: preflight only"; return 0; }
    exec 9>"${LOCK_FILE}"; flock -n 9 || fail "another backup/restore running"
    RUNTIME_DIR="$(mktemp -d /tmp/tdyw-borg.XXXXXX)"
    freeze_application
    backup_database_logical
    build_manifest
    borg_create_local          # 本地 archive + check
    restore_application        # 先解冻恢复生产服务
    borg_prune_local           # 本地 GFS
    borg_push_remote           # 再推老 PC（业务已恢复，不影响停机）
    log "borg backup published: ${BORG_REPO}::${ARCHIVE_NAME}"
}
```

### 4.4 执行备份

```bash
# dry-run（只 preflight）
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
DOCUMENTS_VOLUME=spug_documents MEDIA_VOLUME=spug_media \
./borgbackup/borg_backup_set_create.sh

# 正式备份（本地 + 推老 PC）
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
DOCUMENTS_VOLUME=spug_documents MEDIA_VOLUME=spug_media \
DRY_RUN=NO ./borgbackup/borg_backup_set_create.sh
```

---

## 5. 恢复方案

### 5.1 三种模式（对齐 backup_set_restore.sh）

| 模式 | 命令 | 作用 |
|---|---|---|
| 只校验 | `borg_backup_set_restore.sh <archive>` | `borg check` + `borg list` + 打印恢复计划，不改数据 |
| 隔离演练 | `--mode drill <archive>` | extract 到 `/tmp/tdyw-restore-drill`，逻辑恢复到 `tdyw_restore` 库，容器名须含 `test` |
| 生产恢复 | `--mode production <archive>` | 停 app → 恢复 DB → 替换 documents/media → 启 app + 健康检查 |

### 5.2 恢复流程（production）

```
resolve_archive（borg list 确认存在）
  → acquire_maintenance_lock（共享 .backup.lock）
  → 可选 borg check --verify-data（慢但最彻底，确认块无腐烂）
  → 停 tdyw 应用容器
  → 逻辑恢复 DB：
      borg extract --stdout repo::archive <dump 路径> | gunzip | \
        mariadb --defaults-extra-file=tdyw_restore.cnf（DROP+CREATE+导入）
  → 文件恢复（暂存 + 校验 + 替换 + 失败回滚）：
      borg extract repo::archive <documents mountpoint> → 临时目录
      rsync --delete -a 临时目录/ volume mountpoint/
  → 启动 tdyw + 健康检查
  → 失败时 app 保持停止，不自动启动不一致系统
```

### 5.3 关键设计决策

1. **DB 走逻辑恢复**：`borg extract --stdout` 把 dump 流式喂给 `mariadb`，无需落地大文件。DROP+CREATE 复用 `mariadump_restore.sh` 逻辑。
2. **文件恢复用暂存替换**：不直接 `borg extract` 覆盖 volume（中途失败污染原数据）。先 extract 到同盘临时目录，rsync `--delete` 原子替换。
3. **`--verify-data` 仅演练/恢复前可选**：生产恢复前可跑一次完整校验（耗时，但确认块无腐烂）。
4. **可从老 PC 恢复**：若本地 repo 全毁，`BORG_REPO=backup@oldpc:/data/borg/tdyw BORG_PASSPHRASE=<远程口令>` 切换源即可，流程不变。

### 5.4 `borg extract` 路径注意事项

`borg create` 传入的是 volume **绝对 mountpoint 路径**，`borg extract` 默认在**当前目录**下重建该完整路径树。因此：

- **不要在 `/` 下直接 extract**（会写回原位，中途失败污染原数据）；
- 在专用临时目录 extract，得到 `临时目录/var/lib/docker/volumes/.../_data/...`，再 `rsync --delete` 到真实 mountpoint；
- 或用 `borg mount` FUSE 挂载后选择性拷贝（更直观，但需 `fuse` 内核模块）。

```bash
mkdir -p /tmp/restore-root && cd /tmp/restore-root
borg extract "${BORG_REPO}::${ARCHIVE}" "${docs_mp}"
rsync -a --delete "/tmp/restore-root${docs_mp}/" "${docs_mp}/"
```

### 5.5 执行恢复

```bash
# 只校验
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
./borgbackup/borg_backup_set_restore.sh tdyw-20260727-030000

# 隔离演练
APP_CONTAINER=tdyw-test DB_CONTAINER=tdyw-db-test \
RESTORE_CLIENT_CNF=/opt/docker/borgbackup/restore-test-admin.cnf \
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
./borgbackup/borg_backup_set_restore.sh --mode drill tdyw-20260727-030000

# 生产逻辑恢复
RESTORE_CLIENT_CNF=/opt/docker/borgbackup/tdyw_restore.cnf \
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
./borgbackup/borg_backup_set_restore.sh --mode production tdyw-20260727-030000
```

---

## 6. 3-2-1 异地落地

### 6.1 三副本定位

| 副本 | 介质 | 位置 | 加密 | 实现 | 防什么 |
|---|---|---|---|---|---|
| 副本 1 | 生产机 RAID1 | 机房 | none | 本地 borg repo，每日 cron | 单盘损坏、快速恢复 |
| 副本 2 | U 盘 | 物理带离机房 | tar 不加密（或额外 gpg） | 每周/月 `borg export-tar` 导出，人手带离 | 整机损坏、勒索、火灾 |
| 副本 3 | 老 PC | 异机 | repokey-blake2 | 每日 `borg create ssh:oldpc:` 去重增量推送 | 整机损坏、勒索 |

**老 PC 位置决定容灾等级**：
- 老 PC 在**同一机房/同一建筑** → 算"异机"，防单机硬件损坏、防 `rm -rf`、防勒索（前提勒索未横向到老 PC）；**不防**火灾/盗窃。
- 老 PC 在**另一地点**（家里/另一栋楼） → 算"真异地"，3-2-1 完整成立，防火灾/盗窃。建议老 PC 放另一地点以获得真异地能力。

### 6.2 U 盘策略（按容量）

U 盘不建 borg repo（随机写伤盘 + 慢），改用 `borg export-tar` 导出 tar.gz，顺序写友好、任何机器可读：

```bash
# 挂载 U 盘
sudo mount /dev/sdX1 /mnt/usb

# 策略 A：U 盘 ≥ 单次全量数据（documents+media < U盘容量）
#   导出完整 archive（含 documents+media+dump）
BORG_REPO=/data/borg_repo borg export-tar \
    ::tdyw-$(date -u +%Y%m%d-%H%M%S) /mnt/usb/tdyw-$(date +%Y%m%d).tar.gz

# 策略 B：U 盘较小（容不下完整 archive）
#   只导出数据库 dump（最关键、最小、无可替代），文件靠老 PC 兜底
mkdir -p /tmp/usb-dump && cd /tmp/usb-dump
BORG_REPO=/data/borg_repo borg extract \
    ::tdyw-$(date -u +%Y%m%d-%H%M%S) path/to/database.sql.gz
tar czf /mnt/usb/tdyw-db-$(date +%Y%m%d).tar.gz database.sql.gz
```

导出后**人手把 U 盘带离机房**（带回家/放保险柜），不要留在机房抽屉（火灾一起毁）。

### 6.3 passphrase + key 离线保存

- passphrase 打印一份纸质 + 存另一个 U 盘，与生产机物理分离；
- 老 PC 的 SSH 私钥 `/opt/docker/borgbackup/oldpc_ed25519` 也备份一份离线；
- **丢失 passphrase = 丢失老 PC 全部备份**，这是加密的代价，必须离线冗余。

---

## 7. 保留策略（borg prune）

GFS（Grandfather-Father-Son）策略：

```bash
# 本地 repo（快速恢复源，保留短）
borg prune --list "${BORG_REPO}" --prefix 'tdyw-' \
    --keep-within=2d \   # 最近 2 天全保留（误删快速回滚）
    --keep-daily=7  \    # 每天 1 份，留 7 天
    --keep-weekly=4 \    # 每周 1 份，留 4 周
    --keep-monthly=6     # 每月 1 份，留 6 个月

# 老 PC repo（异地容灾，保留长）
borg prune --list "${BORG_REMOTE_REPO}" --prefix 'tdyw-' \
    --keep-within=7d --keep-daily=14 --keep-weekly=8 --keep-monthly=12
```

- `--keep-within=2d` 防当天多次备份被 prune 误删；
- **prune 只标记删除，不立即释放空间**，需 `borg compact` 才回收孤儿段；
- U 盘 tar 导出按文件名日期手动清理（`find /mnt/usb -name 'tdyw-*.tar.gz' -mtime +90 -delete`）。

```bash
# 每周一次 compact（低峰期）
borg compact --cleanup-commits "${BORG_REPO}"
```

---

## 8. 完整性校验（borg check）+ RAID1 scrub

### 8.1 borg check 分级

| 频率 | 命令 | 作用 | 耗时 |
|---|---|---|---|
| 每次备份后 | `borg check --repository-only` | 校验 repo 索引一致性 | 秒级 |
| 每月 | `borg check --verify-data` | 校验所有块哈希，检测位腐烂 | 分钟~小时级 |
| 每季度 | 老 PC repo `borg check --verify-data` | 异地副本完整性 | 视网络 |

> `--verify-data` 读取所有块重算哈希，是检测存储静默损坏（bitrot）的手段。本地 tar 方案做不到。

### 8.2 RAID1 scrub（位腐烂第一道防线，borg 之外的独立任务）

RAID1 若从不 scrub，两块盘可能各自静默腐烂到不一致而无人知。每月一次校验同步：

```bash
# 先查阵列名（md0/md1/...）
cat /proc/mdstat

# 触发 scrub（后台运行，不中断服务）
echo check > /sys/block/md0/md/sync_action

# 查进度与结果（完成后 mismatch_cnt 应为 0）
watch -n 5 'cat /sys/block/md0/md/sync_action; cat /sys/block/md0/md/mismatch_cnt'
```

加进 cron，每月 1 号：

```cron
# 每月 1 号 03:00 RAID1 scrub
0 3 1 * * root echo check > /sys/block/md0/md/sync_action
```

> `mismatch_cnt > 0` 说明两盘数据不一致，需排查哪块盘出错（smartctl / 换盘重建）。

---

## 9. 失败保护与 trap（对齐 backup_set）

- `trap cleanup EXIT`：任何失败/信号都 `borg delete` 未完成 archive（本地 + 远程）+ `restore_application` + 清理临时目录；
- `flock` 共享 `.backup.lock`，与 `backup_set_*` 互斥，绝不并发备份/恢复；
- DRY_RUN 不获取锁、不冻结、不创建 archive；
- 失败 archive 不残留（`LOCAL_ARCHIVE_CREATED=1` 且 `rc!=0` 时删除），避免 `borg list` 出现半成品；
- 生产恢复失败时 **app 保持停止**，不自动启动"DB 已恢复但文件未恢复"的系统（与 `backup_set_restore.sh` 一致）。

---

## 10. 调度

```cron
# 每天 02:00 Borg 一致性备份（本地 + 推老 PC）
0 2 * * * cd /opt/tdyw/spug-3.0 && BORG_ENV_FILE=/opt/docker/borgbackup/borg.env DOCUMENTS_VOLUME=spug_documents MEDIA_VOLUME=spug_media DRY_RUN=NO ./borgbackup/borg_backup_set_create.sh >> /var/log/tdyw-backup/borg_backup.log 2>&1

# 每月 1 号 03:00 RAID1 scrub
0 3 1 * * root echo check > /sys/block/md0/md/sync_action

# 每月 1 号 04:00 borg verify-data（检测位腐烂）
0 4 1 * * BORG_ENV_FILE=/opt/docker/borgbackup/borg.env borg check --verify-data /data/borg_repo >> /var/log/tdyw-backup/borg_check.log 2>&1

# 每周日 05:00 compact 回收空间
0 5 * * 0 BORG_ENV_FILE=/opt/docker/borgbackup/borg.env borg compact --cleanup-commits /data/borg_repo >> /var/log/tdyw-backup/borg_compact.log 2>&1
```

> **与 backup_set 错峰**：两者共享 `.backup.lock`，调度时间不可重叠。若保留 backup_set 作为季度导出源，其 cron 可降为低频或停用。

---

## 11. tar 的定位（季度手动导出，异构冗余）

纯 borg 没有重大缺陷，日常不并行 tar。但 borg repo 有"格式锁定 + 工具链依赖"的极端叠加风险（概率很低但非零）。tar 作为**异构技术栈兜底**，降为低频手动导出：

```bash
# 每季度一次，从最新本地 archive 导出 tar 到移动硬盘/U 盘
BORG_REPO=/data/borg_repo borg export-tar \
    ::tdyw-YYYYMMDD-HHMMSS /mnt/usb/quarterly-tdyw-$(date +%Y%m).tar.gz
```

- 导出的 tar 是裸文件，任何 Linux 能读，不依赖 borg；
- 兼得"borg 去重日常备份 + tar 异构季度兜底"；
- 不背每日双跑两套的运维负担。

> 这是 nice-to-have 不是 must-have。若运维资源紧张，此项可省略，老 PC repo 已提供异机冗余。

---

## 12. 演练与每日检查

### 12.1 每日检查

```bash
tail -n 200 /var/log/tdyw-backup/borg_backup.log
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env borg list /data/borg_repo | tail -10
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env borg info /data/borg_repo::tdyw-$(date -u +%Y%m%d)* | grep -E 'Archive|Deduplicated|Time'
# 确认老 PC 推送成功
BORG_PASSPHRASE='<远程口令>' BORG_RSH='ssh -i /opt/docker/borgbackup/oldpc_ed25519' \
    borg list backup@oldpc:/data/borg/tdyw | tail -5
```

### 12.2 月度演练（drill）

```bash
APP_CONTAINER=tdyw-test DB_CONTAINER=tdyw-db-test \
RESTORE_CLIENT_CNF=/opt/docker/borgbackup/restore-test-admin.cnf \
BORG_ENV_FILE=/opt/docker/borgbackup/borg.env \
./borgbackup/borg_backup_set_restore.sh --mode drill tdyw-YYYYMMDD-HHMMSS
```

记录：恢复耗时、表数量、documents/media 文件数与抽样 SHA-256、应用健康状态。drill 通过后才允许动用 Borg 方案做生产恢复。

---

## 13. 安全注意事项

1. **passphrase 不进 argv**：通过 `source borg.env` → `BORG_PASSPHRASE` 环境变量，`/proc/<pid>/environ` 仅 root 可读；
2. **cnf 权限 0600**：`tdyw_backup.cnf` / `tdyw_restore.cnf` / `borg.env` / `oldpc_ed25519` 均强制 0600/0400，preflight 校验；
3. **borg repo 目录权限**：`/data/borg_repo` 属主为备份用户，`chmod 700`；
4. **SSH 老 PC**：专用 `backup` 账号 + `command="borg serve --restrict-to-path ..."` 限制，禁 shell；
5. **不在 Git 提交**：`borg.env` / `*.cnf` / `oldpc_ed25519*` 全部 gitignore；
6. **archive 不含密码**：manifest 只记录 DB 版本/git commit，不记录任何凭据；
7. **本地 repo 无加密的取舍**：同机加密不防勒索（勒索会连 repo 一起加密），所以本地 none 是诚实选择；真正的防外泄靠 U 盘/老 PC 的加密。

---

## 14. 附录：Borg 常用命令速查

```bash
# 列出所有 archive
borg list ${BORG_REPO}

# archive 详情（去重前后大小、耗时）
borg info ${BORG_REPO}::tdyw-20260727-030000

# FUSE 挂载浏览（无需 extract）
mkdir -p /mnt/borg && borg mount ${BORG_REPO} /mnt/borg
ls /mnt/borg/tdyw-20260727-030000/
fusermount -u /mnt/borg

# 流式提取 dump 到 mariadb（生产恢复核心命令）
borg extract --stdout ${BORG_REPO}::tdyw-20260727-030000 path/to/database.sql.gz \
    | gunzip | docker exec -i tdyw-db mariadb tdyw

# 删除单个 archive
borg delete ${BORG_REPO}::tdyw-20260727-030000

# 仓库完整性校验（快）
borg check --repository-only ${BORG_REPO}

# 仓库完整性校验（慢，检测位腐烂）
borg check --verify-data ${BORG_REPO}

# 保留策略裁剪
borg prune --list ${BORG_REPO} --prefix 'tdyw-' \
    --keep-within=2d --keep-daily=7 --keep-weekly=4 --keep-monthly=6

# 回收空间
borg compact ${BORG_REPO}

# 导出为 tar（U 盘 / 季度异构冗余）
borg export-tar ${BORG_REPO}::tdyw-20260727-030000 /mnt/usb/tdyw-20260727.tar.gz

# 切换源到老 PC 恢复（本地 repo 全毁时）
BORG_REPO=backup@oldpc:/data/borg/tdyw BORG_PASSPHRASE='<远程口令>' \
    BORG_RSH='ssh -i /opt/docker/borgbackup/oldpc_ed25519' \
    borg list backup@oldpc:/data/borg/tdyw
```

---

## 15. 落地清单

- [ ] 生产机 `borg --version` ≥ 1.2，老 PC borg 版本 ≥ 生产机
- [ ] `/opt/docker/borgbackup/borg.env`（0600，含 `BORG_REPO` / `BORG_REMOTE_REPO` / `BORG_REMOTE_PASSPHRASE`）
- [ ] `borg init --encryption=none` 本地 repo + `borg init --encryption=repokey-blake2` 老 PC repo
- [ ] 老 PC backup 账号 + `borg serve --restrict-to-path` + authorized_keys 限制
- [ ] 生产机 SSH 免密到老 PC（ed25519，0600）
- [ ] `tdyw_backup.cnf` / `tdyw_restore.cnf` 已就位（复用现有）
- [ ] `DOCUMENTS_VOLUME` / `MEDIA_VOLUME` 名确认（`docker volume inspect`）
- [ ] `borg_backup_set_create.sh` dry-run 通过
- [ ] 首次正式备份 + `borg check --repository-only` + 确认老 PC archive 存在
- [ ] drill 模式恢复演练（隔离容器）
- [ ] cron 调度（备份 + RAID1 scrub + verify-data + compact）
- [ ] passphrase + SSH 私钥离线保存（纸质 + 另一个 U 盘）
- [ ] U 盘首次 `borg export-tar` 导出 + 物理带离机房
- [ ] 确认老 PC 放置位置（机房内=异机级 / 另一地点=真异地级）

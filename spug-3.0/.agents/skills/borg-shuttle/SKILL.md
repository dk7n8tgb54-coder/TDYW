---
name: borg-shuttle
description: 把生产服务器的 TDYW borg 备份快照经 U 盘搬运到本机，导入 WSL 的 borg 仓库，再还原 tdyw 数据库与文件卷。当用户提到 borg 快照搬运、U 盘备份导入、生产快照还原、还原 tdyw 库、borg-shuttle 时使用——即使用户只说"把上次的备份搬过来还原一下"。
---

# borg-shuttle：生产 borg 快照 U 盘搬运与 tdyw 还原

四段式流程。**第 1 段（生产服务器导出）完全由用户手工完成**——执行环境接触不到生产机，skill 只提供命令参考卡；可执行流程从第 2 段（U 盘插上本机）开始。

```
[1 生产·人工]  borg extract 到 U 盘          ← 只出参考卡，不执行
[2 Windows]    U盘 → E:\TDYW\borg<MMDD>\      ← robocopy + 完整性校验
[3 WSL]        borg create 打包为 tdyw-restore-<MMDD> → borg check
[4 WSL]        borg_backup_set_restore.sh --mode production 还原 tdyw
```

## 环境事实（已核实，直接使用，勿重新探测）

- 本机 docker 在 WSL 里；Windows 侧没有 docker 命令（不是连不上 daemon，是命令本身不存在），docker 与 docker compose 一律通过 `wsl ...` 执行
- WSL 默认用户 `tdywuser`（在 docker 组），`/data` 归 root → 涉及 `/data` 的 borg 操作用 `wsl -u root bash -c '...'`
- WSL 内 borg 1.2.0；本地仓库 `/data/borg_repo`（repokey-blake2，生产 repo 的副本）
- 生产 archive 命名 `tdyw-YYYYMMDD-HHMMSS`；本段流程导入后的命名固定 `tdyw-restore-<MMDD>`
- archive 内容结构（相对路径，无前导 /）：`tmp/tdyw-borg.*/{database.sql.gz,manifest.json,binlog/}`、`data/docker/volumes/docker_tdyw-documents/_data/`、`data/docker/volumes/docker_tdyw-media/_data/`
- 生产容器/卷名与本地 dev 栈同名：`tdyw`、`tdyw-db`、`docker_tdyw-documents`、`docker_tdyw-media`
- passphrase 在仓库文件 `borgbackup/borg.env`（BORG_REPO=/data/borg_repo，已与本地 repo 匹配）
- 备份元数据以 U 盘导出物中的 `tmp/tdyw-borg.*/manifest.json` 为权威：`backup_set_id` 是真实生产快照名（U 盘目录名 MMDD 只是搬运标签，可能与快照日期不同），`database_name` / `documents_mountpoint` / `media_mountpoint` 是第 4 段计划摘要的来源
- 本地 dev 栈的 `tdyw`/`tdyw-db` 容器可能不存在（只有 test 栈常驻）；第 4 段预检时确认
- `borgbackup/borg_backup_set_restore.sh` 对 BORG_ENV_FILE 和 RESTORE_CLIENT_CNF 有 0600/0400 权限硬校验——文件必须放 WSL 原生路径（如 `/data/borgbackup/`）并 chmod 600，放 /mnt/e 下必挂（drvfs 权限位不符）
- 还原脚本 `LOCK_FILE` 默认 `/data/backups/tdyw/.backup.lock`（root 可写，无需覆盖）

## 启动：收集信息 + 断点判定

先向用户收集（能推断的先给默认值，用户确认即可）：

1. **源 archive 名**（生产上的 `tdyw-YYYYMMDD-HHMMSS`，用户在生产导出时已选定）
2. **MMDD 后缀**（默认今天，决定 `tdyw-restore-<MMDD>` 与 `E:\TDYW\borg<MMDD>`）
3. **U 盘盘符**（可先用 PowerShell 探测可移动盘：`powershell -NoProfile -Command "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2' | Select -ExpandProperty DeviceID"`，结果不确定就直接问）

**第 0 步（先于一切 borg 命令）：预置 `/data/borgbackup/borg.env`**（缺失才建，0600）——最小内容两行，值取自仓库 `borgbackup/borg.env`：

```
BORG_REPO=/data/borg_repo
BORG_PASSPHRASE=<取自 borgbackup/borg.env>
```

不带 passphrase 的 `borg list` 会停在交互输密码**永久挂起**（无输出、无超时，只能杀任务）——所以本文件里所有 `borg list` / `borg check` 统一带 env：

```
wsl -u root bash -c 'set -a; . /data/borgbackup/borg.env; set +a; borg list --short /data/borg_repo'
```

断点判定（按状态续跑，不要从头重复已完成的段）：

- `E:\TDYW\borg<MMDD>` 已存在且含标记文件（`tmp/tdyw-borg.*/database.sql.gz`、两个 `_data` 目录）→ 第 2 段已完成，从第 3 段开始（先补跑 gzip 校验）
- 本地 repo 已有 `tdyw-restore-<MMDD>`（第 0 步完成后用带 env 的 `borg list --short` 查）且用户未要求重导 → 从第 4 段开始
- 若同名 archive 已存在且用户要重导：`borg delete` 属破坏性操作，必须先向用户确认，禁止静默删除

## 第 1 段：生产导出（人工参考卡，只打印不执行）

打印给用户，等用户回复"已在生产导出完成"再进第 2 段：

```bash
# 在生产服务器上执行
borg list --short /data/borg_repo                     # 挑选要导出的快照
mkdir -p /mnt/usb/borg-export && cd /mnt/usb/borg-export
borg extract -v --list /data/borg_repo::<tdyw-YYYYMMDD-HHMMSS>
```

人工自检点（用户确认）：
- U 盘导出目录下存在 `tmp/tdyw-borg.*/database.sql.gz` 与 `manifest.json`
- 存在 `data/docker/volumes/docker_tdyw-documents/_data/` 与 `data/docker/volumes/docker_tdyw-media/_data/`
- 报出导出目录的总大小，供第 2 段比对

## 第 2 段：U 盘 → E:\TDYW\borg<MMDD>

1. **定位 U 盘上的导出根**：用 WSL find 找标记文件，避免假设目录层级（用户可能直接解在 U 盘根，也可能解在子目录）：

   ```
   wsl bash -c 'find /mnt/<盘符> -maxdepth 4 -path "*tmp/tdyw-borg.*/database.sql.gz" 2>/dev/null | head -3'
   ```
   由命中路径反推导出根（database.sql.gz 向上三级）。

2. **robocopy 拷贝**（/E 含子目录，/MT 多线程，/R:2 /W:5 限制重试；robocopy 退出码 0-7 均为成功，≥8 才是失败）：

   ```
   MSYS_NO_PATHCONV=1 robocopy '<U盘导出根>' 'E:\TDYW\borg<MMDD>' /E /MT:8 /R:2 /W:5 /NFL /NDL
   ```

   **必须加 `MSYS_NO_PATHCONV=1`**：Git Bash/MSYS 会把 `/E /R:2 /W:5` 等斜杠参数改写成 `E:/` 之类路径，robocopy 报"无效参数"退出 16（已实测踩坑）。后台包装层可能仍报整体 exit 0——判定成败只看输出里的汇总行 `FAILED = 0` 与 `ROBOCOPY_EXIT`；若数百 MB"秒完成"，先核对目标目录真实存在再谈成功。

3. **完整性校验，三项全过才算到货**：
   - robocopy 汇总行 `FAILED = 0`
   - 两侧文件数与总字节比对（在 Git Bash 侧直接做；PowerShell 内联命令的 `$` 变量会被 Git Bash 吞掉，勿用）：

     ```
     find <路径> -type f | wc -l
     find <路径> -type f -printf '%s\n' | awk '{t+=$1} END{print t}'
     ```

     源 = U 盘导出根，目标 = borg<MMDD>，文件数与字节两项必须完全相等
   - dump 完整性：`wsl bash -c 'gzip -t /mnt/e/TDYW/borg<MMDD>/tmp/tdyw-borg.*/database.sql.gz && echo GZIP_OK'`
     （gzip 校验必不可少：第 4 段是流式导入，dump 损坏要到导入中途才炸，排查代价大）

## 第 3 段：导入 WSL borg 仓库

以 root 执行（/data 归 root）；passphrase 经最小 env 文件带入，不进 argv：

1. **`/data/borgbackup/borg.env`**：第 0 步已预置则直接复用（缺失才建，0600，最小内容两行）：
   ```
   BORG_REPO=/data/borg_repo
   BORG_PASSPHRASE=<取自 borgbackup/borg.env>
   ```
2. **打包**：
   ```
   wsl -u root bash -c 'set -a; . /data/borgbackup/borg.env; set +a; borg create -v --compression zstd /data/borg_repo::tdyw-restore-<MMDD> /mnt/e/TDYW/borg<MMDD>'
   ```
   说明：重打包与生产原 archive 无去重关系，每次全量写入本地 repo（GB 级，/data 盘 880G 可用，属本流程固有成本）。`/mnt/e` 是 drvfs，读速一般，属正常现象。
   注意：`wsl bash -c` 内 `${PIPESTATUS[0]}` 之类的扩展会**静默丢失**（回显为空），不要用 exit code 回显技巧判定打包成败——成败一律以下面第 3 步的到货确认为准。
3. **到货确认**（两命令都必须带 env，否则卡交互密码）：
   - `wsl -u root bash -c 'set -a; . /data/borgbackup/borg.env; set +a; borg list --short /data/borg_repo' | grep tdyw-restore-<MMDD>` → 必须命中
   - `wsl -u root bash -c 'set -a; . /data/borgbackup/borg.env; set +a; borg check --repository-only /data/borg_repo && echo CHECK_OK'`
4. 到货后**不自动删除** `E:\TDYW\borg<MMDD>`（还原前留作应急源），完成后向用户报告大小并提示可手动清理。

## 第 4 段：还原 tdyw（破坏性，逐项预检后执行）

### 预检（全部通过才继续）

1. **容器在位**：`wsl bash -c 'docker inspect -f "{{.State.Running}}" tdyw tdyw-db'`。缺失时（常见：本地常驻的只有 test 栈，生产栈容器可能从未创建过）不要盲跑命令——按序启动，向用户说明后再执行：

   ```
   wsl bash -c 'cd /mnt/e/TDYW/spug-3.0 && docker compose -f docker/docker-compose.yml up -d tdyw-db'
   # 轮询至 healthy（约 30-60s）：
   wsl bash -c 'docker inspect -f "{{.State.Health.Status}}" tdyw-db'
   wsl bash -c 'cd /mnt/e/TDYW/spug-3.0 && docker compose -f docker/docker-compose.yml up -d tdyw'
   ```

   三个要点：① 必须在 WSL 内执行（Windows 侧无 docker 命令）；② 必须 cd 到仓库挂载路径再 compose——项目名取自 compose 文件所在目录名 `docker`，卷名才会是 `docker_tdyw-*`，env 也取自 `docker/.env`（不是仓库根 `.env`，那个不存在）；③ 还原只需 `tdyw-db` + `tdyw` 两个服务（不需要 kkfileview/onlyoffice），依赖镜像 `mysql:0601` + `tdyw:1024`。**严禁碰任何带 -test 的容器/卷（tdyw-test 栈常驻运行）**。
2. **本地 borg.env**：第 3 段已建则复用。
3. **恢复用 cnf `/data/borgbackup/tdyw_restore.cnf`**（缺失才建，0600）。本地容器 root 密码可能与生产不同，必须从容器内读，不照抄生产 cnf：
   - 读密码（`printenv` 免 `$`，绕开内联双引号问题）：`pw=$(wsl bash -c 'docker exec tdyw-db printenv MYSQL_ROOT_PASSWORD')`
   - 写 cnf 用 **stdin 管道**（密码不进 argv、不落 Windows 侧明文文件）：

     ```
     printf '[client]\nuser=root\npassword=%s\n' "$pw" | wsl -u root bash -c 'cat > /data/borgbackup/tdyw_restore.cnf && chmod 600 /data/borgbackup/tdyw_restore.cnf'
     ```

   - 验证 cnf 有效（能查询即通过）：**WSL 宿主机没有 mysql/mariadb 客户端**，且 restore 脚本本身就是把 cnf `docker cp` 进 DB 容器、用容器内客户端执行——照脚本同款方式验证：

     ```
     wsl -u root bash -c 'docker cp /data/borgbackup/tdyw_restore.cnf tdyw-db:/tmp/restore_verify.cnf >/dev/null && docker exec tdyw-db sh -c "mysql --defaults-extra-file=/tmp/restore_verify.cnf -e \"SELECT 1\" && rm -f /tmp/restore_verify.cnf && echo CNF_OK"'
     ```

   - 兜底红线不变：**含 `$` 变量的命令禁止内联双引号传给 wsl**（Git Bash/MSYS 会转义与改写路径，已实测踩坑）——优先用 `printenv` / stdin 管道绕开 `$`；绕不开时把命令写成临时 sh 文件落盘，再 `wsl bash /mnt/e/....sh` 执行
4. **空跑预览**（无 --mode 即只校验不改数据，含 borg check + 打印恢复计划）：
   ```
   wsl -u root bash -c 'cd /mnt/e/TDYW/spug-3.0 && BORG_ENV_FILE=/data/borgbackup/borg.env RESTORE_CLIENT_CNF=/data/borgbackup/tdyw_restore.cnf ./borgbackup/borg_backup_set_restore.sh tdyw-restore-<MMDD>'
   ```
   注意：verify-only 模式打出的计划**只有 archive/repo/容器名，目标库与两个卷只在 production 模式才打印**——给用户的计划摘要（目标库、两卷、源快照名）改从 U 盘导出物的 `tmp/tdyw-borg.*/manifest.json` 读（`database_name`、`documents_mountpoint`、`media_mountpoint`、`backup_set_id`）。空跑成功的判定 = 结尾出现 `Verification completed; no data was changed`（其文件清单刷屏会把计划段顶出 tail 窗口，抓计划用 `grep -A 12 "restore plan"`）。

### 确认与执行

把恢复计划摘要给用户（目标库、两个卷、archive 名——目标库与卷从 manifest.json 取，见预检第 4 步注意），明确告知：**将 DROP 重建本地 tdyw 库、清空替换 documents/media 两卷，tdyw-test 栈不受影响**。必须让用户在对话中输入确认词 `RESTORE_PRODUCTION` 后，才允许带 `ASSUME_YES=YES` 执行（脚本确认交互在 wsl 非终端下不可用，ASSUME_YES 是唯一通路，因此对话确认绝对不可省）：

```
wsl -u root bash -c 'cd /mnt/e/TDYW/spug-3.0 && ASSUME_YES=YES BORG_ENV_FILE=/data/borgbackup/borg.env RESTORE_CLIENT_CNF=/data/borgbackup/tdyw_restore.cnf ./borgbackup/borg_backup_set_restore.sh --mode production tdyw-restore-<MMDD>'
```

失败时脚本会让应用保持停止并报所处阶段——如实转告用户，不要自行 `docker start tdyw`；数据处于中间状态时重跑第 4 段即可完整重来。

### 完成后

1. 报告脚本输出的恢复结果（库表数量、卷条目数、健康检查）
2. **提示可选 migrate**（本地代码 schema 可能领先生产，恢复的是生产 schema）：
   ```
   wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py migrate --noinput'
   ```
   是否执行由用户决定，默认只提示不执行。
3. 提醒两条已知事项：登录账号密码已是生产库中的账号；document-chunks 卷不在备份内未被处理，若资料库向量检索异常需单独重建。

## 安全红线

- 第 1 段永不尝试自动执行（接触不到生产机）
- 还原动作破坏性覆盖本地 tdyw 库与两卷：无用户在对话中输入 `RESTORE_PRODUCTION`，绝不带 ASSUME_YES=YES
- 不碰 tdyw-test 栈的任何容器与卷
- 不对本仓库执行 prune / compact / delete / --repair（保留策略归生产管；check 失败如实上报，不做修复尝试）
- `E:\TDYW\borg<MMDD>` 与 U 盘数据不自动清理，只提示
- 每段产物校验失败即停在当前段，如实报告，禁止跳过校验继续

---
name: tdyw-release
description: 构建新版 tdyw 镜像、在本地生产快照上做升级演练（migrate 预检与实跑、健康与日志验证、人工冒烟），演练通过后才导出发布 tar 并输出服务器部署清单。当用户提到构建镜像、新镜像升级、升级演练、新镜像覆盖 tdyw、导出发布 tar、上生产部署时使用——即使用户只说"构建一下发上去"。
---

# tdyw-release：镜像构建 → 本地升级演练 → 打包发布

五段式流程。核心原则：**演练通过才 save**——发布 tar 是演练结论的包装，不是构建的附庸。

```
[0 前置]  工作区知情（不设 git 门禁）+ 借 tdyw-test（活代码）做 Django 预检 + 破坏性迁移扫描
[1 构建]  docker build -t tdyw:<TAG> -f docker/Dockerfile .
[2 演练]  生产快照还原态 + 新镜像：migrate 预告 → override 切镜像（entrypoint 自动实跑）→ 三层验证
[3 打包]  演练通过才 docker save 导出 tar 到 tdyw-server/
[4 部署]  服务器随行清单 + 回滚语义
```

## 环境事实（已核实，直接使用，勿重新探测）

- docker 只在 WSL；Windows 侧没有 docker 命令，一律 `wsl bash -c`；构建/演练在 WSL 内 cd 仓库挂载路径执行
- 构建上下文根 = 仓库根（`-f docker/Dockerfile .`），**根 `.dockerignore` 生效**；quality/ 与两份 onlyoffice-fonts/（共 ~460MB）已排除——Dockerfile 不 COPY 它们，字体运行时经 compose bind mount
- **代码预检的正确对象是 `tdyw-test`**（dev compose bind mount 活代码）；`tdyw` 是生产栈（代码烤在镜像里，无活代码挂载）——借 tdyw 做代码预检查的是旧镜像代码，对象错位（历史 build.sh 的教训，禁止复用）
- 演练场地 = borg-shuttle 第 4 段完成态（本地 `tdyw`/`tdyw-db` 生产快照数据，compose 项目名 `docker`，卷名 `docker_tdyw-*`）；演练回滚 = 重跑 borg-shuttle 第 4 段（`tdyw-restore-<MMDD>` 在本地 repo）
- **迁移不可逆**（项目有 fail-fast 不可逆迁移前科）：换回旧镜像 ≠ 回滚，旧代码 + 新 schema 会崩；真回滚 = restore 整体重放
- **tdyw 容器 ENTRYPOINT 启动即自动 `migrate --noinput`**（fail-closed，失败退出码 1）——所以"只看计划不动数据"的预告必须绕过 entrypoint（见第 2 段），直接 `up` 就是实跑
- docker/.env 已含 ONLYOFFICE 全套 8 键（2026-10-31 补配，凭据独立于 dev、不入 Git）；compose OO 三服务（onlyoffice/onlyoffice-db/onlyoffice-mq）凭据齐备后可启动，但演练不需要它们
- 历史 build.sh（commit e2e668b2"规范部署流程"）已判定退役：检查对象错位 + git 干净门禁与实际工作流冲突 + 曾带 `"""` 语法错误躺两个月。2026-10-31 已修复保留在 `docker/scripts/` 备用，本 skill 取代其定位，默认不走

## 启动：收集 + 断点判定

收集（能推断先给默认，用户确认即可）：

1. **镜像 tag**：默认 `tdyw:<MMDD>`（沿用户历史命名 0917/1024 风格）
2. **演练起点**：本地栈是否处于生产快照还原态（上轮演练若已迁移，问用户：重放快照 or 接受现状）

断点判定（按状态续跑）：

- `docker images` 已有目标 tag 且用户未要求重建 → 从第 2 段起
- `docker inspect tdyw --format '{{.Config.Image}}'` 已是新 tag → 从 L2 验证起
- tar 已导出且演练已通过 → 从第 4 段部署清单起

## 第 0 段：前置（知情 + 预检）

1. `git status --short` 报告未提交改动规模——**不设门禁**（构建不要求 commit，尊重用户工作流），但必须让用户知情；不代提交
2. 借 tdyw-test 对工作区代码做 Django 预检（几秒，快速失败）：

   ```
   wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check --tag compatibility'
   ```

   tdyw-test 未运行时如实报告并跳过（不得静默）。
3. 破坏性迁移扫描（host 侧对工作区文件）：

   ```
   grep -rln 'RemoveField\|DeleteModel\|AlterUniqueTogether\|RemoveIndex\|RemoveConstraint' spug_api/apps/*/migrations/*.py
   ```

   命中即在演练前重点提示（这些迁移会在第 2 段 --plan 里重点核对）。

## 第 1 段：构建

```
wsl bash -c 'cd /mnt/e/TDYW/spug-3.0 && docker build -t tdyw:<TAG> -f docker/Dockerfile .'
```

- 构建全程走网络（npm/pip/playwright 下载 chromium），失败如实报错，不吞错重试
- 成功后 `docker images | grep tdyw` 确认 tag 在位

## 第 2 段：本地升级演练（核心段）

场地预检：tdyw-db healthy、tdyw 在跑旧镜像、documents/media 卷为快照内容（三者不满足先向用户说明）。

1. **写 override 文件** `docker/docker-compose.rehearsal.yml`（演练完删除；禁止改 docker-compose.yml——工作区有未提交改动，git 回退不可用）：

   ```yaml
   services:
     tdyw:
       image: tdyw:<TAG>
   ```

2. **migrate 预告（只读，绕过 entrypoint）**：

   ```
   wsl bash -c 'cd /mnt/e/TDYW/spug-3.0 && docker compose -f docker/docker-compose.yml -f docker/docker-compose.rehearsal.yml run --rm --no-deps --entrypoint python tdyw manage.py migrate --plan'
   ```

   把计划（迁移条目 + 破坏性操作标注）给用户过目。**不得用 `compose run tdyw <cmd>` 不带 --entrypoint 的形式做预告**——entrypoint 会先跑真迁移，预告就变成实跑了。
3. **切镜像实跑**（entrypoint 自动 migrate，fail-closed）：

   ```
   wsl bash -c 'cd /mnt/e/TDYW/spug-3.0 && docker compose -f docker/docker-compose.yml -f docker/docker-compose.rehearsal.yml up -d tdyw'
   ```

   容器退出码非零 = 迁移失败：如实报告 + 转失败处置，禁止自行重启掩盖。
4. **L2 自动验证**：
   - 健康轮询至 healthy（start_period 60s）：`wsl bash -c 'docker inspect -f "{{.State.Health.Status}}" tdyw'`
   - 启动日志扫描：`wsl bash -c 'docker logs tdyw 2>&1 | grep -iE "traceback"'`（须为空）
   - 进程在位：`wsl bash -c 'docker exec tdyw supervisorctl status'` 12 个程序全 RUNNING（supervisorctl 不可用则 `docker exec tdyw ps aux` 查 nginx/gunicorn/celery/beat）
5. **L3 人工冒烟（用户执行，skill 给清单）**：生产账号登录 → 工作台、维护台账（生成/填写/导出）、运行处置记录、制度管理（原稿转档/在线编辑——OO 栈若未启动则为下载编辑降级路径）、干扰、执照/合同抽查
6. **结论**：通过/失败 + 证据。**失败处置**：删除 override → `up -d tdyw` 回旧镜像 → 若 migrate 已应用，重放 borg-shuttle 第 4 段；绝不只换镜像了事。

## 第 3 段：打包（演练通过才执行）

```
wsl bash -c 'docker save -o /mnt/e/TDYW/tdyw-server/tdyw<TAG>.tar tdyw:<TAG>'
```

- 先引用演练结论（通过 + 日期），再 save；报出 tar 大小
- 可选：`docker tag tdyw:<TAG> tdyw:git-<sha>` 便于追溯

## 第 4 段：部署随行清单（打印给用户，不代执行）

1. **服务器 .env 同步**：REDIS_PASSWORD（旧副本缺）+ ONLYOFFICE 8 键整段（本地 docker/.env 已就绪；密钥勿经聊天工具明文传）
2. **OO 栈首启**：`up -d onlyoffice-db onlyoffice-mq onlyoffice`（deploy_prod.sh 只起 tdyw）
3. **`docker/onlyoffice-fonts/`** 手工放置服务器（授权字体不入 Git；缺失回退 noto-cjk）
4. **探活 sidecar**：compose 里 `tdyw-health-probe` 的镜像引用可能落后于 tdyw 主服务（tdyw 镜像 tag 每次发布都换，勿写死任何具体 tag）——首启需 `up -d tdyw-health-probe`，或顺手改指新 tag
5. **deploy_prod.sh**：会 sed 更新 compose 镜像 tag 并 `up -d tdyw`，健康检查 90s + 失败自动回滚（仅镜像）
6. **回滚语义**：迁移已应用后镜像回滚无效，真回滚 = 服务器 borg 快照恢复流程；升级前先在生产跑一次 borg 备份
7. institution 卷首建为空（新模块首发）；RELEASE_PENDING_APPS 保持空（部署必须摘，历史前科）

## 安全红线

- **演练未通过绝不 save**；发布 tar 只能是演练结论的包装
- 演练切镜像只用 override 文件，禁止改 docker-compose.yml
- migrate 预告必须绕过 entrypoint（--entrypoint python + --plan）；**`compose run tdyw <cmd>` 不带 --entrypoint = 真迁移**
- **换回旧镜像 ≠ 回滚**；绝不向用户暗示"换回镜像就没事"
- 不碰 tdyw-test 栈的任何容器与卷
- 代码预检对象只许 tdyw-test（活代码）；借 tdyw 查活代码是已知历史事故
- 每段验证失败即停，如实报告，禁止跳过校验继续

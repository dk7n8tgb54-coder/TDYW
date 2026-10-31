# onlyoffice-main — 生产 ONLYOFFICE Docs 10.0 配置（凭据不进仓库）

生产 `tdyw-onlyoffice`（ONLYOFFICE Docs 10.0，dev 已验证版本 10.0.0 Build 169）
的入口包装与数据库初始化目录。架构与 dev/docker-compose.yml 主实例一致：
10.0 社区版不再内置 PostgreSQL/RabbitMQ，由 compose 新增的 onlyoffice-db
（postgres:16-alpine）/ onlyoffice-mq（rabbitmq:4-alpine）提供，数据全落在
`tdyw-onlyoffice-*-10` 新卷。

| 文件 | 用途 |
|---|---|
| ds-entrypoint.sh | 入口包装：校验必需环境变量（缺失 fail-closed）→ 渲染 local.json → 交回官方入口 |
| createdb.sql | DS 表结构（从 10.0 镜像提取，仅建表；建库由 POSTGRES_DB 完成） |
| README.md | 本文档 |

**local.json 不落盘到仓库**：由 ds-entrypoint.sh 启动时用 ONLYOFFICE_* 环境变量
渲染（dev 版是仓库静态文件 + dev/.env 注入；生产凭据只进 docker/.env）。
也不能直接 bind-mount local.json 单文件——官方入口用 npm json -I 原地重写会
EBUSY，所以必须挂整个目录、由脚本启动时渲染到容器内普通文件。

## 首次启用步骤

1. **docker/.env 增补 ONLYOFFICE_* 全套键**（键清单与占位符见
   docker/.env.example 的 ONLYOFFICE 段）：
   - `ONLYOFFICE_JWT_SECRET` 用 `openssl rand -base64 32` 等强随机生成；
   - `ONLYOFFICE_DB_PASSWORD` / `ONLYOFFICE_MQ_PASSWORD` 独立生成，
     **不得复用 dev 开发凭据（oomain* / oo10*）**；
   - 留空 `ONLYOFFICE_JWT_SECRET` 时应用侧自动降级为"下载→本机编辑→上传保存"，
     只配 db/mq 不配 JWT 没有意义，请整套配置后启用。
2. **宿主机 docker/onlyoffice-fonts/ 放置授权中文字体**（字体文件因授权不入
   Git，目录已用 .gitignore 排除）：字体清单与拷贝步骤参照
   dev/onlyoffice-fonts/README.md（从已授权 Windows 的 C:\Windows\Fonts 拷贝
   simsun/simhei/simfang/simkai/msyh/Deng/STKAITI 等到本目录）。该目录同时
   只读挂进 tdyw 与 onlyoffice 两个容器；为空时回退镜像内 fonts-noto-cjk。
3. **启动顺序**：先
   `docker compose -f docker/docker-compose.yml up -d onlyoffice-db onlyoffice-mq`
   （等两者健康检查通过），再 `up -d onlyoffice`。首次启动自动完成：
   postgres 初始化建表（createdb.sql，幂等 IF NOT EXISTS）+ DS 重建字体索引
   （GENERATE_FONTS 默认 true，读取 /usr/share/fonts/custom）。
4. **健康检查**：`curl http://<host>/onlyoffice/healthcheck` 经 tdyw nginx 的
   /onlyoffice/ 同源代理验证（应返回 `true`）；再在制度管理前端打开一个
   .docx 手册验证编辑/保存链路。
5. **回退路径**：8.1 旧卷（tdyw-onlyoffice-data / tdyw-onlyoffice-log）原封
   保留。还原 docker/docker-compose.yml 中 onlyoffice 服务的改动后
   `up -d onlyoffice` 即回 8.1（8.1 镜像与旧卷完好；重建后需补跑
   `documentserver-generate-allfonts.sh`）。10.0 数据全在 `*-10` 新卷，
   两条路线互不影响；**绝不删除任何一侧卷**。

## 回源主机（X-Forwarded-Host）说明

DS 生成缓存/回调文件 URL 的主机取自 nginx 传的 X-Forwarded-Host（即浏览器
来源主机，docker/config/nginx.conf 两处 `proxy_set_header X-Forwarded-Host
$host/onlyoffice`）。该主机必须能被 tdyw 容器回源解析（tdyw 自身 nginx →
/onlyoffice/ 回到 DS；生产 nginx 已带 proxy_redirect 相对化重定向，版本化
静态资源 302 不会产生混合内容）。若部署在无法回源自身公网地址的网络
（容器不能访问对外 IP/域名），备选方案是把 nginx 两处 X-Forwarded-Host
固定为 `tdyw/onlyoffice`（Compose 网络 DNS 名）：所有回源走容器内网必然
可达，取舍是缓存/回调 URL 固定认 tdyw 这一个主机，浏览器侧多入口
（多 IP/域名并存）时不再跟随来源，一般单域名/IP 部署无感知。

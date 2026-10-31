#!/bin/bash
# DS 10.0 生产版入口包装（2026-10-31）
#
# 与 dev/onlyoffice-main/ds-entrypoint.sh 的差异：
# - dev 版把仓库内静态 local.json 直接 cp 覆盖（dev 凭据在 dev/.env，不入 Git，
#   配置文件本身可留仓库）；生产凭据绝不落仓库，故本脚本在启动时用环境变量
#   （compose 的 onlyoffice 服务注入的 ONLYOFFICE_DB_*/ONLYOFFICE_AMQP_URI）
#   以 heredoc 渲染 local.json，仓库中不存在 local.json 文件。
# 其余背景两版相同（10.0 社区版必须知道）：
# - 10.0 社区版启动脚本忽略 DB_*/AMQP_URI 环境变量，DB/队列配置只能写入
#   /etc/onlyoffice/documentserver/local.json；
# - 该文件不能直接 bind-mount——官方入口用 npm json -I 原地重写 local.json
#   （含 JWT 合并），对 bind-mount 单文件 rename 会 EBUSY 失败。改为启动时
#   先渲染覆盖配置，再交回官方入口，之后的所有 json -I 写入都落在容器内
#   普通文件上。
set -e

# ---- fail-closed：必需环境变量非空校验（缺失即报错退出，不允许静默空密码启动）----
# 含 MQ 账号（2026-10-31 审查修正）：compose 层占位一律空缺省（.env 未配置
# ONLYOFFICE_* 键时不影响其他服务的 compose 操作），本栈的 fail-closed 收敛在
# 启动层——DB 空密码由 postgres 镜像初始化拒绝，MQ 账号由此处拒绝。
for var in ONLYOFFICE_DB_HOST ONLYOFFICE_DB_PORT ONLYOFFICE_DB_NAME ONLYOFFICE_DB_USER ONLYOFFICE_DB_PASSWORD ONLYOFFICE_MQ_USER ONLYOFFICE_MQ_PASSWORD ONLYOFFICE_AMQP_URI; do
  if [ -z "${!var:-}" ]; then
    echo "FATAL: \$${var} is required but empty/unset (compose 注入缺失，见 docker/.env.example ONLYOFFICE 段)" >&2
    exit 1
  fi
done

# 含双引号/反斜杠的值会破坏下方 heredoc 生成的 JSON，直接拒绝启动（fail-closed）
for var in ONLYOFFICE_DB_PASSWORD ONLYOFFICE_AMQP_URI; do
  case "${!var}" in
    *\"*|*\\*)
      echo "FATAL: \$${var} contains JSON-hostile characters (double quote or backslash)" >&2
      exit 1
      ;;
  esac
done

# ---- 渲染 local.json ----
# token.enable 全 true、secret.string 全空串：与镜像自带 local.json 的 token/secret
# 段结构一致（官方入口随后用 json -e 深路径合并 JWT_SECRET 的前提——缺骨架段会
# 写不进去）；真实 JWT 密钥由官方入口从 JWT_SECRET 环境变量合并，不经过本脚本。
# sql/rabbitmq 段即 10.0 社区版缺失的外部 DB/队列连接。
cat > /etc/onlyoffice/documentserver/local.json <<EOF
{
  "services": {
    "CoAuthoring": {
      "token": {
        "enable": {
          "request": {
            "inbox": true,
            "outbox": true
          },
          "browser": true
        },
        "inbox": {
          "header": "Authorization"
        },
        "outbox": {
          "header": "Authorization"
        }
      },
      "secret": {
        "browser": {
          "string": ""
        },
        "inbox": {
          "string": ""
        },
        "outbox": {
          "string": ""
        },
        "session": {
          "string": ""
        }
      },
      "sql": {
        "type": "postgres",
        "dbHost": "${ONLYOFFICE_DB_HOST}",
        "dbPort": ${ONLYOFFICE_DB_PORT},
        "dbName": "${ONLYOFFICE_DB_NAME}",
        "dbUser": "${ONLYOFFICE_DB_USER}",
        "dbPass": "${ONLYOFFICE_DB_PASSWORD}"
      }
    }
  },
  "rabbitmq": {
    "url": "${ONLYOFFICE_AMQP_URI}"
  }
}
EOF

exec /app/ds/run-document-server.sh "$@"

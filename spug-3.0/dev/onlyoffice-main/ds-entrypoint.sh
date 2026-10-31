#!/bin/bash
# DS 10.0 对照实例入口包装（2026-10-30）
# 原因：10.0 社区版启动脚本忽略 DB_*/AMQP_URI 环境变量，DB/队列配置只能写入
# /etc/onlyoffice/documentserver/local.json；但该文件不能直接 bind-mount——
# 官方入口用 npm json -I 原地重写 local.json（含 JWT 合并），对 bind-mount
# 单文件 rename 会 EBUSY 失败。改为启动时先拷贝覆盖配置，再交回官方入口，
# 之后的所有 json -I 写入都落在容器内普通文件上。
set -e
cp /custom-ds-config/local.json /etc/onlyoffice/documentserver/local.json
exec /app/ds/run-document-server.sh "$@"

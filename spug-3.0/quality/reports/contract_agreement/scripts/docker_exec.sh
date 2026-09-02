#!/bin/bash
# 合同协议模块上线前测试 - 容器内命令封装
# 用法： wsl bash /mnt/e/TDYW/spug-3.0/quality/reports/contract_agreement/scripts/docker_exec.sh <命令...>
# 所有命令在 tdyw-test 容器（bind mount + 独立测试库 tdyw-db-test）内执行
set -u
CONTAINER=tdyw-test
WORKDIR=/data/spug/spug_api
docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONWARNINGS=ignore \
  -w "$WORKDIR" "$CONTAINER" "$@"

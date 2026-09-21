#!/bin/bash
# 生成 stable_contract 覆盖数据：循环重试直到在容器重启间隙拿到干净测试窗口
for i in $(seq 8); do
  out=$(docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test sh -c 'coverage run --source=apps.contract_agreement manage.py test apps.contract_agreement.tests.stable_contract --keepdb --parallel 1' 2>&1)
  echo "--- attempt $i ---"
  echo "$out" | tail -2
  if echo "$out" | grep -qE '^OK'; then echo CLEAN_RUN; break; fi
  sleep 20
done

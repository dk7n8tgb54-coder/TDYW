#!/bin/bash
# mutmut runner 包装脚本：服务级就绪门禁 + 重启感知重试
# 1) 等待 MariaDB(mysqladmin ping) 与容器内 Redis 就绪，最多被动等 5 分钟；
#    不主动 docker start，避免与宿主侧备份/维护流程互相干扰。
# 2) 每次测试前后比对两个容器的 StartedAt，若测试期间发生过外部重启则重试该次
#    运行（最多 6 次），确保变异体判定不受重启污染；环境稳定时零额外开销。
ok=0
for i in $(seq 10); do
  if docker exec tdyw-db-test sh -c "mysqladmin ping --silent" 2>/dev/null \
     && docker exec tdyw-test sh -c "redis-cli ping 2>/dev/null | grep -q PONG" 2>/dev/null; then
    ok=1
    break
  fi
  sleep 30
done
[ $ok -eq 1 ] || exit 97
bd=$(docker inspect tdyw-db-test --format '{{.State.StartedAt}}' 2>/dev/null)
ba=$(docker inspect tdyw-test --format '{{.State.StartedAt}}' 2>/dev/null)
rc=98
for a in 1 2 3 4 5 6; do
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test sh -c "python manage.py test apps.contract_agreement.tests.stable_contract --keepdb --parallel 1"
  rc=$?
  ad=$(docker inspect tdyw-db-test --format '{{.State.StartedAt}}' 2>/dev/null)
  aa=$(docker inspect tdyw-test --format '{{.State.StartedAt}}' 2>/dev/null)
  if [ "$bd" = "$ad" ] && [ "$ba" = "$aa" ]; then break; fi
  bd=$ad
  ba=$aa
done
exit $rc

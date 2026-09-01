#!/bin/bash
# 环境探针：确认 tdyw-test 容器连接的数据库容器与网络，排除生产库风险
set -u
echo "=== container IPs ==="
docker inspect -f '{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' tdyw-test tdyw-db tdyw-db-test tdyw 2>&1
echo "=== DB version/name seen by tdyw-test ==="
docker exec -i -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python - <<'PY'
from django.db import connection
with connection.cursor() as c:
    c.execute('SELECT VERSION()')
    print('DB_VERSION=', c.fetchone()[0])
    c.execute('SELECT DATABASE()')
    print('DB_CURRENT=', c.fetchone()[0])
    c.execute("SHOW DATABASES")
    print('DB_LIST=', [r[0] for r in c.fetchall()])
PY

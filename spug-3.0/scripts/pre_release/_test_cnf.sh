#!/bin/bash
ROOT_PW=$(cat /mnt/e/TDYW/spug-3.0/docker/secrets/root_password)
printf "[client]\nhost=127.0.0.1\nport=3306\nuser=root\npassword=%s\n" "$ROOT_PW" > /tmp/test_root.cnf
chmod 600 /tmp/test_root.cnf
echo "=== local file (cat -A) ==="
cat -A /tmp/test_root.cnf
echo "=== root pw length ==="
echo "${#ROOT_PW}"
echo "=== container file ==="
docker cp /tmp/test_root.cnf tdyw-db:/tmp/test_root.cnf
docker exec tdyw-db cat -A /tmp/test_root.cnf
echo "=== try mysql ==="
docker exec tdyw-db mysql --defaults-extra-file=/tmp/test_root.cnf -N -e "SELECT 1" 2>&1
rm /tmp/test_root.cnf
docker exec tdyw-db rm /tmp/test_root.cnf 2>/dev/null

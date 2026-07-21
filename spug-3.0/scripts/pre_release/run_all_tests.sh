#!/bin/bash
# Spug 一键测试脚本（阶段 3 收尾）
# 用法：wsl bash -c "/mnt/e/TDYW/spug-3.0/scripts/pre_release/run_all_tests.sh"
set -e

PROJECT_ROOT="/mnt/e/TDYW/spug-3.0"
CONTAINER="tdyw"
DJANGO_DIR="/data/spug/spug_api"

echo "=========================================="
echo "  Spug 一键测试 ($(date '+%Y-%m-%d %H:%M:%S'))"
echo "=========================================="

# ---- 1. 配置审计 ----
echo ""
echo "[1/4] 配置审计 (audit_config.py)..."
docker exec -i "$CONTAINER" python - < "$PROJECT_ROOT/scripts/pre_release/audit_config.py" 2>&1 | grep -E '(合计|FAIL|PASS)' | tail -5

# ---- 2. 后端单元测试 ----
echo ""
echo "[2/4] 后端单元测试 (5 个 app, 250 tests)..."
docker exec -e PYTHONIOENCODING=utf-8 -w "$DJANGO_DIR" "$CONTAINER" \
  python manage.py test \
  apps.department_duty_log.tests \
  apps.radio_license.tests \
  apps.regulation.tests \
  apps.signature.tests.test_signature \
  apps.signature.tests.test_signature_usage \
  --noinput 2>&1 | tail -5

# ---- 3. 前端单元测试 ----
echo ""
echo "[3/4] 前端单元测试 (17 套件, 282 tests)..."
cd "$PROJECT_ROOT/spug_web" && \
  CI=true npx react-app-rewired test --watchAll=false 2>&1 | grep -E '(Tests:|Test Suites:)'

# ---- 4. 迁移一致性检查 ----
echo ""
echo "[4/4] 迁移一致性检查 (makemigrations --check)..."
docker exec -e PYTHONIOENCODING=utf-8 -w "$DJANGO_DIR" "$CONTAINER" \
  python manage.py makemigrations --check --dry-run 2>&1 | tail -3

echo ""
echo "=========================================="
echo "  测试完成 ($(date '+%Y-%m-%d %H:%M:%S'))"
echo "=========================================="

#!/usr/bin/env bash
# Restore one verified, self-contained schema-v5 full backup set.

set -euo pipefail
umask 027

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TDYW_BACKUP_ROOT="${TDYW_BACKUP_ROOT:-/data/backups/tdyw}"
BACKUP_SETS_DIR="${BACKUP_SETS_DIR:-${TDYW_BACKUP_ROOT}/backup_sets}"

RESTORE_MODE=""
POSITIONAL_BACKUP_SET=""
SHOW_HELP="NO"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --mode)
            [ "$#" -ge 2 ] || { echo "ERROR: --mode requires drill or production" >&2; exit 2; }
            RESTORE_MODE="$2"
            shift 2
            ;;
        --mode=*) RESTORE_MODE="${1#--mode=}"; shift ;;
        -h|--help) SHOW_HELP="YES"; shift ;;
        --) shift; break ;;
        -*) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
        *)
            [ -z "${POSITIONAL_BACKUP_SET}" ] || {
                echo "ERROR: only one backup set may be selected" >&2
                exit 2
            }
            POSITIONAL_BACKUP_SET="$1"
            shift
            ;;
    esac
done
[ "$#" -eq 0 ] || { echo "ERROR: unexpected arguments" >&2; exit 2; }

case "${RESTORE_MODE}" in
    ""|drill|production) ;;
    *) echo "ERROR: --mode must be drill or production" >&2; exit 2 ;;
esac

BACKUP_SET_DIR="${BACKUP_SET_DIR:-${POSITIONAL_BACKUP_SET:-}}"
APP_CONTAINER="${APP_CONTAINER:-tdyw}"
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
DATABASE_RESTORE_MODE="${DATABASE_RESTORE_MODE:-logical}"
RESTORE_CLIENT_CNF="${RESTORE_CLIENT_CNF:-/etc/tdyw-backup/tdyw_restore.cnf}"
RESTORE_DB="${RESTORE_DB:-tdyw_restore}"
DOCUMENTS_PATH="${DOCUMENTS_PATH:-/data/spug/spug_api/storage/documents}"
MEDIA_PATH="${MEDIA_PATH:-/data/spug/spug_api/media}"
DRILL_ROOT="${DRILL_ROOT:-/tmp/tdyw-restore-drill}"
ASSUME_YES="${ASSUME_YES:-NO}"
APP_STOP_TIMEOUT="${APP_STOP_TIMEOUT:-900}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

BACKUP_SET_ID=""
BACKUP_ROOT=""
SOURCE_DB_NAME=""
DATABASE_BACKUP_FILE=""
PHYSICAL_BACKUP_FILE=""
BACKUP_DATABASE_IMAGE=""
APP_IMAGE=""
RUNTIME_DIR=""
PLAN_FILE=""
APP_STOPPED_BY_SCRIPT=0
DB_RESULT="NOT RUN"
DOCUMENTS_RESULT="NOT RUN"
MEDIA_RESULT="NOT RUN"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

usage() {
    cat <<EOF
Usage:
  ./backups/backup_set_restore.sh <backup_set_id|backup_set_directory>
  ./backups/backup_set_restore.sh --mode drill <backup_set_id|backup_set_directory>
  ./backups/backup_set_restore.sh --mode production <backup_set_id|backup_set_directory>

No --mode:
  Verify SHA-256, manifests and the independent full restore plan. No data changes.

--mode drill:
  Restore into a test database container and ${DRILL_ROOT}. Both container names
  must contain "test" and DRILL_ROOT must be under /tmp.

--mode production:
  Stop the application, restore database/documents/media from the same full set,
  then start the application only after every restore step succeeds.

Environment:
  BACKUP_SETS_DIR          Default: /data/backups/tdyw/backup_sets
  DATABASE_RESTORE_MODE   logical|physical, default: logical
  RESTORE_CLIENT_CNF      MariaDB client cnf, mode 0600 or 0400
  APP_CONTAINER           Default: tdyw
  DB_CONTAINER            Default: tdyw-db
  DOCUMENTS_PATH          Path inside the application volumes
  MEDIA_PATH              Path inside the application volumes
  ASSUME_YES=YES          Skip the production confirmation prompt

Only schema-v5 independent full backup sets are accepted. There is no legacy or
incremental restore path. A failed production restore leaves the app stopped.
EOF
}

cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [ "${rc}" -ne 0 ] && [ "${APP_STOPPED_BY_SCRIPT}" -eq 1 ]; then
        log "ERROR: restore failed; ${APP_CONTAINER} remains stopped for inspection"
    fi
    if [ -n "${RUNTIME_DIR}" ] && [ -d "${RUNTIME_DIR}" ]; then
        rm -rf -- "${RUNTIME_DIR}"
    fi
    exit "${rc}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

resolve_backup_set_dir() {
    [ -n "${BACKUP_SET_DIR}" ] || { usage; exit 2; }
    if [ ! -d "${BACKUP_SET_DIR}" ] && [ -d "${BACKUP_SETS_DIR}/${BACKUP_SET_DIR}" ]; then
        BACKUP_SET_DIR="${BACKUP_SETS_DIR}/${BACKUP_SET_DIR}"
    fi
    [ -d "${BACKUP_SET_DIR}" ] || {
        log "ERROR: backup set directory not found: ${BACKUP_SET_DIR}"
        exit 1
    }
    BACKUP_SET_DIR="$(cd "${BACKUP_SET_DIR}" && pwd -P)"
    BACKUP_SET_ID="$(basename "${BACKUP_SET_DIR}")"
}

acquire_maintenance_lock() {
    command -v flock >/dev/null || { log "ERROR: flock is required"; exit 1; }
    exec 9>"$(dirname "${BACKUP_SET_DIR}")/.backup.lock"
    flock -n 9 || { log "ERROR: another backup or restore is running"; exit 1; }
}

plan_get() {
    python3 - "${PLAN_FILE}" "$1" <<'PY'
import json
import sys
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    value = json.load(handle)
for part in sys.argv[2].split("."):
    value = value[part]
if value is not None:
    print(value)
PY
}

load_and_validate_plan() {
    command -v python3 >/dev/null || { log "ERROR: python3 is required"; exit 1; }
    case "${DATABASE_RESTORE_MODE}" in
        logical|physical) ;;
        *) log "ERROR: DATABASE_RESTORE_MODE must be logical or physical"; exit 2 ;;
    esac
    RUNTIME_DIR="$(mktemp -d /tmp/tdyw-restore-plan.XXXXXX)"
    PLAN_FILE="${RUNTIME_DIR}/restore-plan.json"
    python3 "${SCRIPT_DIR}/validate_backup_chain.py" \
        --backup-set-dir "${BACKUP_SET_DIR}" --output "${PLAN_FILE}"
    BACKUP_SET_ID="$(plan_get target_backup_set_id)"
    BACKUP_ROOT="$(plan_get backup_root)"
    SOURCE_DB_NAME="$(plan_get source_database_name)"
    DATABASE_BACKUP_FILE="$(plan_get logical_database_artifact)"
    PHYSICAL_BACKUP_FILE="$(plan_get physical_database_artifact)"
    BACKUP_DATABASE_IMAGE="$(plan_get database_image)"
    if [ "${DATABASE_RESTORE_MODE}" = "physical" ] && [ -z "${PHYSICAL_BACKUP_FILE}" ]; then
        log "ERROR: this backup set has no physical database artifact"
        exit 1
    fi
}

apply_mode() {
    case "${RESTORE_MODE}" in
        "") return 0 ;;
        drill)
            [[ "${APP_CONTAINER}" == *test* && "${DB_CONTAINER}" == *test* ]] || {
                log "ERROR: drill mode requires test in both container names"
                exit 2
            }
            [[ "${DRILL_ROOT}" == /tmp/* ]] || {
                log "ERROR: drill mode requires DRILL_ROOT under /tmp"
                exit 2
            }
            RESTORE_DB="${RESTORE_DB:-tdyw_restore}"
            ;;
        production)
            RESTORE_DB="${SOURCE_DB_NAME}"
            ;;
    esac
}

print_plan() {
    echo "============================================================"
    echo " Independent full backup restore plan"
    echo "============================================================"
    echo "  backup set:              ${BACKUP_SET_ID}"
    echo "  database mode:           ${DATABASE_RESTORE_MODE}"
    echo "  source database:         ${SOURCE_DB_NAME}"
    echo "  target database:         ${RESTORE_DB}"
    if [ "${RESTORE_MODE}" = "drill" ]; then
        echo "  files target:            ${DRILL_ROOT}/{documents,media}"
    else
        echo "  documents target:        ${DOCUMENTS_PATH}"
        echo "  media target:            ${MEDIA_PATH}"
    fi
    echo "  execution mode:          ${RESTORE_MODE:-verify-only}"
    echo "============================================================"
}

verify_fileset_archives() {
    local name
    for name in documents media; do
        python3 "${SCRIPT_DIR}/restore_fileset_chain.py" \
            --backup-root "${BACKUP_ROOT}" --backup-set-id "${BACKUP_SET_ID}" \
            --fileset "${name}" --verify-only --prevalidated
    done
}

require_execution_environment() {
    command -v docker >/dev/null || { log "ERROR: docker is required"; exit 1; }
    if [ "${DATABASE_RESTORE_MODE}" = "logical" ]; then
        [ -f "${RESTORE_CLIENT_CNF}" ] && [ -r "${RESTORE_CLIENT_CNF}" ] || {
            log "ERROR: restore client cnf is missing: ${RESTORE_CLIENT_CNF}"
            exit 1
        }
        local mode
        mode="$(stat -c '%a' "${RESTORE_CLIENT_CNF}" 2>/dev/null || true)"
        case "${mode}" in 600|400) ;; *) log "ERROR: restore client cnf must be 0600 or 0400"; exit 1 ;; esac
    fi
    APP_IMAGE="$(docker inspect -f '{{.Config.Image}}' "${APP_CONTAINER}")"
    [ -n "${APP_IMAGE}" ] || { log "ERROR: unable to detect application image"; exit 1; }
}

confirm_production() {
    [ "${RESTORE_MODE}" = "production" ] || return 0
    [ "${ASSUME_YES}" != "YES" ] || return 0
    echo "This will overwrite ${SOURCE_DB_NAME}, documents and media from ${BACKUP_SET_ID}."
    printf 'Type RESTORE_PRODUCTION to continue: '
    local answer
    read -r answer
    [ "${answer}" = "RESTORE_PRODUCTION" ] || { log "Restore cancelled"; exit 2; }
}

container_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

stop_application() {
    if container_running "${APP_CONTAINER}"; then
        log "Stopping ${APP_CONTAINER}"
        docker stop -t "${APP_STOP_TIMEOUT}" "${APP_CONTAINER}" >/dev/null
        APP_STOPPED_BY_SCRIPT=1
    fi
    if container_running "${APP_CONTAINER}"; then
        log "ERROR: application container did not stop"
        exit 1
    fi
}

wait_for_app_health() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT)) running health
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        running="$(docker inspect -f '{{.State.Running}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${APP_CONTAINER}" 2>/dev/null || true)"
        if [ "${running}" = "true" ] && { [ "${health}" = "healthy" ] || [ "${health}" = "none" ]; }; then
            return 0
        fi
        sleep 3
    done
    log "ERROR: application did not become healthy within ${HEALTH_TIMEOUT}s"
    return 1
}

restore_database() {
    if [ "${DATABASE_RESTORE_MODE}" = "logical" ]; then
        BACKUP_FILE="${DATABASE_BACKUP_FILE}" \
        RESTORE_CLIENT_CNF="${RESTORE_CLIENT_CNF}" \
        RESTORE_DB="${RESTORE_DB}" SOURCE_DB_NAME="${SOURCE_DB_NAME}" \
        DROP_EXISTING=YES \
        ALLOW_RESTORE_TO_PRODUCTION="$([ "${RESTORE_MODE}" = production ] && echo YES || echo NO)" \
        DB_CONTAINER="${DB_CONTAINER}" bash "${SCRIPT_DIR}/mariadump_restore.sh"
        DB_RESULT="SUCCESS (logical -> ${RESTORE_DB})"
        return 0
    fi

    local current_image
    current_image="$(docker inspect -f '{{.Config.Image}}' "${DB_CONTAINER}")"
    if [ "${BACKUP_DATABASE_IMAGE}" != "${current_image}" ] && [ "${ALLOW_PHYSICAL_IMAGE_MISMATCH:-NO}" != "YES" ]; then
        log "ERROR: physical backup image mismatch: ${BACKUP_DATABASE_IMAGE} != ${current_image}"
        return 1
    fi
    PHYSICAL_BACKUP_FILE="${PHYSICAL_BACKUP_FILE}" \
    FORCE_PHYSICAL_RESTORE=YES START_AFTER_RESTORE=YES STOP_APP_CONTAINER=NO \
    DB_CONTAINER="${DB_CONTAINER}" APP_CONTAINER="${APP_CONTAINER}" \
    bash "${SCRIPT_DIR}/mariabackup_prepare_restore.sh"
    DB_RESULT="SUCCESS (physical server instance)"
}

restore_fileset() {
    local name="$1" target="$2" result_var="$3"
    local container_target="${target}"
    if [ "${RESTORE_MODE}" = "drill" ]; then
        container_target="/restore-output/${name}"
    fi
    local -a arguments=(
        --backup-root /backup-root --backup-set-id "${BACKUP_SET_ID}"
        --fileset "${name}" --clear-target --prevalidated --target "${container_target}"
    )
    if [ "${RESTORE_MODE}" = "drill" ]; then
        mkdir -p -- "${DRILL_ROOT}"
        docker run --rm --network none \
            -v "${SCRIPT_DIR}:/backup-code:ro" \
            -v "${BACKUP_ROOT}:/backup-root:ro" \
            -v "${DRILL_ROOT}:/restore-output" \
            --entrypoint python3 "${APP_IMAGE}" \
            /backup-code/restore_fileset_chain.py \
            "${arguments[@]}"
    else
        docker run --rm --network none \
            --volumes-from "${APP_CONTAINER}" \
            -v "${SCRIPT_DIR}:/backup-code:ro" \
            -v "${BACKUP_ROOT}:/backup-root:ro" \
            --entrypoint python3 "${APP_IMAGE}" \
            /backup-code/restore_fileset_chain.py "${arguments[@]}"
    fi
    printf -v "${result_var}" '%s' SUCCESS
}

execute_restore() {
    require_execution_environment
    confirm_production

    if [ "${RESTORE_MODE}" = "production" ] || [ "${DATABASE_RESTORE_MODE}" = "physical" ]; then
        stop_application
    fi
    restore_database
    if [ "${RESTORE_MODE}" = "drill" ]; then
        restore_fileset documents "${DRILL_ROOT}/documents" DOCUMENTS_RESULT
        restore_fileset media "${DRILL_ROOT}/media" MEDIA_RESULT
    else
        restore_fileset documents "${DOCUMENTS_PATH}" DOCUMENTS_RESULT
        restore_fileset media "${MEDIA_PATH}" MEDIA_RESULT
    fi

    if [ "${APP_STOPPED_BY_SCRIPT}" -eq 1 ] && [ "${RESTORE_MODE}" = "production" ]; then
        docker start "${APP_CONTAINER}" >/dev/null
        wait_for_app_health
        APP_STOPPED_BY_SCRIPT=0
    elif [ "${APP_STOPPED_BY_SCRIPT}" -eq 1 ]; then
        log "Drill completed; ${APP_CONTAINER} remains stopped because drill files are isolated"
        APP_STOPPED_BY_SCRIPT=0
    fi
    log "Restore completed: database=${DB_RESULT}, documents=${DOCUMENTS_RESULT}, media=${MEDIA_RESULT}"
}

main() {
    if [ "${SHOW_HELP}" = "YES" ]; then
        usage
        return 0
    fi
    resolve_backup_set_dir
    acquire_maintenance_lock
    load_and_validate_plan
    apply_mode
    print_plan
    if [ -z "${RESTORE_MODE}" ]; then
        verify_fileset_archives
        log "Verification completed; no data was changed"
        return 0
    fi
    execute_restore
}

main "$@"

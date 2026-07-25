#!/usr/bin/env bash
# Prepare and optionally restore a mariabackup full backup into its exact DB volume.

set -euo pipefail
umask 027

DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
APP_CONTAINER="${APP_CONTAINER:-tdyw}"
PHYSICAL_BACKUP_FILE="${PHYSICAL_BACKUP_FILE:-${1:-}}"
RESTORE_WORK_DIR="${RESTORE_WORK_DIR:-}"
DB_IMAGE="${DB_IMAGE:-}"
DB_VOLUME_NAME="${DB_VOLUME_NAME:-}"
FORCE_PHYSICAL_RESTORE="${FORCE_PHYSICAL_RESTORE:-NO}"
STOP_APP_CONTAINER="${STOP_APP_CONTAINER:-YES}"
START_AFTER_RESTORE="${START_AFTER_RESTORE:-NO}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
AUTO_WORK_DIR=0
ACTUAL_DB_VOLUME_NAME=""

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

usage() {
    cat <<EOF
Usage:
  PHYSICAL_BACKUP_FILE=/path/to/database.mariabackup.tar.gz \\
  ./mariabackup_prepare_restore.sh

Destructive restore into the database container's exact named volume:
  PHYSICAL_BACKUP_FILE=/path/to/database.mariabackup.tar.gz \\
  FORCE_PHYSICAL_RESTORE=YES START_AFTER_RESTORE=YES \\
  ./mariabackup_prepare_restore.sh

Options:
  DB_CONTAINER             Default: tdyw-db
  APP_CONTAINER            Default: tdyw
  DB_IMAGE                 Must match DB_CONTAINER when explicitly set
  DB_VOLUME_NAME           Must match its /var/lib/mysql named volume when set
  RESTORE_WORK_DIR         Optional retained prepare directory; otherwise temporary
  FORCE_PHYSICAL_RESTORE   YES is required to overwrite the database volume
  STOP_APP_CONTAINER       Default: YES
  START_AFTER_RESTORE      Default: NO

The script rejects bind mounts and never infers an unrelated volume.
EOF
}

cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [ "${AUTO_WORK_DIR}" -eq 1 ] && [ -n "${RESTORE_WORK_DIR}" ] && [ -d "${RESTORE_WORK_DIR}" ]; then
        rm -rf -- "${RESTORE_WORK_DIR}"
    fi
    exit "${rc}"
}
trap cleanup EXIT INT TERM

container_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

preflight() {
    [ -n "${PHYSICAL_BACKUP_FILE}" ] || { usage; exit 2; }
    [ -f "${PHYSICAL_BACKUP_FILE}" ] || {
        log "ERROR: physical backup file not found: ${PHYSICAL_BACKUP_FILE}"
        exit 1
    }
    command -v docker >/dev/null || { log "ERROR: docker command not found"; exit 1; }
    command -v tar >/dev/null || { log "ERROR: tar command not found"; exit 1; }
    command -v python3 >/dev/null || { log "ERROR: python3 command not found"; exit 1; }
    python3 - "${PHYSICAL_BACKUP_FILE}" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

checkpoint = False
with tarfile.open(sys.argv[1], "r|gz") as archive:
    for member in archive:
        path = PurePosixPath(member.name.rstrip("/"))
        if path.is_absolute() or not path.parts or any(
            part in ("", ".", "..") for part in path.parts
        ):
            raise SystemExit(f"unsafe physical backup member: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"unsupported physical backup member: {member.name!r}")
        checkpoint = checkpoint or path.as_posix() == "xtrabackup_checkpoints"
if not checkpoint:
    raise SystemExit("physical backup is missing xtrabackup_checkpoints")
PY
    [[ "${HEALTH_TIMEOUT}" =~ ^[0-9]+$ ]] || {
        log "ERROR: HEALTH_TIMEOUT must be a non-negative integer"
        exit 2
    }
}

detect_docker_settings() {
    local actual_image mount_info mount_type mount_name mount_source
    actual_image="$(docker inspect -f '{{.Config.Image}}' "${DB_CONTAINER}")"
    if [ -n "${DB_IMAGE}" ] && [ "${DB_IMAGE}" != "${actual_image}" ]; then
        log "ERROR: DB_IMAGE does not match ${DB_CONTAINER}: ${DB_IMAGE} != ${actual_image}"
        exit 1
    fi
    DB_IMAGE="${actual_image}"

    mount_info="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{printf "%s|%s|%s" .Type .Name .Source}}{{end}}{{end}}' "${DB_CONTAINER}")"
    IFS='|' read -r mount_type mount_name mount_source <<<"${mount_info}"
    if [ "${mount_type}" != "volume" ] || [ -z "${mount_name}" ]; then
        log "ERROR: ${DB_CONTAINER}:/var/lib/mysql must use a named Docker volume"
        log "Detected mount type=${mount_type:-none}, source=${mount_source:-none}"
        exit 1
    fi
    ACTUAL_DB_VOLUME_NAME="${mount_name}"
    if [ -n "${DB_VOLUME_NAME}" ] && [ "${DB_VOLUME_NAME}" != "${ACTUAL_DB_VOLUME_NAME}" ]; then
        log "ERROR: DB_VOLUME_NAME does not match ${DB_CONTAINER}:/var/lib/mysql"
        log "Expected ${ACTUAL_DB_VOLUME_NAME}, received ${DB_VOLUME_NAME}"
        exit 1
    fi
    DB_VOLUME_NAME="${ACTUAL_DB_VOLUME_NAME}"
    [[ "${DB_VOLUME_NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || {
        log "ERROR: detected Docker volume name contains unsupported characters"
        exit 1
    }
}

extract_and_prepare() {
    if [ -z "${RESTORE_WORK_DIR}" ]; then
        RESTORE_WORK_DIR="$(mktemp -d /tmp/tdyw-mariabackup-restore.XXXXXX)"
        AUTO_WORK_DIR=1
    else
        mkdir -p -- "${RESTORE_WORK_DIR}"
        [ -z "$(find "${RESTORE_WORK_DIR}" -mindepth 1 -print -quit)" ] || {
            log "ERROR: RESTORE_WORK_DIR must be empty: ${RESTORE_WORK_DIR}"
            exit 1
        }
    fi

    log "Extracting physical backup into ${RESTORE_WORK_DIR}"
    tar xzf "${PHYSICAL_BACKUP_FILE}" -C "${RESTORE_WORK_DIR}" --no-same-owner --no-same-permissions
    [ -f "${RESTORE_WORK_DIR}/xtrabackup_checkpoints" ] || {
        log "ERROR: archive does not contain xtrabackup_checkpoints"
        exit 1
    }
    log "Preparing mariabackup files with ${DB_IMAGE}"
    docker run --rm --network none \
        --mount "type=bind,source=${RESTORE_WORK_DIR},target=/restore" \
        "${DB_IMAGE}" mariabackup --prepare --target-dir=/restore
}

stop_container_and_confirm() {
    local container="$1"
    if container_running "${container}"; then
        docker stop "${container}" >/dev/null
    fi
    if container_running "${container}"; then
        log "ERROR: container did not stop: ${container}"
        exit 1
    fi
}

wait_for_database() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT)) running health
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        running="$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER}" 2>/dev/null || true)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${DB_CONTAINER}" 2>/dev/null || true)"
        if [ "${running}" = "true" ] && { [ "${health}" = "healthy" ] || [ "${health}" = "none" ]; }; then
            return 0
        fi
        sleep 3
    done
    log "ERROR: ${DB_CONTAINER} did not become ready within ${HEALTH_TIMEOUT}s"
    return 1
}

restore_volume() {
    if [ "${FORCE_PHYSICAL_RESTORE}" != "YES" ]; then
        log "Prepare validation completed; database volume was not changed"
        log "Set FORCE_PHYSICAL_RESTORE=YES only for an intentional restore"
        return 0
    fi

    log "Destructive restore target confirmed: ${DB_CONTAINER}:${DB_VOLUME_NAME}"
    if [ "${STOP_APP_CONTAINER}" = "YES" ]; then
        stop_container_and_confirm "${APP_CONTAINER}"
    fi
    stop_container_and_confirm "${DB_CONTAINER}"

    docker run --rm --network none \
        --mount "type=volume,source=${DB_VOLUME_NAME},target=/var/lib/mysql" \
        --mount "type=bind,source=${RESTORE_WORK_DIR},target=/restore,readonly" \
        "${DB_IMAGE}" sh -ceu '
            find /var/lib/mysql -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
            mariabackup --copy-back --target-dir=/restore
            chown -R mysql:mysql /var/lib/mysql
        '
    log "Physical database files copied into ${DB_VOLUME_NAME}"

    if [ "${START_AFTER_RESTORE}" = "YES" ]; then
        docker start "${DB_CONTAINER}" >/dev/null
        wait_for_database
        if [ "${STOP_APP_CONTAINER}" = "YES" ]; then
            docker start "${APP_CONTAINER}" >/dev/null
        fi
    else
        log "Containers remain stopped for verification"
    fi
}

main() {
    preflight
    detect_docker_settings
    extract_and_prepare
    restore_volume
}

main "$@"

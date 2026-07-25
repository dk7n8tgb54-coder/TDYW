#!/usr/bin/env python3
"""Build the stable root manifest for a consistent backup set."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path, payload):
    target = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--backup-set-id", required=True)
    parser.add_argument("--status", choices=("VERIFYING", "SUCCESS"), required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--finished-at", default="")
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--database-account", required=True)
    parser.add_argument("--database-version", required=True)
    parser.add_argument("--database-image", required=True)
    parser.add_argument("--database-image-id", default="")
    parser.add_argument("--database-image-digest", default="")
    parser.add_argument("--app-image", required=True)
    parser.add_argument("--git-commit", default="")
    parser.add_argument("--freeze-seconds", type=int, required=True)
    parser.add_argument(
        "--database-mode", choices=("logical", "both"), required=True
    )
    parser.add_argument("--logical-database-artifact", default="")
    parser.add_argument("--physical-database-artifact", default="")
    parser.add_argument("--documents-manifest", required=True)
    parser.add_argument("--media-manifest", required=True)
    args = parser.parse_args()

    if not args.logical_database_artifact:
        parser.error("logical database artifact is required for this database mode")
    if args.database_mode == "both" and not args.physical_database_artifact:
        parser.error("physical database artifact is required for this database mode")
    if args.database_mode == "logical" and args.physical_database_artifact:
        parser.error("logical database mode cannot include a physical artifact")

    database_artifacts = []
    if args.logical_database_artifact:
        logical_path = Path(args.logical_database_artifact)
        database_artifacts.append(
            {
                "type": "logical",
                "format": "mariadb-dump-gzip",
                "scope": "database",
                "artifact": logical_path.name,
                "size": logical_path.stat().st_size,
                "sha256": sha256_file(logical_path),
                "prepared": True,
                "method": "mariadb-dump --single-transaction --routines --triggers --events --quick --hex-blob",
            }
        )
    if args.physical_database_artifact:
        physical_path = Path(args.physical_database_artifact)
        database_artifacts.append(
            {
                "type": "physical",
                "format": "mariabackup-tar-gzip",
                "scope": "server-instance",
                "artifact": physical_path.name,
                "size": physical_path.stat().st_size,
                "sha256": sha256_file(physical_path),
                "prepared": False,
                "method": "mariabackup --backup; prepare is required before restore",
            }
        )
    documents = load_json(args.documents_manifest)
    media = load_json(args.media_manifest)
    for fileset in (documents, media):
        if fileset.get("schema_version") != 3:
            parser.error("fileset manifest must use schema_version 3")
        if fileset.get("backup_set_id") != args.backup_set_id:
            parser.error("fileset manifest backup_set_id does not match")
        if fileset.get("backup_mode") != "full":
            parser.error("fileset manifest must be a full snapshot")
    payload = {
        "schema_version": 5,
        "backup_set_id": args.backup_set_id,
        "status": args.status,
        "started_at": args.started_at,
        "finished_at": args.finished_at or None,
        "hostname": args.hostname,
        "git_commit": args.git_commit,
        "freeze_seconds": args.freeze_seconds,
        "consistency_method": "application stopped; database and file volumes captured in one freeze window",
        "fileset_mode": "full",
        "database": {
            "name": args.database_name,
            "backup_mode": args.database_mode,
            "version": args.database_version,
            "image": args.database_image,
            "image_id": args.database_image_id,
            "image_digest": args.database_image_digest,
            "account": args.database_account,
            "artifacts": database_artifacts,
        },
        "application": {"image": args.app_image},
        "filesets": {"documents": documents, "media": media},
        "included_data": [
            *(
                ["MariaDB logical dump"]
                if args.database_mode in ("logical", "both")
                else []
            ),
            *(
                ["MariaDB physical server-instance backup"]
                if args.database_mode == "both"
                else []
            ),
            "documents",
            "media",
        ],
        "excluded_data": {
            "document_chunks": "temporary/resumable upload chunks; not authoritative after application writes are frozen",
            "logs": "operational logs are not authoritative business data",
            "cache": "Redis and preview caches are rebuildable",
            "temporary_files": "rebuildable and may be incomplete",
        },
        "remote_copy_status": "MANUAL_NOT_VERIFIED",
    }
    write_atomic(args.output, payload)


if __name__ == "__main__":
    main()

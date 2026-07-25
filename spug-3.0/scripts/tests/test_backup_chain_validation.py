import gzip
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


BACKUPS_DIR = Path(__file__).resolve().parents[2] / "backups"
sys.path.insert(0, str(BACKUPS_DIR))

from backup_chain import validate_member
from create_fileset_snapshot import create_snapshot


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupChainValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.documents = self.root / "documents-source"
        self.media = self.root / "media-source"
        self.backups = self.root / "backup_sets"
        self.documents.mkdir()
        self.media.mkdir()
        self.backups.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def create_set(self, backup_set_id):
        output = self.backups / backup_set_id
        output.mkdir()
        database = output / "database.sql.gz"
        with gzip.open(database, "wt", encoding="utf-8") as handle:
            handle.write("CREATE TABLE `test_record` (`id` bigint NOT NULL);\n")

        for name, source in (("documents", self.documents), ("media", self.media)):
            create_snapshot(
                str(source),
                str(output / f"{name}.tar.gz"),
                str(output / f"{name}.manifest.json"),
                name,
                backup_set_id,
            )

        command = [
            sys.executable,
            str(BACKUPS_DIR / "create_backup_set_manifest.py"),
            "--output", str(output / "manifest.json"),
            "--backup-set-id", backup_set_id,
            "--status", "SUCCESS",
            "--started-at", "2026-07-23T18:00:00Z",
            "--finished-at", "2026-07-23T18:00:05Z",
            "--hostname", "test-host",
            "--database-name", "tdyw_test",
            "--database-account", "root@localhost",
            "--database-version", "test-version",
            "--database-image", "mysql:test",
            "--app-image", "tdyw:test",
            "--freeze-seconds", "5",
            "--database-mode", "logical",
            "--logical-database-artifact", str(database),
            "--documents-manifest", str(output / "documents.manifest.json"),
            "--media-manifest", str(output / "media.manifest.json"),
        ]
        subprocess.run(command, check=True)

        names = (
            "database.sql.gz",
            "documents.tar.gz",
            "documents.manifest.json",
            "media.tar.gz",
            "media.manifest.json",
            "manifest.json",
        )
        with open(output / "SHA256SUMS", "w", encoding="ascii", newline="\n") as handle:
            for name in names:
                handle.write(f"{sha256_file(output / name)}  {name}\n")
        return output

    def rewrite_checksums(self, output):
        names = (
            "database.sql.gz",
            "documents.tar.gz",
            "documents.manifest.json",
            "media.tar.gz",
            "media.manifest.json",
            "manifest.json",
        )
        with open(output / "SHA256SUMS", "w", encoding="ascii", newline="\n") as handle:
            for name in names:
                handle.write(f"{sha256_file(output / name)}  {name}\n")

    def test_full_backup_sets_are_independent_and_retained_individually(self):
        first_id = "backup_set_20260720_020000"
        second_id = "backup_set_20260721_020000"
        (self.documents / "document.txt").write_text("before", encoding="utf-8")
        (self.media / "old.bin").write_bytes(b"old")
        first = self.create_set(first_id)

        (self.documents / "document.txt").write_text("after", encoding="utf-8")
        (self.media / "old.bin").unlink()
        (self.media / "new.bin").write_bytes(b"new")
        second = self.create_set(second_id)

        self.assertEqual(validate_member(second)["backup_set_id"], second_id)

        plan_path = self.root / "restore-plan.json"
        subprocess.run(
            [
                sys.executable,
                str(BACKUPS_DIR / "validate_backup_chain.py"),
                "--backup-set-dir", str(second),
                "--output", str(plan_path),
            ],
            check=True,
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["target_backup_set_id"], second_id)

        old_time = time.time() - 40 * 86400
        os.utime(first, (old_time, old_time))
        os.utime(second, (old_time, old_time))
        retention = subprocess.run(
            [
                sys.executable,
                str(BACKUPS_DIR / "select_retention_chains.py"),
                "--backup-root", str(self.backups),
                "--retention-days", "30",
            ],
            check=True,
            capture_output=True,
        ).stdout
        selected_paths = {
            Path(os.fsdecode(item)).name for item in retention.split(b"\0") if item
        }
        self.assertEqual(selected_paths, {first_id, second_id})

        os.utime(second, None)
        retained = subprocess.run(
            [
                sys.executable,
                str(BACKUPS_DIR / "select_retention_chains.py"),
                "--backup-root", str(self.backups),
                "--retention-days", "30",
            ],
            check=True,
            capture_output=True,
        ).stdout
        retained_paths = {
            Path(os.fsdecode(item)).name for item in retained.split(b"\0") if item
        }
        self.assertEqual(retained_paths, {first_id})

        with open(first / "documents.tar.gz", "ab") as handle:
            handle.write(b"tampered")
        self.assertEqual(validate_member(second)["backup_set_id"], second_id)
        with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
            validate_member(first)

    def test_incremental_metadata_is_rejected(self):
        backup_id = "backup_set_20260722_020000"
        backup = self.create_set(backup_id)
        manifest_path = backup / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["fileset_mode"] = "incremental"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.rewrite_checksums(backup)
        with self.assertRaisesRegex(RuntimeError, "only independent full"):
            validate_member(backup)

    def test_unified_restore_entry_can_verify_without_docker_or_credentials(self):
        backup_id = "backup_set_20260723_020000"
        (self.documents / "document.txt").write_text("content", encoding="utf-8")
        (self.media / "media.bin").write_bytes(b"media")
        backup = self.create_set(backup_id)
        environment = os.environ.copy()
        environment.pop("BACKUP_SET_DIR", None)
        result = subprocess.run(
            ["bash", str(BACKUPS_DIR / "backup_set_restore.sh"), str(backup)],
            check=True,
            env=environment,
            text=True,
            capture_output=True,
        )
        self.assertIn("Verification completed; no data was changed", result.stdout)


if __name__ == "__main__":
    unittest.main()

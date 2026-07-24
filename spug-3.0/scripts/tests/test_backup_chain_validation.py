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

from backup_chain import resolve_chain
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

    def create_set(self, backup_set_id, mode, base_id, parent_id=""):
        output = self.backups / backup_set_id
        output.mkdir()
        database = output / "database.sql.gz"
        with gzip.open(database, "wt", encoding="utf-8") as handle:
            handle.write("CREATE TABLE `test_record` (`id` bigint NOT NULL);\n")

        for name, source in (("documents", self.documents), ("media", self.media)):
            previous = (
                self.backups / parent_id / f"{name}.manifest.json" if parent_id else ""
            )
            create_snapshot(
                str(source),
                str(output / f"{name}.tar.gz"),
                str(output / f"{name}.manifest.json"),
                str(output / f"{name}.delta.json"),
                name,
                mode,
                backup_set_id,
                base_id,
                parent_id,
                str(previous) if previous else "",
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
            "--fileset-mode", mode,
            "--base-backup-set-id", base_id,
            "--documents-manifest", str(output / "documents.manifest.json"),
            "--media-manifest", str(output / "media.manifest.json"),
        ]
        if parent_id:
            command.extend(("--parent-backup-set-id", parent_id))
        subprocess.run(command, check=True)

        names = (
            "database.sql.gz",
            "documents.tar.gz",
            "documents.manifest.json",
            "documents.delta.json",
            "media.tar.gz",
            "media.manifest.json",
            "media.delta.json",
            "manifest.json",
        )
        with open(output / "SHA256SUMS", "w", encoding="ascii", newline="\n") as handle:
            for name in names:
                handle.write(f"{sha256_file(output / name)}  {name}\n")
        return output

    def test_full_and_incremental_chain_is_selected_and_validated(self):
        full_id = "backup_set_20260720_020000"
        incremental_id = "backup_set_20260721_020000"
        (self.documents / "document.txt").write_text("before", encoding="utf-8")
        (self.media / "old.bin").write_bytes(b"old")
        full = self.create_set(full_id, "full", full_id)

        (self.documents / "document.txt").write_text("after", encoding="utf-8")
        (self.media / "old.bin").unlink()
        (self.media / "new.bin").write_bytes(b"new")
        incremental = self.create_set(incremental_id, "incremental", full_id, full_id)

        chain = resolve_chain(incremental)
        self.assertEqual([path.name for path, _ in chain], [full_id, incremental_id])

        selected = subprocess.run(
            [
                sys.executable,
                str(BACKUPS_DIR / "select_fileset_parent.py"),
                "--backup-root", str(self.backups),
            ],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.assertEqual(selected.split("\t")[:2], [incremental_id, full_id])

        plan_path = self.root / "restore-plan.json"
        subprocess.run(
            [
                sys.executable,
                str(BACKUPS_DIR / "validate_backup_chain.py"),
                "--backup-set-dir", str(incremental),
                "--output", str(plan_path),
            ],
            check=True,
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["chain"], [full_id, incremental_id])

        old_time = time.time() - 40 * 86400
        os.utime(full, (old_time, old_time))
        os.utime(incremental, (old_time, old_time))
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
        self.assertEqual(selected_paths, {full_id, incremental_id})

        os.utime(incremental, None)
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
        self.assertEqual(retained, b"")

        with open(full / "documents.tar.gz", "ab") as handle:
            handle.write(b"tampered")
        with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
            resolve_chain(incremental)


if __name__ == "__main__":
    unittest.main()

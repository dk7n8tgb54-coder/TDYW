import gzip
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


BACKUPS_DIR = Path(__file__).resolve().parents[2] / "backups"
sys.path.insert(0, str(BACKUPS_DIR))

from create_fileset_snapshot import create_snapshot


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupSetArtifactTests(unittest.TestCase):
    def test_complete_nonproduction_artifact_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = root / "documents-source"
            media = root / "media-source"
            output = root / "backup_set_test"
            documents.mkdir()
            media.mkdir()
            output.mkdir()
            (documents / "测试 文档.txt").write_text("document", encoding="utf-8")
            (media / "evidence.bin").write_bytes(b"evidence")

            database = output / "database.sql.gz"
            with gzip.open(database, "wt", encoding="utf-8") as handle:
                handle.write("CREATE TABLE `test_record` (`id` bigint NOT NULL);\n")
            checkpoints = root / "xtrabackup_checkpoints"
            checkpoints.write_text("backup_type = full-backuped\n", encoding="ascii")
            physical_database = output / "database.mariabackup.tar.gz"
            with tarfile.open(physical_database, "w:gz") as handle:
                handle.add(checkpoints, arcname="xtrabackup_checkpoints")

            create_snapshot(
                str(documents),
                str(output / "documents.tar.gz"),
                str(output / "documents.manifest.json"),
                str(output / "documents.delta.json"),
                "documents",
                "full",
                "backup_set_test",
                "backup_set_test",
            )
            create_snapshot(
                str(media),
                str(output / "media.tar.gz"),
                str(output / "media.manifest.json"),
                str(output / "media.delta.json"),
                "media",
                "full",
                "backup_set_test",
                "backup_set_test",
            )

            command = [
                sys.executable,
                str(BACKUPS_DIR / "create_backup_set_manifest.py"),
                "--output", str(output / "manifest.json"),
                "--backup-set-id", "backup_set_test",
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
                "--database-mode", "both",
                "--logical-database-artifact", str(database),
                "--physical-database-artifact", str(physical_database),
                "--fileset-mode", "full",
                "--base-backup-set-id", "backup_set_test",
                "--documents-manifest", str(output / "documents.manifest.json"),
                "--media-manifest", str(output / "media.manifest.json"),
            ]
            subprocess.run(command, check=True)

            checksum_names = [
                "database.sql.gz",
                "database.mariabackup.tar.gz",
                "documents.tar.gz",
                "media.tar.gz",
                "documents.manifest.json",
                "documents.delta.json",
                "media.manifest.json",
                "media.delta.json",
                "manifest.json",
            ]
            checksums = {
                name: sha256_file(output / name) for name in checksum_names
            }
            with open(output / "SHA256SUMS", "w", encoding="ascii", newline="\n") as handle:
                for name, digest in checksums.items():
                    handle.write(f"{digest}  {name}\n")

            with gzip.open(database, "rt", encoding="utf-8") as handle:
                self.assertIn("CREATE TABLE", handle.read())
            with tarfile.open(output / "documents.tar.gz", "r:gz") as handle:
                self.assertEqual(len(handle.getmembers()), 1)
            with tarfile.open(output / "media.tar.gz", "r:gz") as handle:
                self.assertEqual(len(handle.getmembers()), 1)

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "SUCCESS")
            self.assertEqual(manifest["schema_version"], 4)
            self.assertEqual(manifest["database"]["account"], "root@localhost")
            self.assertEqual(manifest["database"]["backup_mode"], "both")
            self.assertEqual(
                [item["type"] for item in manifest["database"]["artifacts"]],
                ["logical", "physical"],
            )
            self.assertEqual(
                manifest["database"]["artifacts"][1]["scope"], "server-instance"
            )
            self.assertEqual(manifest["fileset_chain"]["mode"], "full")
            self.assertEqual(manifest["filesets"]["documents"]["file_count"], 1)
            self.assertEqual(manifest["filesets"]["media"]["file_count"], 1)
            for name, expected in checksums.items():
                self.assertEqual(sha256_file(output / name), expected)


if __name__ == "__main__":
    unittest.main()

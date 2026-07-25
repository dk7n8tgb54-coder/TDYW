import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESTORE_SCRIPT = PROJECT_ROOT / "backups" / "mariabackup_prepare_restore.sh"


class MariabackupRestoreSafetyTests(unittest.TestCase):
    def test_database_stop_failure_never_starts_destructive_volume_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "xtrabackup_checkpoints"
            checkpoint.write_text("backup_type = full-backuped\n", encoding="ascii")
            archive = root / "database.mariabackup.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(checkpoint, arcname=checkpoint.name)

            binary_dir = root / "bin"
            binary_dir.mkdir()
            call_log = root / "docker.calls"
            fake_docker = binary_dir / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -u
printf '%s\\n' "$*" >>"${DOCKER_CALL_LOG}"
case "$1" in
  inspect)
    case "$*" in
      *'.Config.Image'*) echo 'mariadb:test' ;;
      *'.Mounts'*) echo 'volume|tdyw_db_data|/var/lib/docker/volumes/tdyw_db_data/_data' ;;
      *'.State.Running'*) echo 'true' ;;
    esac
    ;;
  run) exit 0 ;;
  stop) exit 1 ;;
esac
""",
                encoding="ascii",
            )
            fake_docker.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{binary_dir}:{environment['PATH']}",
                    "DOCKER_CALL_LOG": str(call_log),
                    "PHYSICAL_BACKUP_FILE": str(archive),
                    "FORCE_PHYSICAL_RESTORE": "YES",
                    "STOP_APP_CONTAINER": "NO",
                    "DB_CONTAINER": "tdyw-db-test",
                }
            )
            result = subprocess.run(
                ["bash", str(RESTORE_SCRIPT)],
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            calls = call_log.read_text(encoding="utf-8")
            self.assertIn("stop tdyw-db-test", calls)
            self.assertNotIn("type=volume", calls)


if __name__ == "__main__":
    unittest.main()

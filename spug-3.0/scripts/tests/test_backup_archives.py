import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKUPS_DIR = Path(__file__).resolve().parents[2] / "backups"
sys.path.insert(0, str(BACKUPS_DIR))

import create_fileset_archive as archive_tool
import restore_fileset_chain as restore_tool
from create_fileset_snapshot import create_snapshot
from restore_fileset_chain import restore_full, verify_target


class FilesetArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.output = self.root / "output"
        self.source.mkdir()
        self.output.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def create_archive(self):
        archive = self.output / "documents.tar.gz"
        manifest = self.output / "documents.manifest.json"
        archive_tool.create_archive(
            str(self.source), str(archive), str(manifest), "documents"
        )
        return archive, manifest

    def test_empty_directory_produces_readable_archive(self):
        archive, manifest = self.create_archive()
        with tarfile.open(archive, "r:gz") as handle:
            self.assertEqual(handle.getmembers(), [])
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["file_count"], 0)
        self.assertEqual(payload["total_bytes"], 0)

    def test_special_names_and_hashes_are_preserved(self):
        files = {
            "中文 空格.txt": b"alpha",
            "symbols-[]{}!@#.dat": b"gamma",
        }
        # Windows rejects newline characters in filenames; Linux runs cover this case.
        if os.name != "nt":
            files["line\nbreak.bin"] = b"beta"
        for name, content in files.items():
            (self.source / name).write_bytes(content)

        archive, manifest = self.create_archive()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        records = {item["relative_path"]: item for item in payload["files"]}
        self.assertEqual(set(records), set(files))
        for name, content in files.items():
            self.assertEqual(records[name]["size"], len(content))
            self.assertEqual(records[name]["sha256"], hashlib.sha256(content).hexdigest())

        with tarfile.open(archive, "r:gz") as handle:
            self.assertEqual({item.name for item in handle.getmembers()}, set(files))

    def test_symbolic_link_is_rejected(self):
        target = self.source / "target.txt"
        target.write_text("target", encoding="utf-8")
        link = self.source / "link.txt"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")

        with self.assertRaisesRegex(RuntimeError, "symbolic links are not allowed"):
            self.create_archive()

    def test_file_change_during_archive_is_rejected(self):
        changing = self.source / "changing.txt"
        changing.write_text("before", encoding="utf-8")
        original_hash = archive_tool.sha256_file

        def mutate_after_hash(path):
            digest = original_hash(path)
            Path(path).write_text("after-change", encoding="utf-8")
            return digest

        with mock.patch.object(archive_tool, "sha256_file", side_effect=mutate_after_hash):
            with self.assertRaisesRegex(RuntimeError, "file changed while being archived"):
                self.create_archive()

    def test_full_snapshot_is_self_contained_and_restorable(self):
        (self.source / "unchanged.txt").write_text("same", encoding="utf-8")
        (self.source / "changed.txt").write_text("current", encoding="utf-8")
        (self.source / "empty-dir").mkdir()

        full_archive = self.output / "documents.tar.gz"
        full_manifest = self.output / "documents.manifest.json"
        create_snapshot(
            str(self.source),
            str(full_archive),
            str(full_manifest),
            "documents",
            "backup_set_full",
        )
        final_manifest = json.loads(full_manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            [item["relative_path"] for item in final_manifest["files"]],
            ["changed.txt", "unchanged.txt"],
        )
        self.assertEqual(final_manifest["directories"], ["empty-dir"])
        with tarfile.open(full_archive, "r:gz") as handle:
            self.assertEqual(
                {item.name for item in handle.getmembers()},
                {"changed.txt", "unchanged.txt", "empty-dir"},
            )

        restore_target = self.root / "restore-target"
        restore_target.mkdir()
        (restore_target / "stray.txt").write_text("remove me", encoding="utf-8")
        restore_full(restore_target, full_archive, final_manifest)
        verify_target(restore_target, final_manifest)
        self.assertEqual((restore_target / "changed.txt").read_text(), "current")
        self.assertFalse((restore_target / "stray.txt").exists())

    def test_incremental_snapshot_request_is_rejected(self):
        result = subprocess.run(
            [
                sys.executable,
                str(BACKUPS_DIR / "create_fileset_snapshot.py"),
                "--name", "documents",
                "--source", str(self.source),
                "--archive", str(self.output / "incremental.tar.gz"),
                "--manifest", str(self.output / "incremental.manifest.json"),
                "--backup-set-id", "backup_set_incremental",
                "--mode", "incremental",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_partial_old_file_move_is_rolled_back_without_data_loss(self):
        (self.source / "a.txt").write_text("new-a", encoding="utf-8")
        (self.source / "c.txt").write_text("new-c", encoding="utf-8")
        archive = self.output / "documents.tar.gz"
        manifest_path = self.output / "documents.manifest.json"
        create_snapshot(
            str(self.source),
            str(archive),
            str(manifest_path),
            "documents",
            "backup_set_full",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        target = self.root / "rollback-target"
        target.mkdir()
        (target / "a.txt").write_text("old-a", encoding="utf-8")
        (target / "b.txt").write_text("old-b", encoding="utf-8")
        original_replace = restore_tool.os.replace

        def fail_on_second_old_file(source, destination):
            source_path = Path(source)
            destination_path = Path(destination)
            if source_path == target / "b.txt" and destination_path.parent.name.startswith(
                ".tdyw-restore-rollback-"
            ):
                raise OSError("simulated move failure")
            return original_replace(source, destination)

        with mock.patch.object(
            restore_tool.os, "replace", side_effect=fail_on_second_old_file
        ):
            with self.assertRaisesRegex(OSError, "simulated move failure"):
                restore_tool.restore_full(target, archive, manifest)

        self.assertEqual((target / "a.txt").read_text(encoding="utf-8"), "old-a")
        self.assertEqual((target / "b.txt").read_text(encoding="utf-8"), "old-b")
        self.assertFalse((target / "c.txt").exists())
        self.assertFalse(
            any(path.name.startswith(".tdyw-restore-") for path in target.iterdir())
        )


if __name__ == "__main__":
    unittest.main()

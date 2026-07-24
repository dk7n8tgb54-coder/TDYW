import hashlib
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BACKUPS_DIR = Path(__file__).resolve().parents[2] / "backups"
sys.path.insert(0, str(BACKUPS_DIR))

import create_fileset_archive as archive_tool
from create_fileset_snapshot import create_snapshot
from restore_fileset_chain import apply_deletions, clear_target, extract_delta, verify_target


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

    def test_incremental_snapshot_tracks_changes_and_deletions(self):
        unchanged = self.source / "unchanged.txt"
        changed = self.source / "changed.txt"
        removed = self.source / "removed.txt"
        unchanged.write_text("same", encoding="utf-8")
        changed.write_text("before", encoding="utf-8")
        removed.write_text("remove", encoding="utf-8")

        full_archive = self.output / "full.tar.gz"
        full_manifest = self.output / "full.manifest.json"
        create_snapshot(
            str(self.source),
            str(full_archive),
            str(full_manifest),
            str(self.output / "full.delta.json"),
            "documents",
            "full",
            "backup_set_full",
            "backup_set_full",
        )

        changed.write_text("after", encoding="utf-8")
        removed.unlink()
        (self.source / "added.txt").write_text("add", encoding="utf-8")
        (self.source / "empty-dir").mkdir()

        incremental_archive = self.output / "incremental.tar.gz"
        incremental_manifest = self.output / "incremental.manifest.json"
        incremental_delta = self.output / "incremental.delta.json"
        create_snapshot(
            str(self.source),
            str(incremental_archive),
            str(incremental_manifest),
            str(incremental_delta),
            "documents",
            "incremental",
            "backup_set_incremental",
            "backup_set_full",
            "backup_set_full",
            str(full_manifest),
        )

        delta = json.loads(incremental_delta.read_text(encoding="utf-8"))
        self.assertEqual(delta["added_or_changed_files"], ["added.txt", "changed.txt"])
        self.assertEqual(delta["deleted_files"], ["removed.txt"])
        self.assertEqual(delta["added_directories"], ["empty-dir"])
        with tarfile.open(incremental_archive, "r:gz") as handle:
            self.assertEqual(
                {item.name for item in handle.getmembers()},
                {"added.txt", "changed.txt", "empty-dir"},
            )

        restore_target = self.root / "restore-target"
        restore_target.mkdir()
        (restore_target / "stray.txt").write_text("remove me", encoding="utf-8")
        clear_target(restore_target)
        for archive, delta_path in (
            (full_archive, self.output / "full.delta.json"),
            (incremental_archive, incremental_delta),
        ):
            delta_payload = json.loads(delta_path.read_text(encoding="utf-8"))
            apply_deletions(restore_target, delta_payload)
            extract_delta(restore_target, archive, delta_payload)
        final_manifest = json.loads(incremental_manifest.read_text(encoding="utf-8"))
        verify_target(restore_target, final_manifest)
        self.assertEqual((restore_target / "changed.txt").read_text(), "after")
        self.assertFalse((restore_target / "removed.txt").exists())


if __name__ == "__main__":
    unittest.main()

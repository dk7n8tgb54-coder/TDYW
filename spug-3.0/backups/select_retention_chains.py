#!/usr/bin/env python3
"""Emit expired, independently verified full backup-set directories."""

import argparse
import os
import sys
import time
from pathlib import Path

from backup_chain import BACKUP_SET_PATTERN, validate_member


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--retention-days", type=int, required=True)
    args = parser.parse_args()

    root = Path(args.backup_root).resolve()
    if not root.is_dir() or args.retention_days < 0:
        return
    cutoff = time.time() - args.retention_days * 86400

    for path in sorted(root.iterdir()):
        if (
            not path.is_dir()
            or path.is_symlink()
            or not BACKUP_SET_PATTERN.fullmatch(path.name)
            or path.stat().st_mtime >= cutoff
        ):
            continue
        try:
            validate_member(path)
        except (OSError, ValueError, RuntimeError):
            continue
        resolved = path.resolve()
        if resolved.parent == root:
            sys.stdout.buffer.write(os.fsencode(str(resolved)) + b"\0")


if __name__ == "__main__":
    main()

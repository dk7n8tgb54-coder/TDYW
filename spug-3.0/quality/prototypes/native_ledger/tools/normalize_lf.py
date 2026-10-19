#!/usr/bin/env python
"""Normalize prototype and report text files to LF without touching content."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT.parents[1] / "reports" / "native_ledger_poc"
SUFFIXES = {".js", ".jsx", ".css", ".json", ".md", ".html", ".py", ".txt", ".yml", ".yaml"}
changed = 0
for base in (ROOT, REPORT):
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if "node_modules" in path.parts or ".pydeps" in path.parts or ".npm-cache" in path.parts:
            continue
        data = path.read_bytes()
        normalized = data.replace(b"\r\n", b"\n")
        if normalized != data:
            path.write_bytes(normalized)
            changed += 1
print(f"normalized={changed}")

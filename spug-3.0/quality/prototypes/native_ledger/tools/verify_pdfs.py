#!/usr/bin/env python
"""Verify final PDF geometry, embedded fonts and filled values."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT.parents[1] / "reports" / "native_ledger_poc"
sys.path.insert(0, str(ROOT / ".pydeps"))
import fitz  # noqa: E402

PDFS = {
    "A4_landscape": REPORT / "native-ledger_A4_landscape.pdf",
    "A3_landscape": REPORT / "native-ledger_A3_landscape.pdf",
    "A4_portrait_fit": REPORT / "native-ledger_A4_portrait.pdf",
    "A4_portrait_actual": REPORT / "native-ledger_A4_portrait_actual.pdf",
}
CHECKS = ["TX-2026-Q3-002", "李敏", "2026-09-20", "1.22", "43.6", "2026 年第三季度"]

result = {}
for name, path in PDFS.items():
    doc = fitz.open(path)
    pages = []
    for page in doc:
        rect = page.rect
        text = page.get_text()
        pages.append({
            "width_mm": round(rect.width * 25.4 / 72, 1),
            "height_mm": round(rect.height * 25.4 / 72, 1),
            "text_chars": len(text),
            "checks": {word: word in text for word in CHECKS},
            "fonts": sorted({font[3] for font in page.get_fonts(full=True)}),
        })
    result[name] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "page_count": doc.page_count,
        "pages": pages,
    }

target = REPORT / "pdf_verification.json"
target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=True, indent=2))
print(f"WROTE {target}")

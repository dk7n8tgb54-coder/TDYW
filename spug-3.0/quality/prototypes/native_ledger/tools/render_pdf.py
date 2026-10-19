#!/usr/bin/env python
"""Render a PDF to PNG pages and print page geometry/text checks."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".pydeps"))
import fitz  # noqa: E402

pdf_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
prefix = sys.argv[3]
out_dir.mkdir(parents=True, exist_ok=True)
doc = fitz.open(pdf_path)
print(f"file={pdf_path.name} pages={doc.page_count}")
for index, page in enumerate(doc):
    rect = page.rect
    print(
        f"page={index + 1} size_pt={rect.width:.1f}x{rect.height:.1f} "
        f"size_mm={rect.width * 25.4 / 72:.1f}x{rect.height * 25.4 / 72:.1f}"
    )
    text = page.get_text().strip()
    print(f"  text_chars={len(text)} first={text[:110]!r}")
    image = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    target = out_dir / f"{prefix}_page{index + 1}.png"
    image.save(target)
    print(f"  png={target} {image.width}x{image.height}")

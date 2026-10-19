import { colName } from "./template";

export function collectBatchBindings({
  worksheet,
  existingBindings = [],
  labelPrefix = "",
  type = "text",
  limit = 200,
}) {
  let ranges = [];
  try {
    ranges = worksheet.getSelection().getActiveRangeList();
  } catch {
    return { additions: [], skipped: 0, reason: "no-selection" };
  }
  if (!ranges.length) return { additions: [], skipped: 0, reason: "no-selection" };

  const existing = new Set(existingBindings.map((item) => item.range));
  const seen = new Set();
  const additions = [];
  let skipped = 0;
  let capped = false;

  for (const range of ranges) {
    const box = range.getRange();
    for (let row = box.startRow; row <= box.endRow; row += 1) {
      for (let col = box.startColumn; col <= box.endColumn; col += 1) {
        const cell = worksheet.getRange(row, col).getCell();
        const merge = cell.mergeInfo || cell;
        if (merge.startRow !== row || merge.startColumn !== col) continue;
        const address = `${colName(col)}${row + 1}`;
        if (seen.has(address)) continue;
        seen.add(address);
        if (existing.has(address)) {
          skipped += 1;
          continue;
        }
        if (additions.length >= limit) {
          capped = true;
          break;
        }
        additions.push({
          id: `bind-batch-${Date.now()}-${row}-${col}`,
          key: `batch_${Date.now()}_${row}_${col}`,
          label: `${labelPrefix || "批量字段"} ${address}`,
          section: "批量绑定",
          range: address,
          type,
          placeholder: type === "status" ? "正常 / 不正常" : "",
        });
      }
      if (capped) break;
    }
    if (capped) break;
  }

  return { additions, skipped, capped, reason: additions.length ? "ok" : "empty" };
}

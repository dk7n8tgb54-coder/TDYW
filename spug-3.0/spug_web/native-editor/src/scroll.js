export function readViewportScroll(worksheet) {
  try {
    const state = worksheet.getScrollState?.()
      || { offsetX: 0, offsetY: 0, sheetViewStartRow: 0, sheetViewStartColumn: 0 };
    const skeleton = worksheet.getSkeleton?.();
    const start = skeleton?.getCellWithCoordByIndex?.(
      state.sheetViewStartRow || 0,
      state.sheetViewStartColumn || 0,
      false,
    );
    return {
      x: (start?.startX || 0) + (state.offsetX || 0),
      y: (start?.startY || 0) + (state.offsetY || 0),
    };
  } catch {
    return { x: 0, y: 0 };
  }
}

import { createUniver, LocaleType } from "@univerjs/presets";
import { UniverSheetsCorePreset } from "@univerjs/preset-sheets-core";
import zhCN from "@univerjs/preset-sheets-core/locales/zh-CN";
import "@univerjs/preset-sheets-core/lib/index.css";

export function createLedgerUniver(containerId) {
  const { univer, univerAPI } = createUniver({
    locale: LocaleType.ZH_CN,
    locales: { [LocaleType.ZH_CN]: zhCN },
    presets: [
      UniverSheetsCorePreset({
        container: containerId,
        header: true,
        toolbar: true,
        footer: false,
        formulaBar: true,
        disableAutoFocus: true,
      }),
    ],
  });
  return { univer, univerAPI };
}

export function loadSnapshot(univerAPI, previousId, snapshot, zoom = 0.75) {
  if (previousId) {
    try {
      univerAPI.disposeUnit(previousId);
    } catch {
      // Unit may already be disposed during a fast mode switch.
    }
  }
  const sheetId = snapshot.sheetOrder?.[0];
  if (sheetId && snapshot.sheets?.[sheetId]) {
    snapshot.sheets[sheetId].zoomRatio = zoom;
  }
  const fWorkbook = univerAPI.createWorkbook(snapshot);
  const fWorksheet = fWorkbook.getActiveSheet();
  return { fWorkbook, fWorksheet, id: fWorkbook.getId() };
}

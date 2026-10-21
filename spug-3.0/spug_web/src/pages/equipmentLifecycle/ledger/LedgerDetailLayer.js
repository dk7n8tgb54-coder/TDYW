/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 台账详情与创建弹窗层（自 LedgerIndex 拆出）：按来源渲染 Excel/手工
 * 详情视图并承载创建弹窗；LedgerIndex 只负责视图切换与回调接线。
 */
import React from 'react';
import ExcelLedgerCreateModal from './excel/ExcelLedgerCreateModal';
import ExcelLedgerDetail from './excel/ExcelLedgerDetail';
import LedgerDetail from './LedgerDetail';

export default function LedgerDetailLayer({
  store, excelStore, ledgerType,
  excelCreateVisible,
  onExcelCreateCancel,
  onExcelDetailBack,
}) {
  const excelDetailOpen = !!excelStore.detail;
  return (
    <React.Fragment>
      {excelDetailOpen && (
        <ExcelLedgerDetail store={excelStore} onBack={onExcelDetailBack}/>
      )}
      {store.detailVisible && <LedgerDetail store={store}/>}
      <ExcelLedgerCreateModal
        visible={excelCreateVisible}
        ledgerType={ledgerType}
        store={excelStore}
        onCancel={onExcelCreateCancel}
        onCreated={onExcelCreateCancel}/>
    </React.Fragment>
  );
}

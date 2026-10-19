/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 台账详情与创建弹窗层（自 LedgerIndex 拆出）：按来源渲染 Excel/原生/
 * 手工详情视图并承载两种创建弹窗；LedgerIndex 只负责视图切换与回调接线。
 */
import React from 'react';
import ExcelLedgerCreateModal from './excel/ExcelLedgerCreateModal';
import ExcelLedgerDetail from './excel/ExcelLedgerDetail';
import NativeLedgerCreateModal from './native/NativeLedgerCreateModal';
import NativeLedgerDetail from './native/NativeLedgerDetail';
import LedgerDetail from './LedgerDetail';

export default function LedgerDetailLayer({
  store, excelStore, nativeStore, ledgerType,
  excelCreateVisible, nativeCreateVisible,
  onExcelCreateCancel, onNativeCreateCancel,
  onExcelDetailBack, onNativeDetailBack,
}) {
  const excelDetailOpen = !!excelStore.detail;
  const nativeDetailOpen = !!nativeStore.detail;
  return (
    <React.Fragment>
      {excelDetailOpen && (
        <ExcelLedgerDetail store={excelStore} onBack={onExcelDetailBack}/>
      )}
      {nativeDetailOpen && (
        <NativeLedgerDetail store={nativeStore} onBack={onNativeDetailBack}/>
      )}
      {store.detailVisible && <LedgerDetail store={store}/>}
      <ExcelLedgerCreateModal
        visible={excelCreateVisible}
        ledgerType={ledgerType}
        store={excelStore}
        onCancel={onExcelCreateCancel}
        onCreated={onExcelCreateCancel}/>
      <NativeLedgerCreateModal
        visible={nativeCreateVisible}
        ledgerType={ledgerType}
        store={nativeStore}
        onCancel={onNativeCreateCancel}
        onCreated={onNativeCreateCancel}/>
    </React.Fragment>
  );
}

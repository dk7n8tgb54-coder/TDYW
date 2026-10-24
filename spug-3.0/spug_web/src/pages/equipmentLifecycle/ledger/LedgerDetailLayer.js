/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 台账详情与创建弹窗层（自 LedgerIndex 拆出）：按来源渲染 Excel/数字表单/
 * 手工详情视图并承载创建弹窗；LedgerIndex 只负责视图切换与回调接线。
 * 数字表单路线（2026-10-21）：FormLedgerDetail 表单填写视图 +
 * FormLedgerCreateModal 数字表单创建弹窗。
 */
import React from 'react';
import ExcelLedgerCreateModal from './excel/ExcelLedgerCreateModal';
import ExcelLedgerDetail from './excel/ExcelLedgerDetail';
import FormLedgerCreateModal from './form/FormLedgerCreateModal';
import FormLedgerDetail from './form/FormLedgerDetail';
import LedgerDetail from './LedgerDetail';

export default function LedgerDetailLayer({
  store, excelStore, formStore, ledgerType,
  excelCreateVisible, formCreateVisible,
  onExcelCreateCancel, onFormCreateCancel,
  onExcelDetailBack, onFormDetailBack,
}) {
  const excelDetailOpen = !!excelStore.detail;
  const formDetailOpen = !!formStore.detail;
  return (
    <React.Fragment>
      {excelDetailOpen && (
        <ExcelLedgerDetail store={excelStore} onBack={onExcelDetailBack}/>
      )}
      {formDetailOpen && (
        <FormLedgerDetail store={formStore} onBack={onFormDetailBack}/>
      )}
      {store.detailVisible && <LedgerDetail store={store}/>}
      <ExcelLedgerCreateModal
        visible={excelCreateVisible}
        ledgerType={ledgerType}
        store={excelStore}
        onCancel={onExcelCreateCancel}
        onCreated={onExcelCreateCancel}/>
      <FormLedgerCreateModal
        visible={formCreateVisible}
        ledgerType={ledgerType}
        store={formStore}
        onCancel={onFormCreateCancel}
        onCreated={onFormCreateCancel}/>
    </React.Fragment>
  );
}

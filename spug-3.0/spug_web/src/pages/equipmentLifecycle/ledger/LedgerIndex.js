/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账列表页：周月维护 / 季维护 共用，ledgerType 由路由入口注入。
 * 周月维护不再拆分周表/月表（2026-09-26），无维护周期筛选与列。
 * 旧巡检台账（历史）入口已删除（2026-09-24），巡检业务走独立巡检单。
 *
 * 统一维护台账列表（2026-10）：Excel 模板 / 手工补录路线台账一并展示，
 * 按后端 source_type 区分详情路由（Excel 来源点击详情进入 ExcelLedgerDetail
 * 版本快照版式回放；原生模板路线已随 2026-10-20 整体下线删除）；正式新增
 * 台账选择已发布的 Excel/WPS 模板版本创建（旧可视化模板路线已整体删除）。
 * 详情与创建弹窗承载在 LedgerDetailLayer（本组件只负责视图切换与接线）。
 *
 * 视图切换（2026-10-11，默认"按维护周期"）：
 * - 按维护周期：LedgerPeriodView（维护类型＋周期分组，组内各系统台账）；
 * - 按模板查看：LedgerTemplateView（模板身份分组统计 → 组内台账分页列表，
 *   组内不混手工补录）；refresh 按当前视图分发刷新，返回/详情返回后视图
 *   与筛选状态保留。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Radio} from 'antd';
import {AuthDiv, Breadcrumb} from 'components';
import useWorkTabUnsaved from 'layout/useWorkTabUnsaved';
import LedgerPeriodView from './LedgerPeriodView';
import LedgerTemplateView from './LedgerTemplateView';
import LedgerDetailLayer from './LedgerDetailLayer';
import LedgerPeriodGenerateModal from './LedgerPeriodGenerateModal';
import LedgerMultiExportModal from './LedgerMultiExportModal';
import {ExcelLedgerStore} from './excel/excelLedgerStore';
import {FormLedgerStore} from './form/formLedgerStore';
import {getLedgerStore} from './store';
import {buildColumns, sourceTypeOf} from './LedgerColumns';
import {PERM_L} from './constants';

/** 详情/创建/生成/导出弹窗承载（自 LedgerIndex 函数体抽出，控制函数行数）。 */
function LedgerLayersHost(props) {
  return (
    <React.Fragment>
      <LedgerDetailLayer
        store={props.store}
        excelStore={props.excelStore}
        formStore={props.formStore}
        ledgerType={props.ledgerType}
        excelCreateVisible={props.excelCreateVisible}
        formCreateVisible={props.formCreateVisible}
        onExcelCreateCancel={props.onExcelCreateCancel}
        onFormCreateCancel={props.onFormCreateCancel}
        onExcelDetailBack={props.onExcelDetailBack}
        onFormDetailBack={props.onFormDetailBack}/>
      <LedgerPeriodGenerateModal
        visible={props.generateVisible}
        ledgerType={props.ledgerType}
        store={props.store}
        onCancel={props.onGenerateCancel}/>
      {/* "批量导出 PDF"弹窗（2026-10-21）：两个视图共用，按当前 ledgerType 拉取候选 */}
      <LedgerMultiExportModal store={props.store}/>
    </React.Fragment>
  );
}

function LedgerIndex({ledgerType, location}) {
  const store = getLedgerStore(ledgerType);
  // Excel 路线详情独立 Store（与试点页单例隔离，互不干扰）
  const [excelStore] = useState(() => new ExcelLedgerStore());
  // 数字表单路线详情独立 Store（2026-10-21 数字表单路线）
  const [formStore] = useState(() => new FormLedgerStore());
  const [excelCreateVisible, setExcelCreateVisible] = useState(false);
  const [formCreateVisible, setFormCreateVisible] = useState(false);
  const [generateVisible, setGenerateVisible] = useState(false);
  // Excel/数字表单详情填写有未保存修改时，当前页签不参与自动淘汰（翻阅视图
  // 的独立 Store 由 LedgerGroupBrowse 自行登记）
  useWorkTabUnsaved(!!excelStore.hasUnsaved || !!formStore.hasUnsaved);

  useEffect(() => {
    // 跨页跳转直达详情（故障详情跳入：?detail=<台账ID>；
    // Excel 来源跳转：?detail=<ID>&source=excel；数字表单：source=form）
    const params = new URLSearchParams(location ? location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      const source = params.get('source');
      if (source === 'excel') {
        excelStore.fetchDetail(parseInt(detailId, 10)).catch(() => {});
      } else if (source === 'form') {
        formStore.fetchDetail(parseInt(detailId, 10)).catch(() => {});
      } else {
        store.fetchDetail(parseInt(detailId, 10));
      }
    }
    store.refresh();
    store.fetchSystemOptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDetail = record => {
    const source = sourceTypeOf(record);
    if (source === 'excel') {
      excelStore.fetchDetail(record.id).catch(() => {});
    } else if (source === 'form') {
      formStore.fetchDetail(record.id).catch(() => {});
    } else {
      store.fetchDetail(record.id);
    }
  };

  const handleExcelDetailBack = () => {
    excelStore.applyDetail(null);
    store.refresh();
  };

  const handleFormDetailBack = () => {
    formStore.applyDetail(null);
    store.refresh();
  };

  const columns = buildColumns(store, ledgerType, openDetail);
  const detailLayerOpen = !!excelStore.detail || !!formStore.detail;

  return (
    <AuthDiv auth={PERM_L.LED_VIEW}>
      {store.viewMode === 'template' && (
        <Breadcrumb>
          <Breadcrumb.Item>按模板查看</Breadcrumb.Item>
          {!!store.activeGroup && (
            <Breadcrumb.Item>{store.activeGroup.group_name}</Breadcrumb.Item>
          )}
          {!!store.browseState && (
            <Breadcrumb.Item>翻阅台账</Breadcrumb.Item>
          )}
        </Breadcrumb>
      )}
      {!detailLayerOpen && (
        <React.Fragment>
          <div style={{marginBottom: 8}}>
            <Radio.Group
              value={store.viewMode}
              onChange={e => store.setViewMode(e.target.value)}
              optionType="button"
              buttonStyle="solid">
              <Radio.Button value="period">按维护周期</Radio.Button>
              <Radio.Button value="template">按模板查看</Radio.Button>
            </Radio.Group>
          </div>
          {store.viewMode === 'period' && (
            <LedgerPeriodView
              store={store}
              ledgerType={ledgerType}
              columns={columns}
              onGenerate={() => setGenerateVisible(true)}
              onExcelCreate={() => setExcelCreateVisible(true)}
              onFormCreate={() => setFormCreateVisible(true)}
              onMultiExport={() => store.openMultiExport()}/>
          )}
          {store.viewMode === 'template' && (
            <LedgerTemplateView
              store={store}
              ledgerType={ledgerType}
              openDetail={openDetail}
              onGenerate={() => setGenerateVisible(true)}
              onOpenExcelCreate={() => setExcelCreateVisible(true)}
              onOpenFormCreate={() => setFormCreateVisible(true)}
              onMultiExport={() => store.openMultiExport()}/>
          )}
        </React.Fragment>
      )}
      <LedgerLayersHost
        store={store}
        excelStore={excelStore}
        formStore={formStore}
        ledgerType={ledgerType}
        excelCreateVisible={excelCreateVisible}
        formCreateVisible={formCreateVisible}
        onExcelCreateCancel={() => setExcelCreateVisible(false)}
        onFormCreateCancel={() => setFormCreateVisible(false)}
        onExcelDetailBack={handleExcelDetailBack}
        onFormDetailBack={handleFormDetailBack}
        generateVisible={generateVisible}
        onGenerateCancel={() => setGenerateVisible(false)}/>
    </AuthDiv>
  );
}

export default observer(LedgerIndex);

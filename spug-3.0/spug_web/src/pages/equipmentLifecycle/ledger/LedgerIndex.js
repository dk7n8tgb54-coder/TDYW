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
 * 版本快照版式回放）；正式新增台账统一走 Excel/WPS 模板路线
 * （旧可视化模板路线已整体删除）。
 *
 * 视图切换（2026-10-11，默认"按维护周期"）：
 * - 按维护周期：LedgerPeriodView（维护类型＋周期分组，组内各系统台账）；
 * - 按模板查看：LedgerTemplateView（模板身份分组统计 → 组内台账分页列表，
 *   组内不混手工补录）；refresh 按当前视图分发刷新，返回/详情返回后
 *   视图与筛选状态保留。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Radio} from 'antd';
import {AuthDiv, Breadcrumb} from 'components';
import LedgerPeriodView from './LedgerPeriodView';
import LedgerTemplateView from './LedgerTemplateView';
import LedgerDetail from './LedgerDetail';
import LedgerPeriodGenerateModal from './LedgerPeriodGenerateModal';
import ExcelLedgerCreateModal from './excel/ExcelLedgerCreateModal';
import ExcelLedgerDetail from './excel/ExcelLedgerDetail';
import {ExcelLedgerStore} from './excel/excelLedgerStore';
import {getLedgerStore} from './store';
import {buildColumns, sourceTypeOf} from './LedgerColumns';
import {LEDGER_TYPE_TEXT, PERM_L} from './constants';

function LedgerIndex({ledgerType, location}) {
  const store = getLedgerStore(ledgerType);
  // Excel 路线详情独立 Store（与试点页单例隔离，互不干扰）
  const [excelStore] = useState(() => new ExcelLedgerStore());
  const [excelCreateVisible, setExcelCreateVisible] = useState(false);
  const [generateVisible, setGenerateVisible] = useState(false);

  useEffect(() => {
    // 跨页跳转直达详情（故障详情跳入：?detail=<台账ID>；
    // Excel 来源跳转：?detail=<台账ID>&source=excel 打开 Excel 详情）
    const params = new URLSearchParams(location ? location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      if (params.get('source') === 'excel') {
        excelStore.fetchDetail(parseInt(detailId, 10)).catch(() => {});
      } else {
        store.fetchDetail(parseInt(detailId, 10));
      }
    }
    store.refresh();
    store.fetchSystemOptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDetail = record => {
    if (sourceTypeOf(record) === 'excel') {
      excelStore.fetchDetail(record.id).catch(() => {});
    } else {
      store.fetchDetail(record.id);
    }
  };

  const handleExcelCreated = () => {
    // 创建成功后 excelStore 已持有详情（createLedger 内 applyDetail），
    // 关闭弹窗即切换到 Excel 台账填写详情
    setExcelCreateVisible(false);
  };

  const handleExcelDetailBack = () => {
    excelStore.applyDetail(null);
    store.refresh();
  };

  const columns = buildColumns(store, ledgerType, openDetail);
  const excelDetailOpen = !!excelStore.detail;

  return (
    <AuthDiv auth={PERM_L.LED_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备管理</Breadcrumb.Item>
        <Breadcrumb.Item>维护台账</Breadcrumb.Item>
        <Breadcrumb.Item>{LEDGER_TYPE_TEXT[ledgerType]}台账</Breadcrumb.Item>
        {store.viewMode === 'template' && (
          <Breadcrumb.Item>按模板查看</Breadcrumb.Item>
        )}
        {store.viewMode === 'template' && !!store.activeGroup && (
          <Breadcrumb.Item>{store.activeGroup.group_name}</Breadcrumb.Item>
        )}
        {store.viewMode === 'template' && !!store.browseState && (
          <Breadcrumb.Item>翻阅台账</Breadcrumb.Item>
        )}
      </Breadcrumb>
      {!excelDetailOpen && (
        <React.Fragment>
          <div style={{marginBottom: 12}}>
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
              onExcelCreate={() => setExcelCreateVisible(true)}/>
          )}
          {store.viewMode === 'template' && (
            <LedgerTemplateView
              store={store}
              ledgerType={ledgerType}
              openDetail={openDetail}
              onGenerate={() => setGenerateVisible(true)}
              onOpenExcelCreate={() => setExcelCreateVisible(true)}/>
          )}
        </React.Fragment>
      )}
      {excelDetailOpen && (
        <ExcelLedgerDetail store={excelStore} onBack={handleExcelDetailBack}/>
      )}
      {store.detailVisible && <LedgerDetail store={store}/>}
      <ExcelLedgerCreateModal
        visible={excelCreateVisible}
        ledgerType={ledgerType}
        store={excelStore}
        onCancel={() => setExcelCreateVisible(false)}
        onCreated={handleExcelCreated}/>
      <LedgerPeriodGenerateModal
        visible={generateVisible}
        ledgerType={ledgerType}
        store={store}
        onCancel={() => setGenerateVisible(false)}/>
    </AuthDiv>
  );
}

export default observer(LedgerIndex);

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
 * 版本快照版式回放）并渲染 Excel模板列；来源/明细数/异常数列已删除（2026-10）。
 * 正式新增台账入口（2026-10 收口）：不再提供"可视化表格 / Excel 模板"
 * 二选一，直接选择当前类型已发布的 Excel/WPS 模板版本创建 Excel 台账
 * （旧可视化模板路线已整体删除）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Input, Select, Button, Tag, Popconfirm} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {SearchForm, AuthDiv, Breadcrumb, AuthButton, ExportButton} from 'components';
import ComTable from './LedgerTable';
import LedgerDetail from './LedgerDetail';
import ExcelLedgerCreateModal from './excel/ExcelLedgerCreateModal';
import ExcelLedgerDetail from './excel/ExcelLedgerDetail';
import {ExcelLedgerStore} from './excel/excelLedgerStore';
import {getLedgerStore} from './store';
import {
  API_PREFIX_L, LEDGER_TYPE_TEXT, PERM_L, STATUS_COLOR, STATUS_TEXT,
} from './constants';

/** 来源类型：优先取后端 source_type，兼容旧数据仅返回 created_from 的形态。 */
function sourceTypeOf(record) {
  if (record.source_type) return record.source_type;
  if (record.created_from === 'excel_template') return 'excel';
  return 'manual';
}

function buildColumns(store, ledgerType, openDetail) {
  return [
    {title: '台账编号', dataIndex: 'ledger_no', width: 190},
    {title: '实际执行日期', dataIndex: 'executed_date', width: 110},
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: v => <Tag color={STATUS_COLOR[v]}>{STATUS_TEXT[v] || v}</Tag>,
    },
    {title: '执行人', dataIndex: 'executor_names', width: 140, ellipsis: true},
    {
      title: 'Excel模板', key: 'excel_template', width: 170, ellipsis: true,
      render: (v, record) => sourceTypeOf(record) === 'excel' && record.source_template_name
        ? `${record.source_template_name} v${record.source_version_no || ''}` : '—',
    },
    {title: '录入人', dataIndex: 'created_by_name', width: 100},
    {title: '录入时间', dataIndex: 'created_at', width: 160},
    {
      title: '操作', width: 150, align: 'center',
      render: (text, record) => {
        const isExcel = sourceTypeOf(record) === 'excel';
        return (
          <span>
            <a onClick={() => openDetail(record)}>详情</a>
            {!isExcel && record.status === 'draft' && (
              <AuthButton auth={PERM_L.LED_SUBMIT}>
                <Popconfirm
                  title={`确定提交${LEDGER_TYPE_TEXT[ledgerType]}台账？`}
                  onConfirm={() => store.submitLedger(record.id)}>
                  <a style={{marginLeft: 8}}>提交</a>
                </Popconfirm>
              </AuthButton>
            )}
            {record.status !== 'void' && (
              <AuthButton auth={PERM_L.LED_DEL}>
                <Popconfirm
                  title="作废后台账不参与统计，确定作废？"
                  onConfirm={() => store.voidLedger(record.id, '列表受控作废')}>
                  <a style={{marginLeft: 8, color: '#f5222d'}}>作废</a>
                </Popconfirm>
              </AuthButton>
            )}
          </span>
        );
      },
    },
  ];
}

// observer：筛选控件直接读取 store.f_keyword / f_status，输入后需触发重渲染
const LedgerSearchForm = observer(function LedgerSearchForm({store}) {
  return (
    <SearchForm>
      <SearchForm.Item span={6} title="台账编号">
        <Input
          allowClear
          value={store.f_keyword}
          onChange={e => store.f_keyword = e.target.value}
          placeholder="请输入台账编号"
          onPressEnter={() => {
            store.page = 1;
            store.fetchRecords();
          }}
        />
      </SearchForm.Item>
      <SearchForm.Item span={6} title="状态">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_status}
          onChange={v => {
            store.f_status = v;
            store.page = 1;
            store.fetchRecords();
          }}
          placeholder="请选择状态">
          {Object.keys(STATUS_TEXT).map(key => (
            <Select.Option value={key} key={key}>{STATUS_TEXT[key]}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
    </SearchForm>
  );
});

function LedgerIndex({ledgerType, location}) {
  const store = getLedgerStore(ledgerType);
  // Excel 路线详情独立 Store（与试点页单例隔离，互不干扰）
  const [excelStore] = useState(() => new ExcelLedgerStore());
  const [excelCreateVisible, setExcelCreateVisible] = useState(false);

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
    store.fetchRecords();
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
    store.fetchRecords();
  };

  const columns = buildColumns(store, ledgerType, openDetail);
  const excelDetailOpen = !!excelStore.detail;

  return (
    <AuthDiv auth={PERM_L.LED_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
        <Breadcrumb.Item>巡视与维护</Breadcrumb.Item>
        <Breadcrumb.Item>{LEDGER_TYPE_TEXT[ledgerType]}台账</Breadcrumb.Item>
      </Breadcrumb>
      {!excelDetailOpen && (
        <React.Fragment>
          <LedgerSearchForm store={store}/>
          <div style={{marginBottom: 12}}>
            <AuthButton
              auth={PERM_L.LED_ADD}
              type="primary"
              icon={<PlusOutlined/>}
              onClick={() => setExcelCreateVisible(true)}>
              新增{LEDGER_TYPE_TEXT[ledgerType]}台账
            </AuthButton>
            <ExportButton
              auth={PERM_L.LED_EXPORT}
              style={{marginLeft: 8}}
              url={`${API_PREFIX_L}/ledgers/export/?ledger_type=${ledgerType}`}
              filename={`${LEDGER_TYPE_TEXT[ledgerType]}台账.csv`}>
              导出
            </ExportButton>
          </div>
          <ComTable store={store} columns={columns}/>
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
    </AuthDiv>
  );
}

export default observer(LedgerIndex);

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账列表页：巡检 / 周月维护 / 季维护 共用，ledgerType 由路由入口注入。
 * 周月维护单入口，通过"维护周期"筛选区分周与月。
 */
import React, {useEffect} from 'react';
import {observer} from 'mobx-react';
import {Input, Select, Button, Tag, Popconfirm} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {SearchForm, AuthDiv, Breadcrumb, AuthButton, ExportButton} from 'components';
import ComTable from './LedgerTable';
import ComForm from './LedgerForm';
import LedgerDetail from './LedgerDetail';
import {getLedgerStore} from './store';
import {API_PREFIX_L, CYCLE_TEXT, LEDGER_TYPE, LEDGER_TYPE_TEXT, PERM_L, STATUS_COLOR, STATUS_TEXT} from './constants';

function LedgerIndex({ledgerType, location}) {
  const store = getLedgerStore(ledgerType);
  const isWeekMonth = ledgerType === LEDGER_TYPE.WEEK_MONTH;

  useEffect(() => {
    // 跨页跳转直达详情（故障详情/工单详情跳入：?detail=<台账ID>）
    const params = new URLSearchParams(location ? location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.fetchDetail(parseInt(detailId, 10));
    }
    store.fetchRecords();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const columns = [
    {title: '台账编号', dataIndex: 'ledger_no', width: 190},
    ...(isWeekMonth ? [{
      title: '维护周期', dataIndex: 'maintenance_cycle', width: 80,
      render: v => CYCLE_TEXT[v] || '-',
    }] : []),
    {title: '实际执行日期', dataIndex: 'executed_date', width: 110},
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: v => <Tag color={STATUS_COLOR[v]}>{STATUS_TEXT[v] || v}</Tag>,
    },
    {title: '执行人', dataIndex: 'executor_names', width: 140, ellipsis: true},
    {title: '明细数', dataIndex: 'items_count', width: 70, align: 'center'},
    {
      title: '异常数', dataIndex: 'abnormal_count', width: 70, align: 'center',
      render: v => v > 0 ? <span style={{color: '#f5222d', fontWeight: 'bold'}}>{v}</span> : v,
    },
    {title: '录入人', dataIndex: 'created_by_name', width: 100},
    {title: '录入时间', dataIndex: 'created_at', width: 160},
    {
      title: '操作', width: 150, align: 'center',
      render: (text, record) => (
        <span>
          <a onClick={() => store.fetchDetail(record.id)}>详情</a>
          {['draft', 'returned'].includes(record.status) && (
            <AuthButton auth={PERM_L.LED_EDIT}>
              <a style={{marginLeft: 8}} onClick={() => store.showForm(record)}>编辑</a>
            </AuthButton>
          )}
          {record.status === 'draft' && (
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
      ),
    },
  ];

  return (
    <AuthDiv auth={PERM_L.LED_VIEW}>
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
        <Breadcrumb.Item>运行维护</Breadcrumb.Item>
        <Breadcrumb.Item>{LEDGER_TYPE_TEXT[ledgerType]}台账</Breadcrumb.Item>
      </Breadcrumb>
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
        {isWeekMonth && (
          <SearchForm.Item span={6} title="维护周期">
            <Select
              allowClear
              style={{width: '100%'}}
              value={store.f_cycle}
              onChange={v => {
                store.f_cycle = v;
                store.page = 1;
                store.fetchRecords();
              }}
              placeholder="请选择周期">
              <Select.Option value="week">周</Select.Option>
              <Select.Option value="month">月</Select.Option>
            </Select>
          </SearchForm.Item>
        )}
      </SearchForm>
      <div style={{marginBottom: 12}}>
        <AuthButton
          auth={PERM_L.LED_ADD}
          type="primary"
          icon={<PlusOutlined/>}
          onClick={() => store.showForm()}>
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
      {store.formVisible && <ComForm store={store}/>}
      {store.detailVisible && <LedgerDetail store={store}/>}
    </AuthDiv>
  );
}

export default observer(LedgerIndex);

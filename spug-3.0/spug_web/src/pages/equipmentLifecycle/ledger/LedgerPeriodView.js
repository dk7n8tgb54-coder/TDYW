/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账"按维护周期"视图（2026-10-11 自 LedgerIndex 迁出）：
 * 维护类型＋周期分组表（组内为各系统台账及填写状态）＋"生成本期应填台账"
 * 入口（2026-10-14 重构：按 Excel 模板配置生成本周/本月/本航季应填台账）；
 * 筛选为 编号/状态/按系统查看。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Input, Select, Tooltip} from 'antd';
import {AppstoreAddOutlined, PlusOutlined} from '@ant-design/icons';
import {AuthButton, ExportButton, SearchForm} from 'components';
import LedgerPeriodOverviewCard from './LedgerPeriodOverviewCard';
import LedgerGroupTable from './LedgerGroupTable';
import {API_PREFIX_L, LEDGER_TYPE_TEXT, PERM_L, STATUS_FILTER_OPTIONS} from './constants';

// observer：筛选控件直接读取 store.f_keyword / f_status / f_system，输入后需触发重渲染
const PeriodSearchForm = observer(function PeriodSearchForm({store}) {
  const refresh = () => store.refresh();
  return (
    <SearchForm>
      <SearchForm.Item span={6} title="台账编号">
        <Input
          allowClear
          value={store.f_keyword}
          onChange={e => store.f_keyword = e.target.value}
          placeholder="请输入台账编号"
          onPressEnter={refresh}
        />
      </SearchForm.Item>
      <SearchForm.Item span={6} title="状态">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.f_status}
          onChange={v => {
            store.f_status = v;
            refresh();
          }}
          placeholder="默认不含已作废">
          {STATUS_FILTER_OPTIONS.map(opt => (
            <Select.Option value={opt.value} key={opt.value}>{opt.label}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={6} title="按系统查看">
        <Select
          allowClear
          showSearch
          optionFilterProp="children"
          style={{width: '100%'}}
          value={store.f_system}
          onChange={v => {
            store.f_system = v;
            refresh();
          }}
          placeholder="查看某个系统下的台账">
          {store.systemOptions.map(s => (
            <Select.Option value={s.id} key={s.id}>
              {`${s.name}（${s.system_code}）${s.is_active ? '' : ' [已停用]'}`}
            </Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
    </SearchForm>
  );
});

function LedgerPeriodView({store, ledgerType, columns, onGenerate, onExcelCreate}) {
  return (
    <React.Fragment>
      <LedgerPeriodOverviewCard store={store}/>
      <PeriodSearchForm store={store}/>
      <div style={{marginBottom: 12}}>
        <AuthButton
          auth={PERM_L.LED_ADD}
          type="primary"
          icon={<AppstoreAddOutlined/>}
          data-testid="period-generate"
          onClick={onGenerate}>
          生成本期应填台账
        </AuthButton>
        <AuthButton
          auth={PERM_L.LED_ADD}
          style={{marginLeft: 8}}
          icon={<PlusOutlined/>}
          onClick={onExcelCreate}>
          新增{LEDGER_TYPE_TEXT[ledgerType]}台账
        </AuthButton>
        <Tooltip title="导出台账明细数据（手工补录台账的检查项目明细行，携带当前筛选）；Excel 模板台账请在台账详情中导出填写完整的 Excel/PDF。">
          <ExportButton
            auth={PERM_L.LED_EXPORT}
            style={{marginLeft: 8}}
            url={`${API_PREFIX_L}/ledgers/export/`}
            params={store.periodExportParams()}
            filename={`${LEDGER_TYPE_TEXT[ledgerType]}台账明细.csv`}>
            导出明细 CSV
          </ExportButton>
        </Tooltip>
      </div>
      <LedgerGroupTable store={store} columns={columns}/>
    </React.Fragment>
  );
}

export default observer(LedgerPeriodView);

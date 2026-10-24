/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账"按维护周期"视图（2026-10-11 自 LedgerIndex 迁出）：
 * 维护类型＋周期分组表（2026-10-20 单表头：分组行贯通 + 组内直接铺台账
 * 记录行）＋"生成本期应填台账"入口（2026-10-14 重构：按 Excel 模板配置
 * 生成本周/本月/本航季应填台账）；筛选为 编号/状态/按系统查看。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Input, Select} from 'antd';
import {AppstoreAddOutlined, FilePdfOutlined, PlusOutlined} from '@ant-design/icons';
import {AuthButton, SearchForm} from 'components';
import LedgerPeriodOverviewCard from './LedgerPeriodOverviewCard';
import LedgerGroupTable from './LedgerGroupTable';
import {LEDGER_TYPE_TEXT, PERM_L, STATUS_FILTER_OPTIONS} from './constants';

// observer：筛选控件直接读取 store.f_keyword / f_status / f_system，输入后需触发重渲染
const PeriodSearchForm = observer(function PeriodSearchForm({store}) {
  const refresh = () => store.refresh();
  return (
    // SearchForm 会把 style 同时作用于外层容器与内层 Form（components/SearchForm.js），
    // paddingTop 4 经两次叠加即 8px 视觉内边距；marginBottom 8 替代类默认 16，
    // 使 概览卡/筛选区/操作区 形成连续工作区（2026-10-20 视觉密度压缩）
    <SearchForm style={{paddingTop: 4, marginBottom: 8}}>
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

function LedgerPeriodView({store, ledgerType, columns, onGenerate, onExcelCreate, onFormCreate, onMultiExport}) {
  return (
    <React.Fragment>
      <LedgerPeriodOverviewCard store={store}/>
      <PeriodSearchForm store={store}/>
      {/* 操作区（2026-10-20 整理）：主操作仅"生成本期应填台账"（primary），
          新增/导出为默认按钮低视觉权重；统一 8px 间距，窄屏自动换行 */}
      <div style={{marginBottom: 8, display: 'flex', flexWrap: 'wrap', gap: 8}}>
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
          icon={<PlusOutlined/>}
          onClick={onExcelCreate}>
          新增{LEDGER_TYPE_TEXT[ledgerType]}台账
        </AuthButton>
        {/* 数字表单路线（2026-10-21）：按数字表单模板创建，与 Excel 路线并行 */}
        <AuthButton
          auth={PERM_L.LED_ADD}
          icon={<PlusOutlined/>}
          data-testid="form-create-open"
          onClick={onFormCreate}>
          新增数字表单台账
        </AuthButton>
        {/* 批量导出 PDF（2026-10-21）：替换原"导出明细 CSV"入口，按模板多选导出 */}
        <AuthButton
          auth={PERM_L.LED_EXPORT}
          icon={<FilePdfOutlined/>}
          data-testid="multi-export-open"
          onClick={onMultiExport}>
          批量导出 PDF
        </AuthButton>
      </div>
      <LedgerGroupTable store={store} columns={columns}/>
    </React.Fragment>
  );
}

export default observer(LedgerPeriodView);

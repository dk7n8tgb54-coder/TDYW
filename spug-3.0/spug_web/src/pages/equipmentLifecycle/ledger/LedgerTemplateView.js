/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账"按模板查看"视图（2026-10-11）：
 * 先展示模板身份分组统计（LedgerTemplateGroupTable），点击进入组内台账
 * 分页列表（返回按钮 + 统一列表列 + 模板版本列）。筛选为 编号/状态/执行
 * 日期范围（Excel 台账无表头系统关联，不提供系统筛选）；组内台账行复用
 * 统一列表的操作与详情路由（Excel 来源走 ExcelLedgerDetail 版本快照回放）；
 * 新增/导出为全局动作保留；"生成本期应填台账"入口在两个视图模式均可用
 * （2026-10-14）。模板组内提供"导出本模板台账"：先弹确认框
 * （LedgerBatchExportModal）展示匹配数/日期范围/状态范围/涉及版本，确认后
 * 按同口径批量生成合并 PDF（manual 组无模板版式不提供该入口）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Button, Input, Select, Table, DatePicker} from 'antd';
import {
  AppstoreAddOutlined, ArrowLeftOutlined, FilePdfOutlined, PlusOutlined,
} from '@ant-design/icons';
import {AuthButton, ExportButton, SearchForm} from 'components';
import LedgerTemplateGroupTable from './LedgerTemplateGroupTable';
import LedgerBatchExportModal from './LedgerBatchExportModal';
import {buildColumns} from './LedgerColumns';
import {API_PREFIX_L, LEDGER_TYPE_TEXT, PERM_L, STATUS_TEXT} from './constants';

// observer：筛选控件直接读取 store 可观察字段，输入后需触发重渲染。
// 模板视图使用独立筛选字段（t_keyword/t_status/t_date_range），与周期视图
// （f_keyword/f_status/f_system）互不混淆。
const TemplateSearchForm = observer(function TemplateSearchForm({store}) {
  const refresh = () => store.refresh();
  return (
    <SearchForm>
      <SearchForm.Item span={6} title="台账编号">
        <Input
          allowClear
          value={store.t_keyword}
          onChange={e => store.t_keyword = e.target.value}
          placeholder="请输入台账编号"
          onPressEnter={refresh}
        />
      </SearchForm.Item>
      <SearchForm.Item span={6} title="状态">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.t_status}
          onChange={v => {
            store.t_status = v;
            refresh();
          }}
          placeholder="请选择状态">
          {Object.keys(STATUS_TEXT).map(key => (
            <Select.Option value={key} key={key}>{STATUS_TEXT[key]}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={8} title="实际执行日期">
        <DatePicker.RangePicker
          style={{width: '100%'}}
          value={store.t_date_range}
          onChange={v => {
            store.t_date_range = v;
            store.templateGroupsPage = 1;
            store.groupLedgersPage = 1;
            refresh();
          }}
          placeholder={['执行日期起', '执行日期止']}
        />
      </SearchForm.Item>
    </SearchForm>
  );
});

function LedgerTemplateView({store, ledgerType, openDetail, onGenerate, onOpenExcelCreate}) {
  const inGroup = !!store.activeGroup;
  const columns = buildColumns(store, ledgerType, openDetail, inGroup);
  return (
    <React.Fragment>
      <TemplateSearchForm store={store}/>
      <div style={{marginBottom: 12}}>
        {inGroup && (
          <Button
            icon={<ArrowLeftOutlined/>}
            style={{marginRight: 8}}
            onClick={store.backToGroups}>
            返回模板组
          </Button>
        )}
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
          style={{marginLeft: 8}}
          onClick={onOpenExcelCreate}>
          新增{LEDGER_TYPE_TEXT[ledgerType]}台账
        </AuthButton>
        {inGroup && store.activeGroup.group_key !== 'manual' && (
          <AuthButton
            auth={PERM_L.LED_EXPORT}
            icon={<FilePdfOutlined/>}
            style={{marginLeft: 8}}
            loading={store.isBatchExportFetching}
            disabled={store.groupLedgersTotal === 0}
            onClick={store.openBatchExport}>
            导出本模板台账
          </AuthButton>
        )}
        {!inGroup && (
          <ExportButton
            auth={PERM_L.LED_EXPORT}
            style={{marginLeft: 8}}
            url={`${API_PREFIX_L}/ledgers/export/?ledger_type=${ledgerType}`}
            filename={`${LEDGER_TYPE_TEXT[ledgerType]}台账.csv`}>
            导出
          </ExportButton>
        )}
      </div>
      {inGroup ? (
        <Table
          rowKey="id"
          loading={store.isGroupLedgersFetching}
          dataSource={store.groupLedgers}
          columns={columns}
          pagination={{
            total: store.groupLedgersTotal,
            current: store.groupLedgersPage,
            pageSize: store.groupLedgersPageSize,
            showSizeChanger: false,
            showTotal: t => `共 ${t} 条台账`,
            onChange: page => {
              store.groupLedgersPage = page;
              store.fetchGroupLedgers();
            },
          }}
        />
      ) : (
        <LedgerTemplateGroupTable store={store}/>
      )}
      <LedgerBatchExportModal store={store}/>
    </React.Fragment>
  );
}

export default observer(LedgerTemplateView);

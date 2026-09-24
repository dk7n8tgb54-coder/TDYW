/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——巡检单记录查询（今日巡检改造）。
 * 浏览全部值班巡检单（按值班日范围/状态/编号筛选），详情只读展示
 * 值班人员与四轮检查内容回显；异常明细的转故障/工单处置状态在此可见，
 * 转单操作仍在"今日巡检"工作台进行（巡检单不关联系统）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Button, DatePicker, Descriptions, Drawer, Input, Select, Spin, Tag} from 'antd';
import {AuthButton, AuthDiv, Breadcrumb, ExportButton, SearchForm} from 'components';
import store from './store';
import {API_PREFIX, PERM_I, ROUND_TEXT, SHEET_STATUS_COLOR, SHEET_STATUS_TEXT} from './constants';
import {withProjectSpans} from './tableUtils';

const DISPOSITION_TEXT = {
  none: '未处置',
  converted_fault: '已转故障',
  converted_work_order: '已转工单',
  target_cancelled: '目标已作废',
};

function buildBrowseParams() {
  const params = {
    page: store.browsePage,
    page_size: store.browsePageSize,
  };
  if (store.f_duty_range && store.f_duty_range.length === 2) {
    params.duty_from = store.f_duty_range[0].format('YYYY-MM-DD');
    params.duty_to = store.f_duty_range[1].format('YYYY-MM-DD');
  }
  if (store.f_status) params.status = store.f_status;
  if (store.f_keyword) params.keyword = store.f_keyword;
  return params;
}

// 导出参数 = 当前筛选条件（不含分页参数，后端导出筛选范围内全部数据）
function buildExportParams() {
  const {page, page_size, ...filters} = buildBrowseParams();
  return filters;
}

@observer
class SheetTable extends React.Component {
  componentDidMount() {
    store.fetchBrowse(buildBrowseParams());
  }

  render() {
    return (
      <table className="el-ins-recap-table" style={{width: '100%'}}>
        <thead>
        <tr>
          <th style={{width: 110}}>值班日</th>
          <th style={{width: 160}}>单号</th>
          <th style={{width: 160}}>模板</th>
          <th style={{width: 90}}>状态</th>
          <th style={{width: 80}}>异常数</th>
          <th style={{width: 150}}>提交时间</th>
          <th style={{width: 100}}>提交人</th>
          <th style={{width: 80}}>操作</th>
        </tr>
        </thead>
        <tbody>
        {store.browseRecords.map(record => (
          <tr key={record.id}>
            <td>{record.duty_date}</td>
            <td>{record.sheet_no}</td>
            <td>{record.template_name}</td>
            <td>
              <Tag color={SHEET_STATUS_COLOR[record.status]}>
                {SHEET_STATUS_TEXT[record.status] || record.status}
              </Tag>
            </td>
            <td>
              {record.abnormal_count > 0
                ? <span style={{color: 'red', fontWeight: 'bold'}}>{record.abnormal_count}</span>
                : record.abnormal_count}
            </td>
            <td>{record.submitted_at || '-'}</td>
            <td>{record.submitted_by_name || '-'}</td>
            <td>
              <AuthButton
                auth={PERM_I.VIEW}
                type="link"
                size="small"
                style={{padding: 0}}
                onClick={() => store.openBrowseDetail(record.id)}
              >
                详情
              </AuthButton>
            </td>
          </tr>
        ))}
        {!store.browseRecords.length && !store.isBrowseFetching && (
          <tr>
            <td colSpan={8} style={{color: '#999', textAlign: 'center', padding: 16}}>
              暂无巡检单记录
            </td>
          </tr>
        )}
        </tbody>
      </table>
    );
  }
}

const SheetDetailDrawer = observer(function SheetDetailDrawer() {
  const d = store.detail;
  const rounds = ['r1', 'r2', 'r3', 'r4'];
  // 一行 = 检查项目（设备名称快照）× 检查内容，四轮取值横向展开；
  // 临时加项的设备名可能为空，检查项目归为"临时检查项"
  const itemMap = {};
  (d ? d.records : []).forEach(r => {
    const key = r.template_item ? `t_${r.template_item}` : `m_${r.client_key || r.id}`;
    const item = itemMap[key] || (itemMap[key] = {
      key,
      project: r.device_name || '临时检查项',
      content: r.item_name,
      displayOrder: r.display_order || 0,
      rounds: {},
    });
    item.rounds[r.round_no] = r;
  });
  const items = Object.values(itemMap).sort((a, b) => {
    if (a.project !== b.project) return a.project < b.project ? -1 : 1;
    if (a.displayOrder !== b.displayOrder) return a.displayOrder - b.displayOrder;
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
  });
  // 同一检查项目的连续行合并第一列单元格
  const rows = withProjectSpans(items);
  function cell(record) {
    if (!record) return <span style={{color: '#ddd'}}>—</span>;
    const color = record.result === 'abnormal' ? 'red' : 'inherit';
    const disp = record.disposition && record.disposition.status !== 'none'
      ? <Tag style={{marginLeft: 4}}>{DISPOSITION_TEXT[record.disposition.status]}</Tag>
      : null;
    return (
      <span>
        <span style={{color}}>
          {record.value_text || '—'}
          {record.onsite_action ? `（${record.onsite_action}）` : ''}
        </span>
        {disp}
      </span>
    );
  }
  return (
    <Drawer
      title={d ? `巡检单详情 - ${d.sheet_no}` : '巡检单详情'}
      visible={store.browseVisible}
      width={960}
      onClose={() => store.closeBrowseDetail()}
      destroyOnClose
      extra={d ? (
        <div>
          <ExportButton
            auth={PERM_I.EXPORT}
            url={`${API_PREFIX}/inspection-sheets/${d.id}/export/xlsx/`}
            filename={`巡检单_${d.sheet_no}.xlsx`}>
            导出 Excel
          </ExportButton>
          <ExportButton
            auth={PERM_I.EXPORT}
            style={{marginLeft: 8}}
            url={`${API_PREFIX}/inspection-sheets/${d.id}/export/pdf/`}
            filename={`巡检单_${d.sheet_no}.pdf`}>
            导出 PDF
          </ExportButton>
        </div>
      ) : null}
    >
      <Spin spinning={store.isDetailFetching}>
        {d && (
          <div>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="单号">{d.sheet_no}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={SHEET_STATUS_COLOR[d.status]}>{SHEET_STATUS_TEXT[d.status]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="值班日">{d.duty_date}</Descriptions.Item>
              <Descriptions.Item label="巡检模板">{d.template_name}</Descriptions.Item>
              <Descriptions.Item label="值班人员" span={2}>
                {d.persons && d.persons.length
                  ? d.persons.map(p => p.person_name).join('、') : '（未登记）'}
              </Descriptions.Item>
              <Descriptions.Item label="提交时间">
                {d.submitted_at || '-'}
                {d.submitted_by_name ? `（${d.submitted_by_name}）` : ''}
              </Descriptions.Item>
              <Descriptions.Item label="异常数">{d.abnormal_count}</Descriptions.Item>
              {d.status === 'void' && (
                <Descriptions.Item label="作废原因" span={2}>
                  {d.void_reason || '-'}
                  {d.voided_at ? `（${d.voided_at} ${d.voided_by_name || ''}）` : ''}
                </Descriptions.Item>
              )}
            </Descriptions>
            <div style={{marginTop: 12}}>
              <table className="el-ins-recap-table" style={{width: '100%'}}>
                <thead>
                <tr>
                  <th>检查项目</th>
                  <th>检查内容</th>
                  {rounds.map(r => <th key={r}>{ROUND_TEXT[r]}</th>)}
                </tr>
                </thead>
                <tbody>
                {rows.map(({item, isGroupStart, span}) => (
                  <tr key={item.key}>
                    {isGroupStart ? <td rowSpan={span}>{item.project}</td> : null}
                    <td>{item.content}</td>
                    {rounds.map(r => (
                      <td key={r}>{cell(item.rounds[r])}</td>
                    ))}
                  </tr>
                ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Spin>
    </Drawer>
  );
});

@observer
class SheetIndex extends React.Component {
  componentDidMount() {
    // 来源跳转直达详情（故障详情/工单详情/系统履历跳入：?detail=<巡检单ID>）
    const params = new URLSearchParams(this.props.location ? this.props.location.search : '');
    const detailId = params.get('detail');
    if (detailId && /^\d+$/.test(detailId)) {
      store.openBrowseDetail(parseInt(detailId, 10));
    }
  }

  render() {
    return (
      <AuthDiv>
        <Breadcrumb>
          <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
          <Breadcrumb.Item>运行维护</Breadcrumb.Item>
          <Breadcrumb.Item>巡检单记录</Breadcrumb.Item>
        </Breadcrumb>
        <SearchForm>
          <SearchForm.Item>
            <DatePicker.RangePicker
              value={store.f_duty_range}
              onChange={v => {store.f_duty_range = v || [];}}
              format="YYYY-MM-DD"
              placeholder={['值班日起', '值班日止']}
            />
          </SearchForm.Item>
          <SearchForm.Item>
            <Select
              allowClear
              style={{width: 140}}
              placeholder="状态"
              value={store.f_status}
              onChange={v => {store.f_status = v;}}
            >
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="submitted">已提交</Select.Option>
              <Select.Option value="void">已作废</Select.Option>
            </Select>
          </SearchForm.Item>
          <SearchForm.Item>
            <Input
              allowClear
              placeholder="单号关键字"
              value={store.f_keyword}
              onChange={e => {store.f_keyword = e.target.value;}}
              onKeyPress={e => {
                if (e.key === 'Enter') {
                  store.browsePage = 1;
                  store.fetchBrowse(buildBrowseParams());
                }
              }}
            />
          </SearchForm.Item>
        </SearchForm>
        <div style={{marginBottom: 12}}>
          <Button
            type="primary"
            onClick={() => {
              store.browsePage = 1;
              store.fetchBrowse(buildBrowseParams());
            }}
          >
            查询
          </Button>
          <ExportButton
            auth={PERM_I.EXPORT}
            style={{marginLeft: 8}}
            url={`${API_PREFIX}/inspection-sheets/export/`}
            params={buildExportParams()}
            filename="巡检单记录.xlsx">
            导出 Excel
          </ExportButton>
          <ExportButton
            auth={PERM_I.EXPORT}
            style={{marginLeft: 8}}
            disabled={store.browseTotal === 0}
            url={`${API_PREFIX}/inspection-sheets/batch-export/xlsx/`}
            params={buildExportParams()}
            filename="巡检单详情批量.xlsx">
            {`批量导出 Excel（共 ${store.browseTotal} 条）`}
          </ExportButton>
          <ExportButton
            auth={PERM_I.EXPORT}
            style={{marginLeft: 8}}
            disabled={store.browseTotal === 0}
            url={`${API_PREFIX}/inspection-sheets/batch-export/pdf/`}
            params={buildExportParams()}
            filename="巡检单详情批量.pdf">
            {`批量导出 PDF（共 ${store.browseTotal} 条）`}
          </ExportButton>
        </div>
        <SheetTable/>
        <div style={{marginTop: 12, color: '#999'}}>
          共 {store.browseTotal} 条（第 {store.browsePage} 页）
        </div>
        <SheetDetailDrawer/>
      </AuthDiv>
    );
  }
}

export default SheetIndex;

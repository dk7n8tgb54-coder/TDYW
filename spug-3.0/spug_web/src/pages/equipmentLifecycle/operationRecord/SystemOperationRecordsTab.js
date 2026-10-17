/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统档案详情——"运行处置记录"页签（当前系统的运行处置记录视图）。
 * 数据按系统直接查询统一主表（systems/<pk>/records/，不重建履历事件表），
 * 默认排除已撤销记录（显式筛选状态时返回）。
 * 2026-10-15 体验三轮——与左侧主菜单主列表同一阅读/操作方式：
 * - 列：标题为主要入口（前置类型标签，点击打开统一详情，长标题截断悬浮
 *   看全文）；编号一键复制；故障影响并入状态列；发生时间/最近更新；
 *   进展数可点击直达详情进展页签；不再保留重复的"详情"操作列。
 *   展示单元与主列表共用 shared.js 实现（不复制展示规则）。
 * - 筛选与主列表同构：关键词/状态常驻，记录类型/异常类别/发生时间收入
 *   "更多筛选"（折叠时提示仍生效的条件数）；系统由档案固定不设选择器；
 *   查询/重置/翻页/失败重试同一组筛选条件（条件收进 store）。关键词输入为
 *   草稿（sf_input_keyword），查询按钮/回车提交后才成为已执行条件
 *   （sf_keyword）；状态等筛选变更即刷新但不代提交未执行草稿，详情动作后
 *   的联动刷新同样只用已执行条件（2026-10-15 与主列表同口径）。
 * - "查看该系统全部记录"跳入主列表并自动带上系统筛选（/el/records?system=）。
 * - 详情内新增/编辑/删除/状态动作成功后由 store 以同一组条件联动刷新
 *   本页签（refreshSystemRecordsIfActive），不显示过期行。
 * - 空态区分"当前系统暂无记录"与"筛选后没有匹配记录"；加载失败显式
 *   提示并可重试，不把旧结果冒充新查询结果。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Table, Input, Select, DatePicker, Button, Alert} from 'antd';
import {DownOutlined, UpOutlined} from '@ant-design/icons';
import {SearchForm, AuthDiv} from 'components';
import {history} from 'libs';
import store, {SYSTEM_RECORDS_PAGE_SIZE} from './store';
import RecordDetail from './RecordDetail';
import {RecordStatusTag, FaultImpactTag, RecordTitleCell, RecordNoCell} from './shared';
import {
  PERM, RECORD_STATUS_OPTIONS,
  RECORD_CATEGORY_OPTIONS, RECORD_TYPE_OPTIONS,
} from '../constants';

const {RangePicker} = DatePicker;

// 表格空态文案（2026-10-15）：区分"加载失败"与"当前系统暂无记录"与
// "筛选后没有匹配记录"。抽为纯函数便于契约测试（jsdom 下 rc-table 因
// componentWidth=0 隐藏空态内容，文案分支只能以函数级验证）
export function systemTabEmptyMessage(hasError, hasFilter) {
  if (hasError) return '记录列表加载失败';
  return hasFilter ? '没有符合条件的记录' : '当前系统暂无记录';
}

@observer
class SystemOperationRecordsTab extends React.Component {
  componentDidMount() {
    // 换系统进入即重置筛选与页码（store 内部处理），首屏即当前系统第 1 页
    store.fetchSystemRecords(this.props.systemId, 1);
  }

  componentWillUnmount() {
    // 关闭系统详情/离开系统档案页：清空页签数据与在位标记（此后详情动作
    // 不再联动刷新），并收起可能打开的统一详情窗口（共享单例 store）
    store.clearSystemRecords();
    if (store.detailVisible) store.closeDetail();
  }

  // 列（2026-10-15）与主列表同一呈现：标题入口前置类型标签；编号可复制；
  // 故障影响并入状态列；进展数直达详情进展页签；去掉重复的"详情"操作列
  // （点击标题即打开统一详情）。宽度按 1100px 系统详情弹窗内可用宽度
  // 设计（合计约 890，不照搬主列表列宽）
  columns = [{
    title: '标题',
    dataIndex: 'title',
    width: 240,
    ellipsis: true,
    render: (text, record) => (
      <RecordTitleCell record={record} onOpen={r => store.showDetail(r)}/>
    ),
  }, {
    title: '编号',
    dataIndex: 'record_no',
    width: 170,
    render: (text) => <RecordNoCell value={text}/>,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 130,
    render: (text, record) => (
      <span>
        <RecordStatusTag status={text}/>
        <FaultImpactTag record={record}/>
      </span>
    ),
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    // 最近更新：全部进展中处理时间最新的进展时间（后端按处理时间聚合最大值，
    // 非进展创建时间/ID 口径，不取主记录 updated_at）；无进展显示"-"
    title: '最近更新',
    dataIndex: 'latest_progress_at',
    width: 150,
    render: (text) => text || '-',
  }, {
    // 统一进展数：后端列表聚合统计（progress_count，只读）；
    // 点击数量打开详情并定位到"进展"页签
    title: '进展数',
    dataIndex: 'progress_count',
    width: 80,
    render: (text, record) => (
      <a onClick={() => store.showDetail(record, 'progress')}>
        {record.progress_count ?? 0} 条
      </a>
    ),
  }];

  render() {
    const systemId = this.props.systemId;
    return (
      <AuthDiv auth={PERM.OP_VIEW}>
        {/* 摘要与跳转入口：左侧系统维度摘要，右侧跳入主列表（自动带系统筛选） */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          flexWrap: 'wrap', marginBottom: 10,
        }}>
          <span style={{color: 'rgba(0, 0, 0, 0.45)', fontSize: 12}}>
            {store.systemLatestOccurredAt ? `最近发生时间：${store.systemLatestOccurredAt}` : ''}
          </span>
          <a onClick={() => history.push(`/el/records?system=${systemId}`)}>
            查看该系统全部记录
          </a>
        </div>
        <SystemRecordFilters systemId={systemId}/>
        {/* 加载失败显式提示并保留旧数据供参考，重试沿用同一组筛选与页码
            （错误 toast 已由 http 拦截器弹出，此处不重复弹出） */}
        {store.systemRecordsError && (
          <Alert
            type="warning"
            showIcon
            message="记录列表加载失败，以下可能为上次查询结果"
            action={
              <Button size="small" onClick={() => store.fetchSystemRecords()}>重试</Button>
            }
            style={{marginBottom: 12}}
          />
        )}
        <Table
          rowKey="id"
          size="small"
          loading={store.isSystemRecordsFetching}
          scroll={{x: 890}}
          pagination={{
            current: store.systemRecordsPage,
            pageSize: SYSTEM_RECORDS_PAGE_SIZE,
            total: store.systemRecordsTotal,
            onChange: (page) => store.fetchSystemRecords(systemId, page),
            showTotal: total => `共 ${total} 条`,
          }}
          dataSource={store.systemRecords}
          columns={this.columns}
          locale={{emptyText: (
            <div style={{padding: '24px 0'}}>
              <div>
                {systemTabEmptyMessage(
                  store.systemRecordsError, store.systemHasActiveFilter)}
              </div>
              {!store.systemRecordsError && !store.systemHasActiveFilter && (
                <div style={{color: 'rgba(0, 0, 0, 0.45)', fontSize: 12, marginTop: 4}}>
                  在主菜单"运行处置记录"或维护台账中登记本系统的记录后展示在此
                </div>
              )}
            </div>
          )}}
        />
        {/* 统一详情窗口（共享单例 store；关闭系统详情时由上方收起） */}
        {store.detailVisible && <RecordDetail/>}
      </AuthDiv>
    );
  }
}

// 筛选区（与主列表同构，系统由档案固定不设选择器）：关键词/状态常驻，
// 记录类型/异常类别/发生时间收入"更多筛选"（折叠时显示活跃条件数）。
// 任一筛选变更即重置页码并刷新，查询/重置/翻页/失败重试同一组条件
const SystemRecordFilters = observer(function SystemRecordFilters({systemId}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // 查询（按钮/回车）：提交关键词草稿并回第 1 页；其余筛选变更即刷新但
  // 不代提交未执行的草稿（输入中的条件与已执行条件分离，与主列表同口径）
  const query = () => store.querySystemRecords(systemId);
  const refresh = () => store.fetchSystemRecords(systemId, 1);
  const advancedCount = [
    store.sf_record_type,
    store.sf_category,
    store.sf_occurred_range && store.sf_occurred_range.length === 2,
  ].filter(Boolean).length;
  return (
    <SearchForm>
      <SearchForm.Item span={9} title="关键词">
        {/* 输入只写草稿（不触发查询）：查询按钮/回车提交后才成为已执行条件 */}
        <Input
          allowClear
          value={store.sf_input_keyword}
          onChange={e => store.setSystemKeywordInput(e.target.value)}
          placeholder="编号/标题/描述"
          onPressEnter={query}
        />
      </SearchForm.Item>
      <SearchForm.Item span={7} title="状态">
        <Select
          allowClear
          style={{width: '100%'}}
          value={store.sf_status}
          onChange={v => {store.sf_status = v; refresh();}}
          placeholder="默认不含已撤销"
        >
          {RECORD_STATUS_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </SearchForm.Item>
      <SearchForm.Item span={8}>
        <Button type="primary" onClick={query}>查询</Button>
        <Button
          style={{marginLeft: 8}}
          onClick={() => {store.resetSystemFilter(); query();}}
        >
          重置
        </Button>
        <a
          style={{marginLeft: 16, lineHeight: '32px', userSelect: 'none'}}
          onClick={() => setAdvancedOpen(!advancedOpen)}
        >
          {advancedOpen ? '收起筛选' : '更多筛选'}
          {!advancedOpen && advancedCount > 0 && `（${advancedCount}）`}
          {advancedOpen ? <UpOutlined style={{marginLeft: 4}}/> : <DownOutlined style={{marginLeft: 4}}/>}
        </a>
      </SearchForm.Item>
      {advancedOpen && (
        <React.Fragment>
          <SearchForm.Item span={6} title="记录类型">
            <Select
              allowClear
              style={{width: '100%'}}
              value={store.sf_record_type}
              onChange={v => {store.sf_record_type = v; refresh();}}
              placeholder="请选择"
            >
              {RECORD_TYPE_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
              ))}
            </Select>
          </SearchForm.Item>
          <SearchForm.Item span={6} title="异常类别">
            <Select
              allowClear
              style={{width: '100%'}}
              value={store.sf_category}
              onChange={v => {store.sf_category = v; refresh();}}
              placeholder="请选择"
            >
              {RECORD_CATEGORY_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>
                  {item.label}
                </Select.Option>
              ))}
            </Select>
          </SearchForm.Item>
          <SearchForm.Item span={12} title="发生时间">
            <RangePicker
              showTime={{format: 'HH:mm'}}
              format="YYYY-MM-DD HH:mm"
              style={{width: '100%'}}
              value={store.sf_occurred_range}
              onChange={v => {store.sf_occurred_range = v; refresh();}}
              placeholder={['发生时间起', '发生时间止']}
            />
          </SearchForm.Item>
        </React.Fragment>
      )}
    </SearchForm>
  );
});

export default SystemOperationRecordsTab;

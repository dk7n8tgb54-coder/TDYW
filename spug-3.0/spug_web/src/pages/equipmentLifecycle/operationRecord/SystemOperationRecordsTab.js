/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统档案详情——"运行与故障记录"页签（2026-10-11 合并改造）。
 * 按系统直接查询统一主表（systems/<pk>/records/，不重建履历事件表），
 * 支持按 记录类型（日常运行/异常事件/正式故障）/状态/关键词/时间范围 筛选；
 * 默认排除已撤销记录（显式筛选时返回）。点击"详情"打开统一详情窗口。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Table, Tag, Empty, Input, Select, DatePicker, Button} from 'antd';
import {AuthDiv} from 'components';
import store from '../operationRecord/store';
import RecordDetail from '../operationRecord/RecordDetail';
import {
  PERM, RECORD_STATUS_TEXT, RECORD_STATUS_COLOR,
  RECORD_CATEGORY_OPTIONS, RECORD_CATEGORY_TEXT,
  RECORD_TYPE_OPTIONS, RECORD_TYPE_TEXT, RECORD_TYPE_COLOR,
} from '../constants';

const {RangePicker} = DatePicker;

function StatusTag({status}) {
  if (status === 'cancelled') {
    return (
      <Tag
        color="default"
        style={{borderStyle: 'dashed', color: 'rgba(0, 0, 0, 0.45)'}}
      >
        {RECORD_STATUS_TEXT[status] || status}
      </Tag>
    );
  }
  return <Tag color={RECORD_STATUS_COLOR[status]}>{RECORD_STATUS_TEXT[status] || status}</Tag>;
}

@observer
class SystemOperationRecordsTab extends React.Component {
  state = {
    keyword: undefined, status: undefined, category: undefined,
    recordType: undefined, occurredRange: null,
  };

  componentDidMount() {
    store.fetchSystemRecords(this.props.systemId);
  }

  componentWillUnmount() {
    // 关闭系统详情时收起可能打开的统一详情窗口（共享单例 store）
    if (store.detailVisible) store.closeDetail();
  }

  fetchWithFilters = (overrides) => {
    const filters = {...this.state, ...overrides};
    const params = {};
    if (filters.keyword) params.keyword = filters.keyword;
    if (filters.status) params.status = filters.status;
    if (filters.category) params.category = filters.category;
    if (filters.recordType) params.record_type = filters.recordType;
    if (filters.occurredRange && filters.occurredRange.length === 2) {
      params.occurred_from = filters.occurredRange[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = filters.occurredRange[1].format('YYYY-MM-DD HH:mm');
    }
    store.fetchSystemRecords(this.props.systemId, params);
  };

  columns = [{
    title: '编号',
    dataIndex: 'record_no',
    width: 140,
  }, {
    title: '记录类型',
    dataIndex: 'record_type',
    width: 90,
    render: text => (
      <Tag color={RECORD_TYPE_COLOR[text]}>{RECORD_TYPE_TEXT[text] || text}</Tag>
    ),
  }, {
    title: '标题',
    dataIndex: 'title',
    width: 200,
    ellipsis: true,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <StatusTag status={text}/>,
  }, {
    title: '异常类别',
    dataIndex: 'category_text',
    width: 90,
    render: text => text || '-',
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    title: '操作',
    width: 70,
    render: (text, record) => (
      <a
        onClick={() => {
          // 列表行数据可能滞后：按 ID 拉取真实详情
          store.showDetail(record.id);
        }}
      >详情</a>
    ),
  }];

  render() {
    return (
      <AuthDiv auth={PERM.OP_VIEW}>
        <div style={{marginBottom: 10}}>
          <Input.Search
            allowClear
            style={{width: 200, marginRight: 8}}
            placeholder="编号/标题"
            value={this.state.keyword}
            onChange={e => this.setState({keyword: e.target.value})}
            onSearch={() => this.fetchWithFilters()}
          />
          <Select
            allowClear
            placeholder="记录类型"
            style={{width: 120, marginRight: 8}}
            value={this.state.recordType}
            onChange={v => {
              this.setState({recordType: v}, () => this.fetchWithFilters({recordType: v}));
            }}
          >
            {RECORD_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="状态"
            style={{width: 110, marginRight: 8}}
            value={this.state.status}
            onChange={v => {
              this.setState({status: v}, () => this.fetchWithFilters({status: v}));
            }}
          >
            {RECORD_STATUS_TEXT && Object.entries(RECORD_STATUS_TEXT).map(([value, label]) => (
              <Select.Option value={value} key={value}>{label}</Select.Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="异常类别"
            style={{width: 130, marginRight: 8}}
            value={this.state.category}
            onChange={v => {
              this.setState({category: v}, () => this.fetchWithFilters({category: v}));
            }}
          >
            {RECORD_CATEGORY_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>
                {item.label}
              </Select.Option>
            ))}
          </Select>
          <RangePicker
            showTime={{format: 'HH:mm'}}
            format="YYYY-MM-DD HH:mm"
            style={{width: 320, marginRight: 8}}
            value={this.state.occurredRange}
            onChange={v => this.setState({occurredRange: v})}
            placeholder={['发生时间起', '发生时间止']}
          />
          <Button onClick={() => this.fetchWithFilters()}>查询</Button>
        </div>
        {store.systemLatestOccurredAt && (
          <div style={{marginBottom: 8, color: '#999'}}>
            最近发生时间：{store.systemLatestOccurredAt}
          </div>
        )}
        <Table
          rowKey="id"
          size="small"
          loading={store.isSystemRecordsFetching}
          pagination={{pageSize: 10, showTotal: total => `共 ${total} 条`}}
          dataSource={store.systemRecords}
          columns={this.columns}
          locale={{emptyText: <Empty description="当前系统暂无记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
        {/* 统一详情窗口（共享单例 store；关闭系统详情时由上方收起） */}
        {store.detailVisible && <RecordDetail/>}
      </AuthDiv>
    );
  }
}

export default SystemOperationRecordsTab;

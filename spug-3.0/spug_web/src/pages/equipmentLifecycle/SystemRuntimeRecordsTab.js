/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——运行异常记录页签（2026-10 第一版 + 第二版）。
 * 只展示所属系统为当前系统的运行异常记录；不含故障/台账/升级/履历。
 * 第二版：支持按 标题/编号关键词、异常类别、发生时间范围 筛选历史记录，
 * 并展示该系统最近一次运行情况发生时间。
 * 重复问题功能已于 2026-10-05 下线：原"关联"数量列与"重复"标记已随
 * 重复功能退役移除（2026-10-06，后端模型与字段同迁移 0008 删除）。
 * 系统影响程度列与重要标记已随字段删除移除（2026-10-06）。
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Empty, Input, Select, DatePicker, Button } from 'antd';
import { AuthDiv } from 'components';
import runtimeStore from './runtimeRecord/store';
import {
  PERM, RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR,
  RUNTIME_CATEGORY_OPTIONS,
} from './constants';

const {RangePicker} = DatePicker;

@observer
class SystemRuntimeRecordsTab extends React.Component {
  state = {keyword: undefined, category: undefined, occurredRange: null};

  componentDidMount() {
    runtimeStore.fetchSystemRecords(this.props.systemId);
  }

  fetchWithFilters = (overrides) => {
    const filters = {...this.state, ...overrides};
    const params = {};
    if (filters.keyword) params.keyword = filters.keyword;
    if (filters.category) params.category = filters.category;
    if (filters.occurredRange && filters.occurredRange.length === 2) {
      params.occurred_from = filters.occurredRange[0].format('YYYY-MM-DD HH:mm');
      params.occurred_to = filters.occurredRange[1].format('YYYY-MM-DD HH:mm');
    }
    runtimeStore.fetchSystemRecords(this.props.systemId, params);
  };

  columns = [{
    title: '编号',
    dataIndex: 'record_no',
    width: 140,
  }, {
    title: '标题',
    dataIndex: 'title',
    width: 200,
    ellipsis: true,
  }, {
    title: '异常类别',
    dataIndex: 'category_text',
    width: 90,
    render: text => text || <Tag>未归类</Tag>,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <Tag color={RUNTIME_STATUS_COLOR[text]}>{RUNTIME_STATUS_TEXT[text]}</Tag>,
  }, {
    // "关联"（重复关联数量）列已于 2026-10-05 随重复问题功能下线移除
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
          runtimeStore.showDetail(record.id);
        }}
      >详情</a>
    ),
  }];

  render() {
    return (
      <AuthDiv auth={PERM.RUNTIME_VIEW}>
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
            placeholder="异常类别"
            style={{width: 130, marginRight: 8}}
            value={this.state.category}
            onChange={v => {
              this.setState({category: v}, () => this.fetchWithFilters({category: v}));
            }}
          >
            {RUNTIME_CATEGORY_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
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
        {runtimeStore.systemLatestOccurredAt && (
          <div style={{marginBottom: 8, color: '#999'}}>
            最近发生时间：{runtimeStore.systemLatestOccurredAt}
          </div>
        )}
        <Table
          rowKey="id"
          size="small"
          loading={runtimeStore.isSystemRecordsFetching}
          pagination={{pageSize: 10, showTotal: total => `共 ${total} 条`}}
          dataSource={runtimeStore.systemRecords}
          columns={this.columns}
          locale={{emptyText: <Empty description="当前系统暂无运行异常记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
      </AuthDiv>
    );
  }
}

export default SystemRuntimeRecordsTab;

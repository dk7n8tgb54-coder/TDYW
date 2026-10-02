/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录待办视图（2026-10 第二版）。
 * 只展示"跟进中"记录（关闭或转故障后由后端状态机自然移出待办）；
 * 支持超期（计划处理时间早于当前时间）、指定跟进人、最近更新筛选。
 * 不做周期轮询、不为普通记录发提醒：仅在打开本页签或调整筛选时查询。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select, Tag, Table, Button, Alert } from 'antd';
import moment from 'moment';
import store from './store';
import {
  RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR, RUNTIME_IMPACT_TEXT, RUNTIME_IMPACT_COLOR,
} from '../constants';

function TodoFilters() {
  return (
    <div style={{marginBottom: 12}}>
      <Select
        allowClear
        style={{width: 160, marginRight: 8}}
        value={store.f_todo_overdue}
        onChange={v => {
          store.f_todo_overdue = v;
          store.fetchTodoRecords();
        }}
        placeholder="超期筛选"
      >
        <Select.Option value={true}>仅看超期</Select.Option>
      </Select>
      <Input.Search
        allowClear
        style={{width: 220, marginRight: 8}}
        value={store.f_todo_follow_up_name}
        onChange={e => store.f_todo_follow_up_name = e.target.value}
        onSearch={() => store.fetchTodoRecords()}
        placeholder="按跟进人筛选"
      />
      <Select
        style={{width: 160, marginRight: 8}}
        value={store.f_todo_order}
        onChange={v => {
          store.f_todo_order = v;
          store.fetchTodoRecords();
        }}
      >
        <Select.Option value="planned">按计划时间</Select.Option>
        <Select.Option value="recent">最近更新优先</Select.Option>
      </Select>
      <Button onClick={() => {store.resetTodoFilter(); store.fetchTodoRecords();}}>重置</Button>
    </div>
  );
}

@observer
class RecordTodo extends React.Component {
  componentDidMount() {
    store.fetchTodoRecords();
  }

  columns = [{
    title: '编号',
    dataIndex: 'record_no',
    width: 150,
  }, {
    title: '标题',
    dataIndex: 'title',
    width: 200,
    ellipsis: true,
  }, {
    title: '所属系统',
    dataIndex: 'system_name',
    width: 160,
    ellipsis: true,
  }, {
    title: '跟进人',
    dataIndex: 'follow_up_name',
    width: 110,
    render: text => text || '-',
  }, {
    title: '计划处理时间',
    dataIndex: 'planned_handle_at',
    width: 150,
    render: text => {
      if (!text) return <Tag>未排期</Tag>;
      // 超期高亮仅为展示强调；权威筛选由后端 overdue 条件完成
      return moment(text).isBefore(moment())
        ? <Tag color="red">{text}（超期）</Tag>
        : <Tag color="blue">{text}</Tag>;
    },
  }, {
    title: '影响状态',
    dataIndex: 'impact_status',
    width: 100,
    render: (text, record) => (
      record.affects_system_operation
        ? <Tag color={RUNTIME_IMPACT_COLOR[text]}>{RUNTIME_IMPACT_TEXT[text] || text}</Tag>
        : <Tag>不影响运行</Tag>
    ),
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: text => <Tag color={RUNTIME_STATUS_COLOR[text]}>{RUNTIME_STATUS_TEXT[text]}</Tag>,
  }, {
    title: '操作',
    width: 80,
    render: (text, record) => (
      <a onClick={() => store.showDetail(record)}>详情</a>
    ),
  }];

  render() {
    return (
      <div>
        {store.todoOverdueCount > 0 && (
          <Alert
            type="warning"
            showIcon
            style={{marginBottom: 12}}
            message={`当前有 ${store.todoOverdueCount} 条跟进中记录已超过计划处理时间`}
          />
        )}
        <TodoFilters/>
        <Table
          rowKey="id"
          loading={store.isTodoFetching}
          pagination={false}
          dataSource={store.todoRecords}
          columns={this.columns}
          locale={{emptyText: '暂无待办：没有处于跟进中的运行记录'}}
        />
      </div>
    );
  }
}

export default observer(RecordTodo);

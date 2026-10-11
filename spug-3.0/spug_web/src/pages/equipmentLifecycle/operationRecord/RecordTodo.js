/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行与故障记录待办视图（2026-10-11 合并改造）。
 * 只展示"跟进中"的异常事件记录（完成跟进或认定正式故障后由后端状态机
 * 自然移出待办），按最近更新优先排序；不做周期轮询、不为普通记录发提醒：
 * 仅在打开本页签时查询。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Tag, Table} from 'antd';
import store from './store';
import {RECORD_STATUS_TEXT, RECORD_STATUS_COLOR, RECORD_TYPE_TEXT, RECORD_TYPE_COLOR} from '../constants';

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
    width: 220,
    ellipsis: true,
  }, {
    title: '所属系统',
    dataIndex: 'system_name',
    width: 160,
    ellipsis: true,
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 150,
  }, {
    title: '类型',
    dataIndex: 'record_type',
    width: 90,
    render: text => (
      <Tag color={RECORD_TYPE_COLOR[text]}>{RECORD_TYPE_TEXT[text] || text}</Tag>
    ),
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: text => <Tag color={RECORD_STATUS_COLOR[text]}>{RECORD_STATUS_TEXT[text]}</Tag>,
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
        <Table
          rowKey="id"
          loading={store.isTodoFetching}
          pagination={false}
          dataSource={store.todoRecords}
          columns={this.columns}
          locale={{emptyText: '暂无待办：没有处于跟进中的异常事件记录'}}
        />
      </div>
    );
  }
}

export default observer(RecordTodo);

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录待办视图（2026-10 第二版；只含异常事件，
 * 日常运行记录不进入跟进流程，天然不会出现在待办中）。
 * 只展示"跟进中"记录（完成跟进或转故障后由后端状态机自然移出待办），
 * 按最近更新优先排序；跟进人/计划处理时间/超期维度已随跟进计划删除移除
 * （2026-10-06）。
 * 不做周期轮询、不为普通记录发提醒：仅在打开本页签时查询。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Tag, Table } from 'antd';
import store from './store';
import {
  RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR,
} from '../constants';

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

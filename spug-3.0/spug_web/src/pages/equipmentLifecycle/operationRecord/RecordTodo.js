/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行处置记录待办视图（2026-10-11 合并改造）。
 * 2026-10-14 体验二轮：待办口径扩展为"真正需要持续处理"的两类记录——
 * 跟进中的异常事件 + 处置中的设备故障（完成跟进/认定故障/确认恢复并结案/
 * 撤销后由后端状态机自然移出）。顶部展示全量分组计数（不随类型筛选变化），
 * 支持按类型分组筛选，分页全量可达（不做静默截断）；按最近更新优先排序。
 * 查询时机：由 index.handleTabChange 在切换到本页签时触发（操作后返回
 * 待办即看到最新结果），不做周期轮询。
 * 加载失败显式提示并可重试，不把旧结果冒充新查询结果；错误 toast 由
 * http 拦截器统一弹出。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Tag, Table, Select, Button, Alert} from 'antd';
import store from './store';
import {
  RECORD_STATUS_TEXT, RECORD_STATUS_COLOR, RECORD_TYPE_TEXT,
  RECORD_TYPE_COLOR, RECORD_TYPE_OPTIONS,
} from '../constants';

// 组件由文件末尾 export default observer(...) 统一包裹，不叠加装饰器
// （双重 observer 会触发 mobx 警告）
class RecordTodo extends React.Component {
  // 查询时机由 index.handleTabChange 驱动（页签切换即取最新）
  columns = [{
    title: '编号',
    dataIndex: 'record_no',
    width: 150,
  }, {
    title: '标题',
    dataIndex: 'title',
    width: 220,
    ellipsis: true,
    render: (text, record) => <a onClick={() => store.showDetail(record)}>{text}</a>,
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
    const counts = store.todoCounts || {};
    return (
      <div>
        {store.todoError && (
          <Alert
            type="warning"
            showIcon
            message="待办加载失败，以下可能为上次结果"
            action={
              <Button size="small" onClick={() => store.fetchTodoRecords()}>重试</Button>
            }
            style={{marginBottom: 12}}
          />
        )}
        <div style={{marginBottom: 12}}>
          <span style={{marginRight: 16}}>
            共 {counts.total ?? 0} 条待办：跟进中异常事件 {counts.following_up ?? 0} 条、
            处置中设备故障 {counts.handling ?? 0} 条
          </span>
          {/* 分组筛选：一般记录不进待办（无需要持续处理的状态），只列两类 */}
          <Select
            allowClear
            style={{width: 160}}
            placeholder="全部分组"
            value={store.f_todo_record_type}
            onChange={v => store.setTodoRecordType(v)}
          >
            {RECORD_TYPE_OPTIONS.filter(item => item.value !== 'routine').map(item => (
              <Select.Option value={item.value} key={item.value}>
                仅{item.label}
              </Select.Option>
            ))}
          </Select>
        </div>
        <Table
          rowKey="id"
          loading={store.isTodoFetching}
          pagination={{
            current: store.todoPage,
            pageSize: store.todoPageSize,
            total: store.todoTotal,
            showSizeChanger: true,
            onChange: (page, pageSize) => {
              store.todoPage = page;
              store.todoPageSize = pageSize;
              store.fetchTodoRecords();
            },
            showTotal: total => `共 ${total} 条`,
          }}
          dataSource={store.todoRecords}
          columns={this.columns}
          locale={{emptyText: store.todoError
            ? '待办加载失败'
            : '暂无待办：没有跟进中的异常事件或处置中的设备故障'}}
        />
      </div>
    );
  }
}

export default observer(RecordTodo);

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——工单页签（步骤 3.3，单系统简化）。
 * 只展示作业系统为当前系统的工单，不再区分目标/受影响工单；
 * 只查询当前系统（租户内）关联的工单，不泄露其他系统的数据。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Empty, Button } from 'antd';
import store from './store';
import WorkOrderDetail from './WorkOrderDetail';
import {
  WO_PERM, WORK_TYPE_TEXT, WO_STATUS_TEXT, WO_STATUS_COLOR, PRIORITY_TEXT, PRIORITY_COLOR,
  MAINTENANCE_SUBTYPE_TEXT,
} from './constants';

@observer
class WorkOrdersTab extends React.Component {
  state = {detailId: null, detailVisible: false};

  componentDidMount() {
    store.fetchSystemOrders(this.props.systemId);
  }

  columns = [{
    title: '工单编号',
    dataIndex: 'work_no',
    width: 150,
  }, {
    title: '标题',
    dataIndex: 'title',
    ellipsis: true,
  }, {
    title: '类型',
    dataIndex: 'work_type',
    width: 90,
    render: (text) => WORK_TYPE_TEXT[text] || text,
  }, {
    // 维护分类仅专项维护有业务含义；其他类型（含历史类型）显示 "-"
    title: '维护分类',
    dataIndex: 'maintenance_subtype',
    width: 90,
    render: (text, record) => (
      record.work_type === 'special_maintenance'
        ? (MAINTENANCE_SUBTYPE_TEXT[text] || text || '-') : '-'
    ),
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <Tag color={WO_STATUS_COLOR[text]}>{WO_STATUS_TEXT[text] || text}</Tag>,
  }, {
    title: '优先级',
    dataIndex: 'priority',
    width: 70,
    render: (text) => <Tag color={PRIORITY_COLOR[text]}>{PRIORITY_TEXT[text] || text}</Tag>,
  }, {
    title: '负责人',
    dataIndex: 'owner_name',
    width: 90,
    render: (text) => text || '-',
  }, {
    title: '计划开始',
    dataIndex: 'planned_start',
    width: 130,
    render: (text) => text || '-',
  }, {
    title: '操作',
    width: 70,
    render: (text, record) => (
      <Button
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => this.setState({detailId: record.id, detailVisible: true})}
      >
        详情
      </Button>
    ),
  }];

  render() {
    return (
      <div>
        <Table
          rowKey="id"
          size="small"
          loading={store.isSystemOrdersFetching}
          columns={this.columns}
          dataSource={store.systemOrders}
          pagination={false}
          locale={{emptyText: <Empty description="暂无关联工单" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
        {this.state.detailVisible && (
          <WorkOrderDetail
            woId={this.state.detailId}
            visible={this.state.detailVisible}
            onClose={() => this.setState({detailVisible: false})}
          />
        )}
      </div>
    );
  }
}

export default WorkOrdersTab;

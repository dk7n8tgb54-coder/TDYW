/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——故障记录页签（步骤 3.1，单系统简化）。
 * 只展示故障系统为当前系统的故障，不再区分主体/受影响故障；
 * 不含台账与统一系统履历。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Empty } from 'antd';
import { AuthDiv } from 'components';
import store from './faultStore';
import FaultStatusTag from './FaultStatusTag';
import { PERM, FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR } from './constants';

@observer
class FaultRecordsTab extends React.Component {
  componentDidMount() {
    store.fetchSystemFaults(this.props.systemId);
  }

  columns = [{
    title: '故障编号',
    dataIndex: 'fault_no',
    width: 150,
  }, {
    title: '影响状态',
    dataIndex: 'impact_status',
    width: 110,
    render: (text, record) => (
      record.affects_system_operation ? (
        <Tag color={FAULT_IMPACT_COLOR[text]}>{FAULT_IMPACT_TEXT[text] || text}</Tag>
      ) : (
        // 部件故障/离线维修：不影响系统对外服务，独立于系统运行状态展示
        <Tag>不影响运行</Tag>
      )
    ),
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <FaultStatusTag status={text}/>,
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    title: '故障登记人',
    dataIndex: 'registrar_name',
    width: 100,
    render: (text) => text || '-',
  }, {
    title: '故障现象',
    dataIndex: 'phenomenon',
    ellipsis: true,
  }];

  render() {
    return (
      <AuthDiv auth={PERM.FAULT_VIEW}>
        <Table
          rowKey="id"
          size="small"
          loading={store.isSystemFaultsFetching}
          pagination={{pageSize: 10, showTotal: total => `共 ${total} 条`}}
          dataSource={store.systemFaults}
          columns={this.columns}
          locale={{emptyText: <Empty description="当前系统暂无故障记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
        />
      </AuthDiv>
    );
  }
}

export default FaultRecordsTab;

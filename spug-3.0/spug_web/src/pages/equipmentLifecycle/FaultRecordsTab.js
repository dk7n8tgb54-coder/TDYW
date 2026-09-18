/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——故障记录页签（步骤 3.1）。
 * 区分当前系统作为主故障系统的「主体故障」与作为受影响系统的「受影响故障」；
 * 不含台账、工单与统一系统履历。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Radio, Empty } from 'antd';
import { AuthDiv } from 'components';
import store from './faultStore';
import { PERM, FAULT_STATUS_TEXT, FAULT_STATUS_COLOR, FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR } from './constants';

const ROLE_OPTIONS = [
  {value: 'all', label: '全部'},
  {value: 'primary', label: '主体故障'},
  {value: 'affected', label: '受影响故障'},
];

@observer
class FaultRecordsTab extends React.Component {
  componentDidMount() {
    store.fetchSystemFaults(this.props.systemId, store.systemFaultRole);
  }

  componentWillUnmount() {
    store.systemFaultRole = 'all';
  }

  columns = [{
    title: '故障编号',
    dataIndex: 'fault_no',
    width: 150,
  }, {
    title: '角色',
    dataIndex: 'fault_role',
    width: 100,
    render: (text, record) => (
      <Tag color={text === 'primary' ? 'red' : 'orange'}>{record.fault_role_text}</Tag>
    ),
  }, {
    title: '影响状态',
    dataIndex: 'primary_impact_status',
    width: 90,
    render: (text, record) => {
      // 主体故障显示主系统影响状态；受影响故障显示本系统受影响状态
      const status = record.fault_role === 'affected' ? record.impact_status : text;
      return <Tag color={FAULT_IMPACT_COLOR[status]}>{FAULT_IMPACT_TEXT[status] || '-'}</Tag>;
    },
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: (text) => <Tag color={FAULT_STATUS_COLOR[text]}>{FAULT_STATUS_TEXT[text]}</Tag>,
  }, {
    title: '发生时间',
    dataIndex: 'occurred_at',
    width: 140,
  }, {
    title: '故障现象',
    dataIndex: 'phenomenon',
    ellipsis: true,
  }];

  render() {
    return (
      <AuthDiv auth={PERM.FAULT_VIEW}>
        <div style={{marginBottom: 12}}>
          <Radio.Group
            value={store.systemFaultRole}
            onChange={e => store.fetchSystemFaults(this.props.systemId, e.target.value)}
            optionType="button"
            options={ROLE_OPTIONS}
          />
        </div>
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

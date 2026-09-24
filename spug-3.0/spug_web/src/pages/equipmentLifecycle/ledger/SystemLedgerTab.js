/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——巡检/周月维护/季维护台账 Tab（步骤 3.2）。
 * 只查询当前系统对应的台账明细（服务端按系统 ID 过滤并做权限校验），
 * 一张台账包含其他系统的明细不会在此显示。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Table, Tag, Empty} from 'antd';
import {http} from 'libs';
import {
  API_PREFIX_L, CYCLE_TEXT, LEDGER_TYPE_TEXT, RESULT_COLOR, RESULT_TEXT, STATUS_COLOR, STATUS_TEXT,
} from './constants';

@observer
class SystemLedgerTab extends React.Component {
  state = {records: [], loading: false};

  componentDidMount() {
    this.fetchRecords();
  }

  componentDidUpdate(prevProps) {
    if (prevProps.systemId !== this.props.systemId || prevProps.ledgerType !== this.props.ledgerType) {
      this.fetchRecords();
    }
  }

  fetchRecords = () => {
    const {systemId, ledgerType} = this.props;
    if (!systemId) return;
    this.setState({loading: true});
    http.get(`${API_PREFIX_L}/systems/${systemId}/ledger-items/`, {params: {ledger_type: ledgerType}})
      .then(res => {
        this.setState({records: res.data});
      })
      .catch(() => {})
      .finally(() => this.setState({loading: false}));
  };

  columns = [
    {title: '台账编号', key: 'ledger_no', width: 180, render: (t, r) => r.ledger_no},
    {title: '台账类型', key: 'ledger_type', width: 100, render: (t, r) => LEDGER_TYPE_TEXT[r.ledger_type] || r.ledger_type},
    {
      title: '执行日期', key: 'executed_date', width: 100,
      render: (t, r) => r.ledger_executed_date,
    },
    {title: '项目', dataIndex: 'item_name', width: 160},
    {title: '填写值', key: 'value', width: 100, render: (t, r) => r.value_text || (r.value_number === null || r.value_number === undefined ? '-' : r.value_number)},
    {
      title: '结果', dataIndex: 'result', width: 80,
      render: v => <Tag color={RESULT_COLOR[v]}>{RESULT_TEXT[v] || v}</Tag>,
    },
    {title: '异常说明', dataIndex: 'abnormal_desc', ellipsis: true, render: v => v || '-'},
    {
      title: '台账状态', key: 'status', width: 90,
      render: (t, r) => <Tag color={STATUS_COLOR[r.ledger_status]}>{STATUS_TEXT[r.ledger_status] || r.ledger_status}</Tag>,
    },
  ];

  render() {
    const {records, loading} = this.state;
    return (
      <div>
        {records.length === 0 && !loading ? (
          <Empty description="暂无台账明细"/>
        ) : (
          <Table
            rowKey="id" size="small"
            loading={loading}
            dataSource={records}
            columns={this.columns}
            pagination={{showSizeChanger: false, showTotal: t => `共 ${t} 条`}}
            rowClassName={r => (r.result === 'abnormal' ? 'el-ledger-abnormal-row' : '')}
          />
        )}
      </div>
    );
  }
}

export default SystemLedgerTab;

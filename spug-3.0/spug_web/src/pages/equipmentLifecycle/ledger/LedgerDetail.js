/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账详情抽屉：表头信息 + 按系统分组的明细列表（含异常突出显示）。
 * 步骤 3.3：异常明细展示处置状态，支持"转故障"/"转工单"，处置目标可跳转。
 */
import React, { useState } from 'react';
import {observer} from 'mobx-react';
import {Drawer, Tabs, Descriptions, Tag, Spin, Table, Collapse, Empty} from 'antd';
import {
  CREATED_FROM_TEXT, CYCLE_TEXT, EXEC_SCOPE_TEXT, LEDGER_TYPE_TEXT, RESULT_COLOR,
  RESULT_TEXT, STATUS_COLOR, STATUS_TEXT,
} from './constants';
import { DispositionTag, ConvertActions } from '../workOrder/LedgerItemDisposition';
import WorkOrderDetail from '../workOrder/WorkOrderDetail';

const {TabPane} = Tabs;
const {Panel} = Collapse;

const RESULT_TAG_STYLE = {marginRight: 0};

@observer
class LedgerDetail extends React.Component {
  state = {workOrderDetailId: null, workOrderDetailVisible: false};

  openWorkOrderDetail = (id) => {
    this.setState({workOrderDetailId: id, workOrderDetailVisible: true});
  };

  refreshConverted = () => {
    // 转单成功后重新获取台账详情（处置状态由后端重新计算）
    this.props.store.fetchDetail();
  };

  renderValue = (item) => {
    if (item.input_type === 'number') return item.value_number === null || item.value_number === undefined ? '-' : item.value_number;
    if (item.input_type === 'boolean') return item.value_bool === null || item.value_bool === undefined ? '-' : (item.value_bool ? '是' : '否');
    if (item.input_type === 'multi_choice') {
      try {
        const arr = item.value_text ? JSON.parse(item.value_text) : [];
        return arr.length ? arr.join('、') : '-';
      } catch (e) {
        return item.value_text || '-';
      }
    }
    return item.value_text || '-';
  };

  renderItems = (items) => {
    const columns = [
      {title: '项目', dataIndex: 'item_name', width: 160},
      {title: '填写值', key: 'value', width: 110, render: (t, r) => this.renderValue(r)},
      {title: '单位', dataIndex: 'unit', width: 70, render: v => v || '-'},
      {
        title: '结果', dataIndex: 'result', width: 90,
        render: v => <Tag color={RESULT_COLOR[v]} style={RESULT_TAG_STYLE}>{RESULT_TEXT[v] || v}</Tag>,
      },
      {title: '异常说明', dataIndex: 'abnormal_desc', width: 160, render: v => v || '-'},
      {title: '现场处理', dataIndex: 'onsite_action', width: 160, render: v => v || '-'},
      {
        title: '处置状态', key: 'disposition', width: 130,
        render: (t, r) => (
          <span>
            <DispositionTag item={r}/>
            <ConvertActions
              ledger={this.props.store.detail}
              item={r}
              onOpenWorkOrder={this.openWorkOrderDetail}
              onConverted={this.refreshConverted}
            />
          </span>
        ),
      },
      {title: '执行人', dataIndex: 'executor_name', width: 90, render: v => v || '-'},
      {title: '执行时间', dataIndex: 'executed_at', width: 140, render: v => v || '-'},
    ];
    return (
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={items}
        pagination={false}
        rowClassName={r => r.result === 'abnormal' ? 'el-ledger-abnormal-row' : ''}
      />
    );
  };

  render() {
    const {store} = this.props;
    const d = store.detail;
    // 按系统分组
    const groups = [];
    const groupMap = {};
    (d.items || []).forEach(item => {
      const key = String(item.system);
      if (!groupMap[key]) {
        groupMap[key] = {system_name: item.system_name, items: []};
        groups.push(groupMap[key]);
      }
      groupMap[key].items.push(item);
    });
    return (
      <Drawer
        title={`${LEDGER_TYPE_TEXT[d.ledger_type] || ''}台账详情 - ${d.ledger_no || ''}`}
        visible={store.detailVisible}
        width={1000}
        onClose={() => store.closeDetail()}
        destroyOnClose>
        <Spin spinning={store.isDetailFetching}>
          <Tabs defaultActiveKey="basic">
            <TabPane tab="基本信息" key="basic">
              <Descriptions size="small" column={2} bordered>
                <Descriptions.Item label="台账编号">{d.ledger_no}</Descriptions.Item>
                <Descriptions.Item label="台账类型">
                  {LEDGER_TYPE_TEXT[d.ledger_type]}
                  {d.maintenance_cycle ? `（${CYCLE_TEXT[d.maintenance_cycle]}）` : ''}
                </Descriptions.Item>
                <Descriptions.Item label="实际执行日期">{d.executed_date}</Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={STATUS_COLOR[d.status]}>{STATUS_TEXT[d.status] || d.status}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="实际执行开始">{d.executed_start || '-'}</Descriptions.Item>
                <Descriptions.Item label="实际执行结束">{d.executed_end || '-'}</Descriptions.Item>
                <Descriptions.Item label="执行人">{d.executor_names || '-'}</Descriptions.Item>
                <Descriptions.Item label="创建方式">{CREATED_FROM_TEXT[d.created_from] || d.created_from}</Descriptions.Item>
                <Descriptions.Item label="录入渠道">{d.entry_channel}</Descriptions.Item>
                {d.status === 'returned' && (
                  <Descriptions.Item label="退回原因" span={2}>
                    <span style={{color: '#fa8c16'}}>{d.return_reason}</span>
                  </Descriptions.Item>
                )}
                {d.status === 'void' && (
                  <Descriptions.Item label="作废原因" span={2}>{d.void_reason}</Descriptions.Item>
                )}
                <Descriptions.Item label="录入人">{d.created_by_name}</Descriptions.Item>
                <Descriptions.Item label="平台录入时间">{d.created_at}</Descriptions.Item>
                {d.reviewer_name && (
                  <Descriptions.Item label="复核人" span={2}>
                    {d.reviewer_name}（{d.reviewed_at}）
                  </Descriptions.Item>
                )}
              </Descriptions>
            </TabPane>
            <TabPane tab="检查明细" key="items">
              {groups.length === 0 ? <Empty description="暂无明细"/> : (
                <Collapse defaultActiveKey={groups.map((g, i) => String(i))}>
                  {groups.map((g, i) => (
                    <Panel
                      header={g.system_name}
                      key={String(i)}
                      extra={
                        <span>
                          {g.items.length} 项
                          {g.items.some(x => x.result === 'abnormal') && (
                            <span style={{color: '#f5222d', marginLeft: 8}}>
                              异常 {g.items.filter(x => x.result === 'abnormal').length}
                            </span>
                          )}
                        </span>
                      }>
                      {this.renderItems(g.items)}
                    </Panel>
                  ))}
                </Collapse>
              )}
            </TabPane>
            {(d.corrections || []).length > 0 && (
              <TabPane tab="更正记录" key="corrections">
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  columns={[
                    {title: '更正时间', dataIndex: 'corrected_at', width: 160},
                    {title: '更正人', dataIndex: 'corrected_by_name', width: 100},
                    {title: '更正原因', dataIndex: 'reason'},
                    {
                      title: '变更内容', key: 'changes',
                      render: (t, r) => (r.changes || []).map((c, i) => (
                        <div key={i}>{c.label}: {String(c.old)} → {String(c.new)}</div>
                      )),
                    },
                  ]}
                  dataSource={d.corrections}
                />
              </TabPane>
            )}
          </Tabs>
        </Spin>
        {/* 异常明细生成的工单详情（嵌套抽屉，跳回来源由工单侧提供） */}
        {this.state.workOrderDetailVisible && (
          <WorkOrderDetail
            woId={this.state.workOrderDetailId}
            visible={this.state.workOrderDetailVisible}
            onClose={() => this.setState({workOrderDetailVisible: false})}
          />
        )}
      </Drawer>
    );
  }
}

export default LedgerDetail;

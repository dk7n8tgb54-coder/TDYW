/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账详情抽屉（手工补录台账）：表头信息 + 按系统分组的明细列表（含异常突出显示）。
 * 异常明细展示处置状态并支持"转故障"（处置目标可跳转）；
 * 已完成台账支持逐项"更正"（须填原因，前后值记入更正记录，2026-10-16）；
 * 转工单已随故障维修工单功能整体删除（2026-09-30）；
 * 旧可视化模板矩阵台账分支已随路线删除（2026-10），Excel 来源台账由
 * ExcelLedgerDetail 承载，不走本组件。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Drawer, Tabs, Descriptions, Tag, Spin, Table, Collapse, Empty, Input,
  InputNumber, Modal, Select, message,
} from 'antd';
import {
  CREATED_FROM_TEXT, LEDGER_TYPE_TEXT, PERM_L, RESULT_COLOR,
  RESULT_TEXT, STATUS_COLOR, STATUS_TEXT,
} from './constants';
import {hasPermission} from 'libs';
import { DispositionTag, ConvertActions } from './LedgerItemDisposition';

const {TabPane} = Tabs;
const {Panel} = Collapse;

const RESULT_TAG_STYLE = {marginRight: 0};

/** 已完成台账明细更正弹窗（2026-10-16）：须填原因；提交走
 * POST /ledgers/<pk>/correct/（后端记录修改人/时间/前后值并生成更正记录）。 */
export function ItemCorrectModal({item, saving, onOk, onCancel}) {
  const [reason, setReason] = React.useState('');
  const [form, setForm] = React.useState(() => ({
    value_text: item.value_text || '',
    value_number: item.value_number === null || item.value_number === undefined
      ? null : item.value_number,
    value_bool: item.value_bool,
    abnormal_desc: item.abnormal_desc || '',
    onsite_action: item.onsite_action || '',
  }));
  const setField = (key, value) => setForm(prev => ({...prev, [key]: value}));
  const valueControl = () => {
    if (item.input_type === 'number') {
      return <InputNumber style={{width: '100%'}} value={form.value_number}
                          onChange={v => setField('value_number', v)}/>;
    }
    if (item.input_type === 'boolean') {
      return (
        <Select style={{width: '100%'}} allowClear value={form.value_bool}
                onChange={v => setField('value_bool', v)}
                placeholder="请选择是/否">
          <Select.Option value={true}>是</Select.Option>
          <Select.Option value={false}>否</Select.Option>
        </Select>
      );
    }
    if (item.input_type === 'choice') {
      return (
        <Select style={{width: '100%'}} value={form.value_text || undefined}
                onChange={v => setField('value_text', v || '')}>
          {(item.choices || []).map(c => <Select.Option key={c} value={c}>{c}</Select.Option>)}
        </Select>
      );
    }
    if (item.input_type === 'multi_choice') {
      let values = [];
      try { values = item.value_text ? JSON.parse(item.value_text) : []; } catch (e) { values = []; }
      return (
        <Select mode="multiple" style={{width: '100%'}} value={values}
                onChange={v => setField('value_text', v)}>
          {(item.choices || []).map(c => <Select.Option key={c} value={c}>{c}</Select.Option>)}
        </Select>
      );
    }
    if (item.input_type === 'attachment') return null;
    return <Input value={form.value_text} onChange={e => setField('value_text', e.target.value)}/>;
  };
  return (
    <Modal title={`更正明细：${item.item_name}`}
           visible={!!item}
           confirmLoading={saving}
           okText="提交更正" cancelText="取消"
           okButtonProps={{disabled: !reason.trim()}}
           onOk={() => onOk({...form, reason: reason.trim()})}
           onCancel={onCancel}
           destroyOnClose>
      <p style={{color: '#666', marginBottom: 8}}>
        更正须填写原因；提交后修改人、时间与修改前后内容将记入更正记录。
      </p>
      <div style={{marginBottom: 4}}>更正原因（必填）</div>
      <Input.TextArea
        data-testid="correct-reason" rows={2} maxLength={200} value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder="请填写更正原因"/>
      {item.input_type !== 'attachment' && (
        <React.Fragment>
          <div style={{margin: '8px 0 4px'}}>填写值</div>
          {valueControl()}
        </React.Fragment>
      )}
      <div style={{margin: '8px 0 4px'}}>异常说明</div>
      <Input value={form.abnormal_desc}
             onChange={e => setField('abnormal_desc', e.target.value)}/>
      <div style={{margin: '8px 0 4px'}}>现场处理内容</div>
      <Input value={form.onsite_action}
             onChange={e => setField('onsite_action', e.target.value)}/>
    </Modal>
  );
}

@observer
class LedgerDetail extends React.Component {
  state = {correctItem: null};

  refreshConverted = () => {
    // 转故障成功后重新获取台账详情（处置状态由后端重新计算）
    this.props.store.fetchDetail();
  };

  get canCorrect() {
    const d = this.props.store.detail;
    return d && d.status === 'completed' && hasPermission(PERM_L.LED_EDIT);
  }

  handleCorrectOk = (body) => {
    const item = this.state.correctItem;
    Promise.resolve(this.props.store.correctLedgerItem(item.id, body))
      .then(() => {
        message.success('更正已保存');
        this.setState({correctItem: null});
      })
      .catch(() => {});
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
              onConverted={this.refreshConverted}
            />
          </span>
        ),
      },
      {title: '执行时间', dataIndex: 'executed_at', width: 140, render: v => v || '-'},
    ];
    if (this.canCorrect) {
      columns.push({
        title: '操作', key: 'correct', width: 70, align: 'center',
        render: (t, r) => (
          <a data-testid="item-correct" onClick={() => this.setState({correctItem: r})}>更正</a>
        ),
      });
    }
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

  /** 基本信息页签。 */
  renderBasicTab = (d) => (
    <TabPane tab="基本信息" key="basic">
      <Descriptions size="small" column={2} bordered>
        <Descriptions.Item label="台账编号">{d.ledger_no}</Descriptions.Item>
        <Descriptions.Item label="台账类型">{LEDGER_TYPE_TEXT[d.ledger_type]}</Descriptions.Item>
        <Descriptions.Item label="实际执行日期">{d.executed_date}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={STATUS_COLOR[d.status]}>{STATUS_TEXT[d.status] || d.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="实际执行开始">{d.executed_start || '-'}</Descriptions.Item>
        <Descriptions.Item label="实际执行结束">{d.executed_end || '-'}</Descriptions.Item>
        <Descriptions.Item label="创建方式">{CREATED_FROM_TEXT[d.created_from] || d.created_from}</Descriptions.Item>
        <Descriptions.Item label="录入渠道">{d.entry_channel}</Descriptions.Item>
        {d.status === 'void' && (
          <Descriptions.Item label="作废原因" span={2}>{d.void_reason}</Descriptions.Item>
        )}
        <Descriptions.Item label="录入人">{d.created_by_name}</Descriptions.Item>
        <Descriptions.Item label="平台录入时间">{d.created_at}</Descriptions.Item>
        {d.completed_at && (
          <Descriptions.Item label="完成时间" span={2}>
            {String(d.completed_at).slice(0, 19).replace('T', ' ')}
          </Descriptions.Item>
        )}
      </Descriptions>
    </TabPane>
  );

  /** 明细页签：按系统分组展示，不补造行树。 */
  renderItemsTab = (d) => {
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
    );
  };

  /** 更正记录页签（有更正记录时才展示）。 */
  renderCorrectionsTab = (d) => {
    if (!(d.corrections || []).length) return null;
    return (
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
    );
  };

  render() {
    const {store} = this.props;
    const d = store.detail;
    return (
      <Drawer
        title={`${LEDGER_TYPE_TEXT[d.ledger_type] || ''}台账详情 - ${d.ledger_no || ''}`}
        visible={store.detailVisible}
        width={1000}
        onClose={() => store.closeDetail()}
        destroyOnClose>
        <Spin spinning={store.isDetailFetching}>
          <Tabs defaultActiveKey="basic">
            {this.renderBasicTab(d)}
            {this.renderItemsTab(d)}
            {this.renderCorrectionsTab(d)}
          </Tabs>
        </Spin>
        {this.canCorrect && (
          <ItemCorrectModal
            item={this.state.correctItem}
            saving={store.isCorrecting}
            onOk={this.handleCorrectOk}
            onCancel={() => this.setState({correctItem: null})}/>
        )}
      </Drawer>
    );
  }
}

export default LedgerDetail;

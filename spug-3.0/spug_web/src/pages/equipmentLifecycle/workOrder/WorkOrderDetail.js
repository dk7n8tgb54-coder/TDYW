/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 工单详情抽屉（步骤 3.3，单账号协同流程）——props 驱动的可复用组件。
 * 可在工单列表页、故障详情、台账详情、系统详情中嵌入使用（无全局单例依赖）。
 * 包含：基本信息 / 来源追溯（跳转）/ 参与人员（历史）/ 处理记录时间线
 * / 完成工单 / 关闭 / 取消。
 * 派发/接单/开始执行/提交复核/复核通过或退回已下线；历史工单的
 * 负责人/派发/接单/复核信息以"历史流程信息"分区展示；
 * 所有动作成功后重新获取后端真实数据；错误提示由 http 拦截器统一弹出。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Drawer, Tabs, Descriptions, Tag, Spin, Button, Timeline, Modal, Form,
  Input, DatePicker, InputNumber, message, Empty } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import moment from 'moment';
import { http, history } from 'libs';
import { AuthButton } from 'components';
import {
  WO_PERM, WORK_TYPE_TEXT, WO_STATUS_TEXT, WO_STATUS_COLOR, PRIORITY_TEXT,
  PRIORITY_COLOR, WO_SOURCE_TEXT, LEDGER_TYPE_PATH,
} from './constants';

const {TextArea} = Input;
const {TabPane} = Tabs;
const API_PREFIX = '/api/equipment-lifecycle';

// 历史兼容状态（旧流程）：仅保留受控取消，不再提供派发/接单/复核操作
const LEGACY_STATUSES = ['pending_dispatch', 'pending_accept', 'pending_review'];

export default function WorkOrderDetail({woId, visible, onClose}) {
  const [detail, setDetail] = useState({});
  const [records, setRecords] = useState([]);
  const [fetching, setFetching] = useState(false);
  const [recordsFetching, setRecordsFetching] = useState(false);
  const [acting, setActing] = useState(false);

  const fetchDetail = useCallback((id) => {
    if (!id) return Promise.resolve();
    setFetching(true);
    return http.get(`${API_PREFIX}/work-orders/${id}/`)
      .then(res => setDetail(res || {}))
      .catch(() => {})
      .finally(() => setFetching(false));
  }, []);

  const fetchRecords = useCallback((id) => {
    if (!id) return Promise.resolve();
    setRecordsFetching(true);
    return http.get(`${API_PREFIX}/work-orders/${id}/handling-records/`)
      .then(res => setRecords(res.data || []))
      .catch(() => {})
      .finally(() => setRecordsFetching(false));
  }, []);

  useEffect(() => {
    if (visible && woId) {
      setRecords([]);
      fetchDetail(woId);
      fetchRecords(woId);
    }
  }, [visible, woId, fetchDetail, fetchRecords]);

  const runAction = (actionName, extra = {}) => {
    setActing(true);
    return http.post(`${API_PREFIX}/work-orders/${woId}/${actionName}/`, extra)
      .then(res => {
        setDetail(res || {});
        fetchRecords(woId);
      })
      .finally(() => setActing(false));
  };

  const gotoFault = (faultId) => {
    onClose();
    history.push(`/el/faults?detail=${faultId}`);
  };

  const gotoLedger = (ledgerType, ledgerId) => {
    const path = LEDGER_TYPE_PATH[ledgerType];
    if (!path || !ledgerId) return;
    onClose();
    history.push(`${path}?detail=${ledgerId}`);
  };

  // 巡检来源跳转：跳到巡检单记录页打开来源值班巡检单（新巡检独立链路）
  const gotoInspectionSheet = (sheetId) => {
    if (!sheetId) return;
    onClose();
    history.push(`/el/inspection-sheets?detail=${sheetId}`);
  };

  const status = detail.status;

  return (
    <Drawer
      title={`工单详情 - ${detail.work_no || ''}`}
      visible={visible}
      width={900}
      onClose={onClose}
      destroyOnClose
    >
      <Spin spinning={fetching}>
        <StatusActionBar detail={detail} acting={acting} runAction={runAction}/>
        <Tabs defaultActiveKey="basic">
          <TabPane tab="基本信息" key="basic">
            {renderBasic(detail, gotoFault, gotoLedger, gotoInspectionSheet)}
          </TabPane>
          <TabPane tab={`参与人员${detail.participants ? `（${detail.participants.length}）` : ''}`} key="participants">
            {renderParticipants(detail)}
          </TabPane>
          <TabPane tab="处理记录" key="handling">
            <HandlingTimeline
              records={records}
              fetching={recordsFetching}
              editable={status === 'executing'}
              onAdd={(payload) => runActionRawPost(woId, 'handling-records', payload)
                .then(() => fetchRecords(woId))}
              onCorrect={(rid, payload) => http
                .put(`${API_PREFIX}/work-orders/${woId}/handling-records/${rid}/`, payload)
                .then(() => fetchRecords(woId))}
            />
          </TabPane>
        </Tabs>
      </Spin>
    </Drawer>
  );
}

async function runActionRawPost(woId, path, payload) {
  await http.post(`${API_PREFIX}/work-orders/${woId}/${path}/`, payload);
}

/** 状态动作按钮栏：执行中→完成工单/取消；已完成→关闭工单；历史兼容状态→仅取消。 */
function StatusActionBar({detail, acting, runAction}) {
  const status = detail.status;
  return (
    <div style={{marginBottom: 12}}>
      {status === 'executing' && (
        <span>
          <CompleteButton runAction={runAction} acting={acting}/>
          <CancelButton order={detail} runAction={runAction} acting={acting}/>
        </span>
      )}
      {status === 'completed' && (
        <AuthButton
          auth={WO_PERM.CLOSE}
          type="primary"
          loading={acting}
          onClick={() => runAction('close').then(() => message.success('工单已关闭')).catch(() => {})}
        >
          关闭工单
        </AuthButton>
      )}
      {LEGACY_STATUSES.includes(status) && <CancelButton order={detail} runAction={runAction} acting={acting}/>}
    </div>
  );
}

function renderBasic(d, gotoFault, gotoLedger, gotoInspectionSheet) {
  return (
    <div>
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="工单编号">{d.work_no}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={WO_STATUS_COLOR[d.status]}>{WO_STATUS_TEXT[d.status] || d.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="工单标题" span={2}>{d.title}</Descriptions.Item>
        <Descriptions.Item label="工单类型">{WORK_TYPE_TEXT[d.work_type] || d.work_type}</Descriptions.Item>
        <Descriptions.Item label="优先级">
          <Tag color={PRIORITY_COLOR[d.priority]}>{PRIORITY_TEXT[d.priority] || d.priority}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="作业系统">
          {d.system_name || ''}
        </Descriptions.Item>
        <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="作业期间影响系统运行">
          <Tag color={d.affects_system_operation ? 'geekblue' : 'default'}>
            {d.affects_system_operation ? '影响运行' : '不影响运行'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="作业位置">{d.work_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="作业对象">
          {[d.work_object_desc, d.work_component_name && `组成项：${d.work_component_name}`]
            .filter(Boolean).join('；') || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="来源类型">{WO_SOURCE_TEXT[d.source_type] || d.source_type}</Descriptions.Item>
        <Descriptions.Item label="来源单据">
          {d.source_type === 'fault' && d.source_fault ? (
            <Button type="link" size="small" style={{padding: 0}} onClick={() => gotoFault(d.source_fault)}>
              {d.source_no || '查看来源故障'}
            </Button>
          ) : d.source_type === 'ledger_item' && d.source_ledger ? (
            <Button type="link" size="small" style={{padding: 0}}
                    onClick={() => gotoLedger(d.source_ledger_type, d.source_ledger)}>
              {d.source_no || '查看来源台账'}
            </Button>
          ) : d.source_type === 'ledger_item' && d.source_ledger_legacy && d.source_ledger_no ? (
            <span>{d.source_ledger_no}（旧巡检台账（历史）已删除，来源为历史台账明细）</span>
          ) : d.source_type === 'inspection_record' && d.source_inspection_sheet ? (
            <Button type="link" size="small" style={{padding: 0}}
                    onClick={() => gotoInspectionSheet(d.source_inspection_sheet)}>
              {d.source_inspection_sheet_no || '查看来源巡检单'}
            </Button>
          ) : (d.source_no || '-')}
        </Descriptions.Item>
        <Descriptions.Item label="计划开始">{d.planned_start || '-'}</Descriptions.Item>
        <Descriptions.Item label="计划结束">{d.planned_end || '-'}</Descriptions.Item>
        <Descriptions.Item label="实际开始">{d.actual_start || '-'}</Descriptions.Item>
        <Descriptions.Item label="实际完成">{d.actual_end || '-'}</Descriptions.Item>
        <Descriptions.Item label="作业要求" span={2}>{d.work_requirement || '-'}</Descriptions.Item>
        <Descriptions.Item label="作业步骤" span={2}>{d.work_steps || '-'}</Descriptions.Item>
        <Descriptions.Item label="处理结果" span={2}>{d.process_result || '-'}</Descriptions.Item>
        <Descriptions.Item label="工时（小时）">{d.work_hours ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="系统中断（小时）">{d.interrupt_hours ?? '-'}</Descriptions.Item>
        <Descriptions.Item label="材料说明" span={2}>{d.material_note || '-'}</Descriptions.Item>
        <Descriptions.Item label="完成账号">{d.completed_by_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="完成时间">{d.completed_at || '-'}</Descriptions.Item>
        {d.status === 'cancelled' && (
          <Descriptions.Item label="取消原因" span={2}>
            {d.cancelled_by_name ? `${d.cancelled_by_name}（${d.cancelled_at || ''}）：` : ''}
            {d.cancel_reason || '-'}
          </Descriptions.Item>
        )}
        <Descriptions.Item label="创建人">{d.created_by_name}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{d.created_at}</Descriptions.Item>
      </Descriptions>
      <LegacyProcessSection d={d}/>
    </div>
  );
}

/** 历史流程信息（旧流程派发/接单/复核/退回），仅历史工单有数据时展示。 */
function LegacyProcessSection({d}) {
  const hasLegacy = !!(d.owner_name || d.dispatched_by_name || d.accepted_by_name
    || d.reviewer_name || d.review_result || d.return_reason);
  if (!hasLegacy) return null;
  return (
    <div style={{marginTop: 16}}>
      <div style={{color: '#999', marginBottom: 8}}>历史流程信息（旧流程，仅供参考）</div>
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="负责人">{d.owner_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="派发">
          {d.dispatched_by_name ? `${d.dispatched_by_name}（${d.dispatched_at || ''}）` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="接单">
          {d.accepted_by_name ? `${d.accepted_by_name}（${d.accepted_at || ''}）` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="复核">
          {d.reviewer_name ? `${d.reviewer_name}（${d.reviewed_at || ''}）` : '-'}
        </Descriptions.Item>
        {d.review_result && (
          <Descriptions.Item label="复核结果" span={2}>{d.review_result}</Descriptions.Item>
        )}
        {d.return_reason && (
          <Descriptions.Item label="退回原因" span={2}>
            <span style={{color: '#fa8c16'}}>{d.return_reason}</span>
          </Descriptions.Item>
        )}
      </Descriptions>
    </div>
  );
}

function renderParticipants(d) {
  const rows = d.participants || [];
  if (!rows.length) {
    return <Empty description="无参与人员（新流程不再指派参与人，历史工单保留展示）"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}/>;
  }
  return (
    <Descriptions bordered size="small" column={1}>
      {rows.map(row => (
        <Descriptions.Item
          key={row.id}
          label={row.nickname || row.username}
        >
          <Tag color={row.role === 'owner' ? 'geekblue' : 'default'}>{row.role_text}</Tag>
        </Descriptions.Item>
      ))}
    </Descriptions>
  );
}

/* ========== 动作按钮与弹窗 ========== */

/** 完成工单：沿用原提交复核表单字段（处理结果必填，工时/系统中断选填）。 */
function CompleteButton({runAction, acting}) {
  const [visible, setVisible] = useState(false);
  return (
    <span>
      <AuthButton
        auth={WO_PERM.EXECUTE}
        type="primary"
        loading={acting}
        onClick={() => setVisible(true)}
      >
        完成工单
      </AuthButton>
      <CompleteModal
        visible={visible}
        acting={acting}
        runAction={runAction}
        onClose={() => setVisible(false)}
      />
    </span>
  );
}

function CompleteModal({visible, acting, runAction, onClose}) {
  const [form] = Form.useForm();
  useEffect(() => {
    if (visible) form.resetFields();
  }, [visible, form]);
  return (
    <Modal
      visible={visible}
      title="完成工单"
      confirmLoading={acting}
      destroyOnClose
      onCancel={() => {onClose(); form.resetFields();}}
      onOk={() => {
        form.validateFields().then(values => {
          runAction('complete', {
            process_result: values.process_result,
            work_hours: values.work_hours ?? null,
            interrupt_hours: values.interrupt_hours ?? null,
          }).then(() => {
            message.success('工单已完成');
            onClose();
            form.resetFields();
          }).catch(() => {});
        }).catch(() => {});
      }}
    >
      <p>完成后工单记为"已完成"，记录实际完成时间与完成账号；之后可关闭工单归档。</p>
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item
          name="process_result"
          label="处理结果"
          rules={[{required: true, message: '请填写处理结果'}]}
        >
          <TextArea rows={4} maxLength={2000} placeholder="请填写处理结果（必填）"/>
        </Form.Item>
        <Form.Item name="work_hours" label="工时">
          <InputNumber min={0} max={999} step={0.5} style={{width: '100%'}} placeholder="小时（选填）"/>
        </Form.Item>
        <Form.Item name="interrupt_hours" label="系统中断时间">
          <InputNumber min={0} max={999} step={0.5} style={{width: '100%'}} placeholder="小时（选填）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

function CancelButton({order, runAction, acting}) {
  const [visible, setVisible] = useState(false);
  const [reason, setReason] = useState('');
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={WO_PERM.DEL} danger onClick={() => setVisible(true)}>取消工单</AuthButton>
      <Modal
        visible={visible}
        title="取消确认"
        confirmLoading={acting}
        onCancel={() => setVisible(false)}
        onOk={() => {
          if (!reason.trim()) {
            message.warning('请填写取消原因');
            return;
          }
          runAction('cancel', {cancel_reason: reason.trim()})
            .then(() => {
              message.success('工单已取消');
              setVisible(false);
            })
            .catch(() => {});
        }}
      >
        <p>取消为受控操作（非物理删除），已取消工单不参与系统健康状态计算。确定取消工单「{order.work_no}」吗？</p>
        <Input.TextArea
          rows={3}
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="请填写取消原因（必填）"
        />
      </Modal>
    </span>
  );
}

/* ========== 处理记录时间线 ========== */

export function HandlingTimeline({records, fetching, editable, onAdd, onCorrect}) {
  return (
    <div>
      {editable && onAdd && (
        <div style={{marginBottom: 12}}>
          <AddHandlingButton onAdd={onAdd}/>
        </div>
      )}
      <Spin spinning={fetching}>
        {records.length ? (
          <Timeline style={{marginTop: 8}}>
            {records.map(record => (
              <Timeline.Item key={record.id}>
                <div>
                  <b>{record.handled_at}</b>
                  <span style={{marginLeft: 8}}>处理人：{record.handler_name}</span>
                  {record.result && <Tag style={{marginLeft: 8}}>{record.result}</Tag>}
                  {record.work_hours !== null && record.work_hours !== undefined && (
                    <Tag style={{marginLeft: 8}}>工时 {record.work_hours}h</Tag>
                  )}
                  {editable && onCorrect && (
                    <CorrectButton record={record} onCorrect={onCorrect}/>
                  )}
                </div>
                <div style={{marginTop: 4}}>{record.content}</div>
                {(record.corrections || []).map((c, i) => (
                  <div key={i} style={{color: '#999', marginTop: 4, fontSize: 12}}>
                    更正记录：{c.at} 由 {c.by} 更正（原因：{c.reason}）
                  </div>
                ))}
              </Timeline.Item>
            ))}
          </Timeline>
        ) : (
          <Empty description="暂无处理记录" image={Empty.PRESENTED_IMAGE_SIMPLE}/>
        )}
      </Spin>
    </div>
  );
}

function AddHandlingButton({onAdd}) {
  const [visible, setVisible] = useState(false);
  return (
    <span>
      <AuthButton
        auth={WO_PERM.EXECUTE}
        type="primary"
        icon={<PlusOutlined/>}
        onClick={() => setVisible(true)}
      >
        添加处理记录
      </AuthButton>
      <HandlingModal visible={visible} onClose={() => setVisible(false)} onSubmit={onAdd}/>
    </span>
  );
}

function CorrectButton({record, onCorrect}) {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={WO_PERM.EDIT}
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => setVisible(true)}
      >
        更正
      </AuthButton>
      <HandlingModal
        visible={visible}
        record={record}
        onClose={() => setVisible(false)}
        onSubmit={onCorrect}
      />
    </span>
  );
}

export function HandlingModal({visible, record, onClose, onSubmit}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const isCorrect = !!record;
  useEffect(() => {
    if (visible) {
      form.resetFields();
      form.setFieldsValue({
        handled_at: isCorrect && record.handled_at
          ? moment(record.handled_at, 'YYYY-MM-DD HH:mm') : moment(),
        content: isCorrect ? record.content : undefined,
        result: isCorrect ? record.result : undefined,
        work_hours: isCorrect ? record.work_hours : undefined,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);
  return (
    <Modal
      visible={visible}
      title={isCorrect ? '更正处理记录' : '添加处理记录'}
      confirmLoading={loading}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          setLoading(true);
          const payload = {
            handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
            content: values.content,
            result: values.result || '',
            work_hours: values.work_hours ?? null,
          };
          const request = isCorrect
            ? onSubmit(record.id, {...payload, correction_reason: values.correction_reason})
            : onSubmit(payload);
          request.then(() => {
            message.success(isCorrect ? '处理记录已更正' : '处理记录已添加');
            setLoading(false);
            onClose();
          }).catch(() => setLoading(false));
        }).catch(() => {});
      }}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item
          name="handled_at"
          label="处理时间"
          rules={[{required: true, message: '请选择处理时间'}]}
        >
          <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item
          name="content"
          label="处理内容"
          rules={[{required: true, message: '请填写处理内容'}]}
        >
          <TextArea rows={3}/>
        </Form.Item>
        <Form.Item name="result" label="处理结果">
          <Input placeholder="如：已更换板卡 / 待观察（选填）"/>
        </Form.Item>
        <Form.Item name="work_hours" label="本次工时">
          <InputNumber min={0} max={999} step={0.5} style={{width: '100%'}} placeholder="小时（选填）"/>
        </Form.Item>
        {isCorrect && (
          <Form.Item
            name="correction_reason"
            label="更正原因"
            rules={[{required: true, message: '更正必须填写原因，原内容将留痕保存'}]}
          >
            <TextArea rows={2} placeholder="原内容、修改内容与更正原因将一并保存"/>
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

export {WO_PERM};

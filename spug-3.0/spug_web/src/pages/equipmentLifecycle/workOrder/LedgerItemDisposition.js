/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账异常明细处置组件（步骤 3.3）。
 * - DispositionTag：异常明细处置状态标签（由后端按来源关系动态计算）；
 * - ConvertActions：异常明细"转故障"/"转工单"操作（含重新处置原因）；
 * - 已处置异常不重复显示可用转单操作；处置目标可跳转。
 * 规则：一次操作只转故障或只转工单；先转故障后，维修工单应从故障生成。
 */
import React, { useState } from 'react';
import { Modal, Form, Input, Select, DatePicker, Tag, Button, message } from 'antd';
import { history } from 'libs';
import { AuthButton } from 'components';
import { http } from 'libs';
import WorkOrderForm from './WorkOrderForm';
import store from './store';
import {
  WO_PERM, DISPOSITION_TEXT, DISPOSITION_COLOR, LEDGER_TYPE_PATH, WORK_TYPE_OPTIONS,
} from './constants';

const {TextArea} = Input;
const API_PREFIX = '/api/equipment-lifecycle';

export function DispositionTag({item}) {
  const d = item.disposition;
  if (!item || item.result !== 'abnormal') return null;
  const status = d ? d.status : 'none';
  return (
    <Tag color={DISPOSITION_COLOR[status]}>{DISPOSITION_TEXT[status] || status}</Tag>
  );
}

export function DispositionTargets({item, onOpenWorkOrder}) {
  const d = item.disposition;
  if (!d) return null;
  const links = [];
  if (d.fault) {
    links.push(
      <Button
        key="fault"
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => {
          history.push(`/el/faults?detail=${d.fault.id}`);
        }}
      >
        {d.fault.fault_no}
      </Button>
    );
  }
  if (d.work_order && onOpenWorkOrder) {
    links.push(
      <Button
        key="wo"
        type="link"
        size="small"
        style={{padding: 0, marginLeft: links.length ? 8 : 0}}
        onClick={() => onOpenWorkOrder(d.work_order.id)}
      >
        {d.work_order.work_no}
      </Button>
    );
  }
  return links.length ? <span style={{marginLeft: 8}}>{links}</span> : null;
}

/**
 * 异常明细行内操作：未处置/目标已取消时可转故障或转工单；
 * 已转故障/已转工单的异常不再显示可用转单操作（重新处置由后端校验原因）。
 */
export function ConvertActions({ledger, item, onOpenWorkOrder, onConverted}) {
  const [convertFaultVisible, setConvertFaultVisible] = useState(false);
  const [convertWoVisible, setConvertWoVisible] = useState(false);
  const d = item.disposition;
  const convertible = !d || d.status === 'none' || d.status === 'target_cancelled';
  if (item.result !== 'abnormal') return null;
  if (!convertible) {
    return <DispositionTargets item={item} onOpenWorkOrder={onOpenWorkOrder}/>;
  }
  return (
    <span>
      <AuthButton
        auth={WO_PERM.LEDGER_HANDLE}
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => setConvertFaultVisible(true)}
      >
        转故障
      </AuthButton>
      <AuthButton
        auth={WO_PERM.LEDGER_HANDLE}
        type="link"
        size="small"
        style={{padding: 0, marginLeft: 8}}
        onClick={() => {
          store.formToken = 'li-' + Date.now().toString(36) + '-' +
            Math.random().toString(36).slice(2, 10);
          setConvertWoVisible(true);
        }}
      >
        转工单
      </AuthButton>
      <ConvertToFaultModal
        visible={convertFaultVisible}
        ledger={ledger}
        item={item}
        needReason={d && d.status === 'target_cancelled'}
        onClose={() => setConvertFaultVisible(false)}
        onConverted={onConverted}
      />
      <ConvertToWorkOrderModal
        visible={convertWoVisible}
        ledger={ledger}
        item={item}
        needReason={d && d.status === 'target_cancelled'}
        onClose={() => setConvertWoVisible(false)}
        onConverted={onConverted}
      />
    </span>
  );
}

function ConvertToFaultModal({visible, ledger, item, needReason, onClose, onConverted}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const submit = () => {
    form.validateFields().then(values => {
      setLoading(true);
      http.post(
        `${API_PREFIX}/ledgers/${ledger.id}/items/${item.id}/convert-to-fault/`,
        {
          occurred_at: values.occurred_at ? values.occurred_at.format('YYYY-MM-DD HH:mm') : '',
          discovery: values.discovery,
          level: values.level,
          impact_status: values.impact_status,
          phenomenon: values.phenomenon || '',
          re_dispose_reason: values.re_dispose_reason || '',
        })
        .then(() => {
          message.success('已生成故障，可跳转查看');
          setLoading(false);
          onClose();
          form.resetFields();
          onConverted && onConverted();
        })
        .catch(() => setLoading(false));
    }).catch(() => {});
  };
  return (
    <Modal
      visible={visible}
      title="异常转故障"
      confirmLoading={loading}
      onCancel={onClose}
      onOk={submit}
      destroyOnClose
    >
      <p style={{color: '#999', marginTop: 0}}>
        故障系统固定为明细所属系统「{item.system_name}（{item.system_code}）」；
        将带入台账类型、编号、检查项、位置、异常说明、实测值与现场处理内容。
      </p>
      <Form
        form={form}
        labelCol={{span: 6}}
        wrapperCol={{span: 16}}
        initialValues={{
          discovery: 'patrol',
          level: 'minor',
          impact_status: 'degraded',
          phenomenon: '',
        }}
      >
        <Form.Item name="occurred_at" label="发生时间">
          <DatePicker
            showTime={{format: 'HH:mm'}}
            format="YYYY-MM-DD HH:mm"
            style={{width: '100%'}}
            placeholder="默认取明细执行时间"
          />
        </Form.Item>
        <Form.Item name="discovery" label="发现方式">
          <Select>
            <Select.Option value="patrol">巡检发现</Select.Option>
            <Select.Option value="alarm">告警发现</Select.Option>
            <Select.Option value="report">人工报告</Select.Option>
            <Select.Option value="other">其他</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="level" label="故障级别">
          <Select>
            <Select.Option value="minor">一般</Select.Option>
            <Select.Option value="major">严重</Select.Option>
            <Select.Option value="critical">重大</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="impact_status" label="系统影响程度">
          <Select>
            <Select.Option value="degraded">降级</Select.Option>
            <Select.Option value="fault">故障</Select.Option>
            <Select.Option value="interrupted">中断</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="phenomenon" label="故障现象">
          <TextArea rows={3} maxLength={2000} placeholder="默认由异常说明等自动组装，可编辑"/>
        </Form.Item>
        {needReason && (
          <Form.Item
            name="re_dispose_reason"
            label="重新处置原因"
            rules={[{required: true, message: '该异常存在历史处置目标（已作废），必须填写重新处置原因'}]}
          >
            <TextArea rows={2} maxLength={200} placeholder="历史处置目标已作废，重新转故障必须说明原因"/>
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

function ConvertToWorkOrderModal({visible, ledger, item, needReason, onClose, onConverted}) {
  const [submitting, setSubmitting] = useState(false);
  const defaultRequirement = [
    item.abnormal_desc || '发现异常',
    _valueText(item),
    item.onsite_action ? `现场处理：${item.onsite_action}` : '',
  ].filter(Boolean).join('；');
  const initialValues = {
    title: `${item.item_name_snapshot || ''} 异常处理`,
    work_type: 'special_maintenance',
    priority: 'normal',
    system: item.system,
    affects_system_operation: false,
    work_location: '',
    work_requirement: defaultRequirement,
    re_dispose_reason: '',
  };
  const submit = (values) => {
    setSubmitting(true);
    const payload = store.buildFormPayload(values);
    if (values.re_dispose_reason) {
      payload.re_dispose_reason = values.re_dispose_reason;
    }
    return http.post(
      `${API_PREFIX}/ledgers/${ledger.id}/items/${item.id}/convert-to-work-order/`, payload)
      .then(() => {
        message.success('已生成工单，可跳转查看');
        onClose();
        onConverted && onConverted();
      })
      .finally(() => setSubmitting(false));
  };
  return (
    <WorkOrderForm
      visible={visible}
      onClose={onClose}
      title="异常转工单"
      initialValues={initialValues}
      onSubmit={submit}
      extraReason={needReason}
    />
  );
}

function _valueText(item) {
  if (item.input_type === 'number' && item.value_number !== null && item.value_number !== undefined) {
    return `实测值：${item.value_number}${item.unit || ''}`;
  }
  if (item.input_type === 'boolean' && item.value_bool !== null && item.value_bool !== undefined) {
    return `实测值：${item.value_bool ? '是' : '否'}`;
  }
  if (item.value_text) return `实测值：${item.value_text}`;
  return '';
}

export {LEDGER_TYPE_PATH, WORK_TYPE_OPTIONS};

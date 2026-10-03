/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账异常明细处置组件（2026-09-30 自 workOrder/LedgerItemDisposition.js 迁入
 * 并去除工单链路：故障维修工单已整体删除，处置只保留"转故障"）。
 * - DispositionTag：异常明细处置状态标签（由后端按来源故障关系动态计算）；
 * - ConvertActions：异常明细"转故障"操作（含重新处置原因）；
 * - 已转故障的异常不再显示可用转换操作；处置目标可跳转。
 */
import React, { useState } from 'react';
import { Modal, Form, Input, Select, DatePicker, Tag, Button, message } from 'antd';
import { history } from 'libs';
import { AuthButton } from 'components';
import { http } from 'libs';

const {TextArea} = Input;
const API_PREFIX = '/api/equipment-lifecycle';

const DISPOSITION_TEXT = {
  none: '未处置',
  converted_fault: '已转故障',
  target_cancelled: '处置目标已撤销登记',
};

const DISPOSITION_COLOR = {
  none: 'default',
  converted_fault: 'red',
  target_cancelled: 'orange',
};

const LEDGER_HANDLE = 'equipment_lifecycle.ledger.handle_exception';

export function DispositionTag({item}) {
  const d = item.disposition;
  if (!item || item.result !== 'abnormal') return null;
  const status = d ? d.status : 'none';
  return (
    <Tag color={DISPOSITION_COLOR[status]}>{DISPOSITION_TEXT[status] || status}</Tag>
  );
}

export function DispositionTargets({item}) {
  const d = item.disposition;
  if (!d || !d.fault) return null;
  return (
    <span style={{marginLeft: 8}}>
      <Button
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => {
          history.push(`/el/faults?detail=${d.fault.id}`);
        }}
      >
        {d.fault.fault_no}
      </Button>
    </span>
  );
}

/**
 * 异常明细行内操作：未处置/目标已取消时可转故障；
 * 已转故障的异常不再显示可用转换操作（重新处置由后端校验原因）。
 */
export function ConvertActions({ledger, item, onConverted}) {
  const [convertFaultVisible, setConvertFaultVisible] = useState(false);
  const d = item.disposition;
  const convertible = !d || d.status === 'none' || d.status === 'target_cancelled';
  if (item.result !== 'abnormal') return null;
  if (!convertible) {
    return <DispositionTargets item={item}/>;
  }
  return (
    <span>
      <AuthButton
        auth={LEDGER_HANDLE}
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => setConvertFaultVisible(true)}
      >
        转故障
      </AuthButton>
      <ConvertToFaultModal
        visible={convertFaultVisible}
        ledger={ledger}
        item={item}
        needReason={d && d.status === 'target_cancelled'}
        onClose={() => setConvertFaultVisible(false)}
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
        故障系统固定为明细所属系统「{item.system_name}」；
        将带入台账类型、编号、检查项、位置、异常说明、实测值与现场处理内容。
      </p>
      <Form
        form={form}
        labelCol={{span: 6}}
        wrapperCol={{span: 16}}
        initialValues={{
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
            rules={[{required: true, message: '该异常存在历史处置目标（已撤销登记），必须填写重新处置原因'}]}
          >
            <TextArea rows={2} maxLength={200} placeholder="历史处置目标已撤销登记，重新转故障必须说明原因"/>
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

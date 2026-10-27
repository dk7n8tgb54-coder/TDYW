import React, {useEffect, useState} from 'react';
import {DatePicker, Form, Input, Modal, Radio, message} from 'antd';
import moment from 'moment';
import {http} from 'libs';

// 规律调查生命周期动作弹窗（2026-10-26）：调查状态改为三态生命周期后，
// 「结束调查 / 取消调查」从列表行内联状态下拉改为独立动作弹窗，分别对接
// POST /investigations/<pk>/finish/（result 必填三选一、conclusion 必填非空、
// end_at 可选缺省当前时间）与 POST /investigations/<pk>/cancel/（cancel_reason
// 必填非空）。成功提示 → 关闭 → 宿主刷新回调；失败依赖 http.js 拦截器统一
// 提示，此处不重复提示、不乐观更新。

const RESULT_OPTIONS = [
  {value: 'found', label: '发现规律'},
  {value: 'not_found', label: '未发现规律'},
  {value: 'undetermined', label: '暂无法确认'},
];

export function FinishInvestigationModal({record, onClose, onSaved}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  // 打开时重置表单（destroyOnClose 关闭后销毁，重开不残留上次输入；
  // end_at 缺省当前时间，可清空交由后端缺省补当前时间）
  useEffect(() => {
    if (record) form.resetFields();
  }, [record, form]);

  function submit() {
    if (!record || loading) return;
    setLoading(true);
    form.validateFields().then(values => {
      const payload = {result: values.result, conclusion: values.conclusion};
      if (values.end_at && values.end_at.format) {
        payload.end_at = values.end_at.format('YYYY-MM-DD HH:mm:ss');
      }
      return http.post(`/api/interference/investigations/${record.id}/finish/`, payload);
    }).then(() => {
      message.success('调查已结束');
      onClose();
      if (onSaved) return onSaved();
    }).catch(() => {}).finally(() => setLoading(false));
  }

  return <Modal visible={!!record} title="结束调查" onCancel={onClose} maskClosable={false}
    destroyOnClose confirmLoading={loading} onOk={submit}>
    <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}} initialValues={{end_at: moment()}}>
      <Form.Item name="result" label="调查结果" rules={[{required: true, message: '请选择调查结果'}]}>
        <Radio.Group>
          {RESULT_OPTIONS.map(option => <Radio key={option.value} value={option.value}>{option.label}</Radio>)}
        </Radio.Group>
      </Form.Item>
      <Form.Item name="conclusion" label="调查结论" rules={[{required: true, message: '请填写调查结论'}]}>
        <Input.TextArea rows={4} placeholder="请填写调查结论"/>
      </Form.Item>
      <Form.Item name="end_at" label="结束时间">
        <DatePicker showTime style={{width: '100%'}} allowClear/>
      </Form.Item>
    </Form>
  </Modal>;
}

export function CancelInvestigationModal({record, onClose, onSaved}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (record) form.resetFields();
  }, [record, form]);

  function submit() {
    if (!record || loading) return;
    setLoading(true);
    form.validateFields().then(values =>
      http.post(`/api/interference/investigations/${record.id}/cancel/`, {cancel_reason: values.cancel_reason})
    ).then(() => {
      message.success('调查已取消');
      onClose();
      if (onSaved) return onSaved();
    }).catch(() => {}).finally(() => setLoading(false));
  }

  return <Modal visible={!!record} title="取消调查" onCancel={onClose} maskClosable={false}
    destroyOnClose confirmLoading={loading} onOk={submit}>
    <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
      <Form.Item name="cancel_reason" label="取消原因" rules={[{required: true, message: '请填写取消原因'}]}>
        <Input.TextArea rows={4} placeholder="请填写取消原因"/>
      </Form.Item>
    </Form>
  </Modal>;
}

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 值班巡检异常明细 → 故障/工单转换弹窗（今日巡检改造）。
 * 规则：
 * - 巡检单不关联系统：转换时必须显式选择目标系统（必填，后端复核），
 *   不能由设备名称推断系统；
 * - 默认"部件故障但不影响系统运行"；明确开启影响运行时才选择影响程度；
 * - 重复转换由后端拒绝或要求重新处置原因。
 */
import React, {useState, useEffect} from 'react';
import {Modal, Form, Select, Input, Switch, Alert} from 'antd';
import {http} from 'libs';
import store from './store';
import {FAULT_IMPACT_OPTIONS} from '../constants';
import {API_PREFIX} from './constants';

const {TextArea} = Input;

function useSystems() {
  useEffect(() => {
    if (!store.systems.length) {
      store.fetchSystems().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return store.systems;
}

export function ConvertToFaultModal({visible, record, onClose}) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [affects, setAffects] = useState(false);
  const systems = useSystems();
  useEffect(() => {
    if (visible) {
      setAffects(false);
      form.resetFields();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  function handleOk() {
    form.validateFields().then(values => {
      setSubmitting(true);
      const payload = {...values};
      if (!values.affects_system_operation) {
        delete payload.impact_status;
      }
      store.convertToFault(record.sheet, record.id, payload)
        .then(() => onClose())
        .catch(() => {})
        .finally(() => setSubmitting(false));
    }).catch(() => {});
  }

  return (
    <Modal
      visible={visible}
      title={`异常转故障 - ${record ? record.device_name : ''}：${record ? record.item_name : ''}`}
      width={560}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={handleOk}
      destroyOnClose
    >
      <Alert
        style={{marginBottom: 16}}
        type="info"
        showIcon
        message="巡检单不关联系统，请选择本次故障所属系统（设备名称不能推断系统）"
      />
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item
          name="system"
          label="故障系统"
          rules={[{required: true, message: '请选择系统'}]}
          extra="一张故障单只关联一个系统"
        >
          <Select
            showSearch
            optionFilterProp="children"
            placeholder="请选择系统"
          >
            {systems.map(s => (
              <Select.Option value={s.id} key={s.id}>
                {s.name}
                <span style={{color: '#bbb', marginLeft: 6}}>{s.install_location}</span>
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="affects_system_operation"
          label="影响系统运行"
          valuePropName="checked"
          initialValue={false}
          extra="默认关闭：部件故障/离线维修不影响系统对外服务；开启后按影响程度参与系统健康状态计算"
        >
          <Switch checkedChildren="影响" unCheckedChildren="不影响"
                  onChange={v => setAffects(v)}/>
        </Form.Item>
        {affects && (
          <Form.Item
            name="impact_status"
            label="系统影响程度"
            preserve={false}
            rules={[{required: true, message: '请选择系统影响程度'}]}
          >
            <Select placeholder="降级 / 故障 / 中断">
              {FAULT_IMPACT_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        )}
        <Form.Item name="phenomenon" label="故障现象">
          <TextArea rows={3} placeholder="默认带入巡检异常内容（可修改）"/>
        </Form.Item>
        <Form.Item name="re_dispose_reason" label="重新处置原因">
          <Input maxLength={200} placeholder="此前已转故障被作废时必填（选填）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

export function ConvertToWorkOrderModal({visible, record, onClose}) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const systems = useSystems();
  const clientTokenRef = React.useRef('');
  useEffect(() => {
    if (visible) {
      clientTokenRef.current = `ins-wo-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      form.resetFields();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  function handleOk() {
    form.validateFields().then(values => {
      setSubmitting(true);
      store.convertToWorkOrder(record.sheet, record.id,
        {...values, client_token: clientTokenRef.current})
        .then(() => onClose())
        .catch(() => {})
        .finally(() => setSubmitting(false));
    }).catch(() => {});
  }

  return (
    <Modal
      visible={visible}
      title={`异常转工单 - ${record ? record.device_name : ''}：${record ? record.item_name : ''}`}
      width={560}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={handleOk}
      destroyOnClose
    >
      <Alert
        style={{marginBottom: 16}}
        type="info"
        showIcon
        message="巡检单不关联系统，请选择本次作业所属系统（设备名称不能推断系统）"
      />
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item
          name="system"
          label="作业系统"
          rules={[{required: true, message: '请选择系统'}]}
          extra="一张工单只关联一个系统"
        >
          <Select
            showSearch
            optionFilterProp="children"
            placeholder="请选择系统"
          >
            {systems.map(s => (
              <Select.Option value={s.id} key={s.id}>
                {s.name}
                <span style={{color: '#bbb', marginLeft: 6}}>{s.install_location}</span>
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="affects_system_operation"
          label="作业期间影响系统运行"
          valuePropName="checked"
          initialValue={false}
          extra="默认关闭：拆下部件离线维修不影响系统对外服务；执行中且开启时系统才进入「维修中」"
        >
          <Switch checkedChildren="影响" unCheckedChildren="不影响"/>
        </Form.Item>
        <Form.Item name="work_requirement" label="作业要求">
          <TextArea rows={3} placeholder="默认带入巡检异常内容（可修改）"/>
        </Form.Item>
        <Form.Item name="re_dispose_reason" label="重新处置原因">
          <Input maxLength={200} placeholder="此前已转工单被作废时必填（选填）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

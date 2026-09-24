/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障新增/编辑弹窗（步骤 3.1，单系统简化）。
 * - 普通用户只需要选择一个"故障系统"（提交系统 ID，显示名称+编号+安装地点）；
 * - 不再提供主故障系统与受影响系统；一次实际工作涉及多个系统时分别建立故障；
 * - 可选引用配置组成项（非必填），选中后自动回填故障对象快照，可手动调整。
 */
import React, { useState, useEffect, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Select, Input, DatePicker, message } from 'antd';
import moment from 'moment';
import { http } from 'libs';
import store from './faultStore';
import {
  API_PREFIX, FAULT_IMPACT_OPTIONS, FAULT_LEVEL_OPTIONS, FAULT_DISCOVERY_OPTIONS,
} from './constants';

const {TextArea} = Input;

function SystemOptionLabel({system}) {
  if (!system) return null;
  return (
    <span>
      {system.name}
      <span style={{color: '#bbb', marginLeft: 6}}>{system.install_location}</span>
    </span>
  );
}

const FaultForm = observer(function FaultForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [components, setComponents] = useState([]);
  const mountedRef = useRef(true);
  const record = store.record;
  const isEdit = !!record.id;

  useEffect(() => {
    mountedRef.current = true;
    return () => {mountedRef.current = false;};
  }, []);

  useEffect(() => {
    if (!isEdit) return;
    setLoading(true);
    store.fetchDetailById(record.id)
      .then(detail => {
        if (!mountedRef.current) return;
        form.setFieldsValue({
          system: detail.system,
          impact_status: detail.impact_status,
          occurred_at: detail.occurred_at ? moment(detail.occurred_at, 'YYYY-MM-DD HH:mm') : null,
          discovery: detail.discovery,
          level: detail.level,
          phenomenon: detail.phenomenon,
          impact_scope: detail.impact_scope,
          fault_location: detail.fault_location,
          fault_object_name: detail.fault_object_name,
          fault_object_model: detail.fault_object_model,
          fault_object_sn: detail.fault_object_sn,
          fault_component: detail.fault_component || undefined,
          reason_analysis: detail.reason_analysis,
        });
        fetchComponents(detail.system);
      })
      .catch(() => {})
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function fetchComponents(systemId) {
    if (!systemId) {
      setComponents([]);
      return;
    }
    http.get(`${API_PREFIX}/systems/${systemId}/components/`)
      .then(res => {
        if (mountedRef.current) setComponents(res.data || []);
      })
      .catch(() => {});
  }

  function handleSystemChange(value) {
    form.setFieldsValue({fault_component: undefined});
    setComponents([]);
    fetchComponents(value);
  }

  function handleComponentChange(value) {
    if (!value) return;
    const comp = components.find(c => c.id === value);
    if (!comp) return;
    // 引用组成项时自动回填故障对象快照（可手动覆盖，后端保存快照文本）
    form.setFieldsValue({
      fault_object_name: form.getFieldValue('fault_object_name') || comp.name,
      fault_object_model: form.getFieldValue('fault_object_model') || comp.model_version,
      fault_object_sn: form.getFieldValue('fault_object_sn') || comp.asset_sn,
    });
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      const payload = {
        ...values,
        occurred_at: values.occurred_at ? values.occurred_at.format('YYYY-MM-DD HH:mm') : null,
      };
      setLoading(true);
      store.submitForm(payload)
        .then(() => {
          if (mountedRef.current) message.success(isEdit ? '故障已更新' : '故障已创建');
        })
        .catch(() => {})
        .finally(() => {
          if (mountedRef.current) setLoading(false);
        });
    }).catch(() => {});
  }

  return (
    <Modal
      visible={store.formVisible}
      title={isEdit ? '编辑故障' : '新增故障'}
      width={760}
      maskClosable={false}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item
          name="system"
          label="故障系统"
          rules={[{required: true, message: '请选择故障系统'}]}
          extra="一张故障单只关联一个系统；涉及多个系统时请分别建立故障"
        >
          <Select
            showSearch
            optionFilterProp="children"
            placeholder="请选择故障系统（显示名称、编号、安装地点）"
            allowClear
            onChange={v => handleSystemChange(v)}
          >
            {store.systems.map(s => (
              <Select.Option value={s.id} key={s.id}>
                <SystemOptionLabel system={s}/>
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="impact_status"
          label="系统影响程度"
          rules={[{required: true, message: '请选择系统影响程度'}]}
        >
          <Select placeholder="降级 / 故障 / 中断">
            {FAULT_IMPACT_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="occurred_at"
          label="故障发生时间"
          rules={[{required: true, message: '请选择故障发生时间'}]}
        >
          <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item
          name="discovery"
          label="发现方式"
          rules={[{required: true, message: '请选择故障发现方式'}]}
        >
          <Select placeholder="请选择发现方式">
            {FAULT_DISCOVERY_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="level"
          label="故障级别"
          rules={[{required: true, message: '请选择故障级别'}]}
        >
          <Select placeholder="请选择级别">
            {FAULT_LEVEL_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="phenomenon"
          label="故障现象"
          rules={[
            {required: true, message: '请填写故障现象'},
            {max: 2000, message: '长度不能超过 2000'},
          ]}
        >
          <TextArea rows={3} placeholder="描述观察到的故障现象"/>
        </Form.Item>
        <Form.Item name="impact_scope" label="影响范围">
          <TextArea rows={2} placeholder="受影响的业务或范围（选填）"/>
        </Form.Item>
        <Form.Item name="fault_location" label="故障位置">
          <Input placeholder="如 机房A 01柜（选填）"/>
        </Form.Item>
        <Form.Item name="fault_component" label="配置组成项" extra="可选：引用故障系统的配置组成项，不要求逐台建档">
          <Select allowClear placeholder="可选" onChange={handleComponentChange}>
            {components.map(c => (
              <Select.Option value={c.id} key={c.id}>
                {`${c.name}${c.model_version ? `（${c.model_version}）` : ''}`}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="fault_object_name" label="故障对象名称">
          <Input placeholder="具体故障对象名称（选填）"/>
        </Form.Item>
        <Form.Item name="fault_object_model" label="故障对象型号">
          <Input placeholder="型号或版本（选填）"/>
        </Form.Item>
        <Form.Item name="fault_object_sn" label="对象编号/序列号">
          <Input placeholder="资产编号或序列号（选填）"/>
        </Form.Item>
        <Form.Item name="reason_analysis" label="原因分析">
          <TextArea rows={2} placeholder="（选填，处置过程中可继续完善）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
});

export default FaultForm;

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障新增/编辑弹窗（步骤 3.1）。
 * - 系统选择器仅提交系统 ID（页面显示名称+编号+安装地点）；
 * - 已选主故障系统不能再选为受影响系统，受影响系统不可重复；
 * - 可选引用配置组成项（非必填），选中后自动回填故障对象快照，可手动调整。
 */
import React, { useState, useEffect, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Select, Input, DatePicker, Button, Divider, message } from 'antd';
import { MinusCircleOutlined } from '@ant-design/icons';
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
      <span style={{color: '#999', marginLeft: 6}}>{system.system_code}</span>
      <span style={{color: '#bbb', marginLeft: 6}}>{system.install_location}</span>
    </span>
  );
}

function renderSystemSelect(value, onChange, excludeIds, placeholder) {
  return (
    <Select
      showSearch
      optionFilterProp="children"
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      style={{width: '100%'}}
      allowClear
    >
      {store.systems.map(s => (
        <Select.Option value={s.id} key={s.id} disabled={excludeIds.has(s.id)}>
          <SystemOptionLabel system={s}/>
        </Select.Option>
      ))}
    </Select>
  );
}

const FaultForm = observer(function FaultForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [affected, setAffected] = useState([]);
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
          primary_system: detail.primary_system,
          primary_impact_status: detail.primary_impact_status,
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
        setAffected((detail.affected_systems || []).map(row => ({
          system_id: row.system,
          impact_status: row.impact_status,
        })));
        fetchComponents(detail.primary_system);
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

  function handlePrimarySystemChange(value) {
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

  function addAffected() {
    setAffected(prev => [...prev, {system_id: undefined, impact_status: 'fault'}]);
  }

  function removeAffected(index) {
    setAffected(prev => prev.filter((_, i) => i !== index));
  }

  function changeAffected(index, key, value) {
    setAffected(prev => prev.map((row, i) => (
      i === index ? {...row, [key]: value} : row
    )));
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      for (const row of affected) {
        if (!row.system_id || !row.impact_status) {
          message.warning('请完善受影响系统的选择与影响状态');
          return;
        }
      }
      const payload = {
        ...values,
        occurred_at: values.occurred_at ? values.occurred_at.format('YYYY-MM-DD HH:mm') : null,
        affected_systems: affected.map(row => ({
          system_id: row.system_id,
          impact_status: row.impact_status,
        })),
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

  const selectedAffectedIds = new Set(affected.map(row => row.system_id).filter(Boolean));

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
          name="primary_system"
          label="主故障系统"
          rules={[{required: true, message: '请选择主故障系统'}]}
        >
          <Select
            showSearch
            optionFilterProp="children"
            placeholder="请选择主故障系统（显示名称、编号、安装地点）"
            allowClear
            onChange={v => handlePrimarySystemChange(v)}
          >
            {store.systems.map(s => (
              <Select.Option value={s.id} key={s.id} disabled={selectedAffectedIds.has(s.id)}>
                <SystemOptionLabel system={s}/>
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="primary_impact_status"
          label="主系统影响状态"
          rules={[{required: true, message: '请选择主故障系统影响状态'}]}
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
        <Form.Item name="fault_location" label="故障位置/巡检点">
          <Input placeholder="如 机房A 01柜（选填）"/>
        </Form.Item>
        <Form.Item name="fault_component" label="配置组成项" extra="可选：引用主故障系统的配置组成项，不要求逐台建档">
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
        <Divider orientation="left" plain>受影响系统（可选）</Divider>
        {affected.map((row, index) => (
          <div key={index} style={{display: 'flex', alignItems: 'center', marginBottom: 8}}>
            <div style={{flex: 1, marginRight: 8}}>
              {renderSystemSelect(
                row.system_id,
                v => changeAffected(index, 'system_id', v),
                selectedAffectedIds,
                '请选择受影响系统',
              )}
            </div>
            <Select
              value={row.impact_status}
              onChange={v => changeAffected(index, 'impact_status', v)}
              style={{width: 120, marginRight: 8}}
            >
              {FAULT_IMPACT_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
              ))}
            </Select>
            <MinusCircleOutlined onClick={() => removeAffected(index)}/>
          </div>
        ))}
        <Button type="dashed" block onClick={addAffected} style={{marginBottom: 16}}>
          添加受影响系统
        </Button>
        <Form.Item name="reason_analysis" label="原因分析">
          <TextArea rows={2} placeholder="（选填，处置过程中可继续完善）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
});

export default FaultForm;

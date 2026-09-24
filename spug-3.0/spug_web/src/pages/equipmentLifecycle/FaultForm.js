/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障新增/编辑弹窗（步骤 3.1，单系统简化）。
 * - 普通用户只需要选择一个"故障系统"（提交系统 ID，显示名称+编号+安装地点）；
 * - 不再提供主故障系统与受影响系统；一次实际工作涉及多个系统时分别建立故障；
 * - 首报表单精简（2026-09）：只保留 故障系统/影响系统运行(+程度)/发生时间/
 *   故障部位/设备(选填)/故障现象；发现方式缺省"人工报告"、故障级别缺省
 *   "一般"由后端写入，不再出现在表单；
 * - 历史设备字段（影响范围/故障位置/对象型号/序列号）仅详情展示：编辑提交
 *   不携带，后端保留原值；原因分析仅在编辑（处置阶段）可填；
 * - 默认"部件故障但不影响系统运行"：只有明确开启"影响系统运行"时才需要
 *   选择影响程度（降级/故障/中断），并参与系统健康状态计算。
 */
import React, { useState, useEffect, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Select, Input, DatePicker, Switch, message } from 'antd';
import moment from 'moment';
import store from './faultStore';
import { API_PREFIX, FAULT_IMPACT_OPTIONS } from './constants';

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

function applyDetailToForm(form, detail) {
  // 仅回填表单仍管理的精简字段；discovery/level 与历史设备字段不进表单，
  // 编辑提交不携带这些键，后端保留原值（不静默清空历史数据）
  form.setFieldsValue({
    system: detail.system,
    affects_system_operation: !!detail.affects_system_operation,
    impact_status: detail.impact_status || undefined,
    occurred_at: detail.occurred_at ? moment(detail.occurred_at, 'YYYY-MM-DD HH:mm') : null,
    fault_object_name: detail.fault_object_name,
    phenomenon: detail.phenomenon,
    reason_analysis: detail.reason_analysis,
  });
}

function SystemImpactFields({systems}) {
  return (
    <>
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
        >
          {systems.map(s => (
            <Select.Option value={s.id} key={s.id}>
              <SystemOptionLabel system={s}/>
            </Select.Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item
        name="affects_system_operation"
        label="影响系统运行"
        valuePropName="checked"
        extra="默认关闭：部件故障、离线维修不影响系统对外服务；开启后按影响程度参与系统健康状态计算"
      >
        <Switch checkedChildren="影响" unCheckedChildren="不影响"/>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={
        (prev, cur) => prev.affects_system_operation !== cur.affects_system_operation
      }>
        {({getFieldValue}) => getFieldValue('affects_system_operation') ? (
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
        ) : null}
      </Form.Item>
    </>
  );
}

function OccurrenceFields() {
  return (
    <>
      <Form.Item
        name="occurred_at"
        label="故障发生时间"
        rules={[{required: true, message: '请选择故障发生时间'}]}
      >
        <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
      </Form.Item>
      <Form.Item
        name="phenomenon"
        label="故障现象"
        rules={[
          {required: true, message: '请填写故障现象'},
          {max: 2000, message: '长度不能超过 2000'},
        ]}
      >
        <TextArea rows={3} placeholder="描述观察到的故障现象，必要时可补充影响范围"/>
      </Form.Item>
    </>
  );
}

function FaultObjectFields({isEdit}) {
  return (
    <>
      <Form.Item name="fault_object_name" label="故障部位/设备">
        <Input placeholder="故障的部位或设备，如 信道机 / 天馈系统（选填）"/>
      </Form.Item>
      {/* 原因分析不放在首报（新增）表单，保留处置阶段（编辑）填写 */}
      {isEdit && (
        <Form.Item name="reason_analysis" label="原因分析">
          <TextArea rows={2} placeholder="（选填，处置过程中可继续完善）"/>
        </Form.Item>
      )}
    </>
  );
}

const FaultForm = observer(function FaultForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
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
        applyDetailToForm(form, detail);
      })
      .catch(() => {})
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      <Form
        form={form}
        labelCol={{span: 6}}
        wrapperCol={{span: 16}}
        initialValues={{affects_system_operation: false}}
      >
        <SystemImpactFields systems={store.systems}/>
        <OccurrenceFields/>
        <FaultObjectFields isEdit={isEdit}/>
      </Form>
    </Modal>
  );
});

export default FaultForm;

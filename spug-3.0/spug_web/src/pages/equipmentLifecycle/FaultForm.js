/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障新增/编辑弹窗（步骤 3.1，单系统简化）。
 * - 普通用户只需要选择一个"故障系统"（提交系统 ID，显示名称+安装地点；
 * - 不再提供主故障系统与受影响系统；一次实际工作涉及多个系统时分别建立故障；
 * - 首报表单精简（2026-09）：只保留 故障系统/影响系统运行(+程度)/发生时间/
 *   故障部位/设备(选填)/故障现象；发现方式/级别字段已删除（2026-09-29），
 *   影响范围/故障位置/处置负责人同步退役，均不再出现在表单与详情；
 * - 故障登记人（2026-09）：手动输入的登记人姓名（与今日巡检值班人员同款
 *   输入：输入姓名后回车确认，可多个），实际添加这条故障记录的人，不代表
 *   负责后续跟进或维修责任（姓名为文本快照，不关联用户账号）；仅新增时
 *   必填，不预填任何默认姓名；编辑不出现在表单，后端保留原登记人
 *   （created_by 登录账号仅审计）；
 * - 历史设备字段（对象名称/型号/序列号）编辑提交不携带时后端保留原值；
 *   初步判断区块（2026-10）：新增表单提供非必填"初步原因分析"（紧随故障现象
 *   之后，原因未知可留空正常创建）；编辑保留"原因分析"入口，详情页亦可
 *   直接补充/修改；
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
          placeholder="请选择故障系统（显示名称、安装地点）"
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
      <Form.Item name="fault_object_name" label="故障部位/设备">
        <Input placeholder="故障的部位或设备，如 信道机 / 天馈系统（选填）"/>
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
    </>
  );
}

// 故障登记人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），只表示
// 实际添加这条故障记录的人，不代表负责后续跟进、不承担维修责任；
// 与登录账号审计字段独立；必填、不预填默认姓名。
// 仅新增可填，编辑不渲染（后端保留原登记人）
function RegistrarFields({isEdit}) {
  if (isEdit) return null;
  return (
    <Form.Item
      name="registrar_names"
      label="故障登记人"
      rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
    >
      {/* open=false：仅手输姓名（回车/失焦添加），与今日巡检值班人员输入一致 */}
      <Select
        mode="tags"
        open={false}
        placeholder="输入姓名后回车确认（可多个）"
      />
    </Form.Item>
  );
}

// 初步判断区块（2026-10）：仅新增表单渲染，紧随"故障现象"之后。
// 初步原因分析非必填：原因未知可留空正常创建（新增成功即进入处置中），
// 处置过程中可在详情页"补充原因分析"或编辑表单继续完善，结案时定为最终原因
function PreliminaryAnalysisField({isEdit}) {
  if (isEdit) return null;
  return (
    <>
      <div style={{
        fontWeight: 600, margin: '4px 0 16px',
        borderTop: '1px dashed #e8e8e8', paddingTop: 12,
      }}>
        初步判断
      </div>
      <Form.Item name="reason_analysis" label="初步原因分析">
        <TextArea
          rows={3}
          placeholder="已知时填写，暂时无法判断可留空，处置过程中可继续补充"
        />
      </Form.Item>
    </>
  );
}

// 编辑（处置阶段）保留原因分析入口；详情页同样可直接补充/修改（FaultDetail）
function ReasonAnalysisField({isEdit}) {
  if (!isEdit) return null;
  return (
    <Form.Item name="reason_analysis" label="原因分析">
      <TextArea rows={2} placeholder="（选填，处置过程中可继续完善，结案时可修改为最终原因）"/>
    </Form.Item>
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
        // 标签数组以顿号拼接为登记人姓名文本（多人）
        registrar_name: (values.registrar_names || []).join('、'),
        // 初步原因分析（2026-10）：始终显式提交，未填写提交空串（非必填，
        // 原因未知可留空正常创建；后端保存后故障进入处置中）
        reason_analysis: values.reason_analysis || '',
      };
      delete payload.registrar_names;
      if (isEdit) {
        // 登记人仅新增可填：编辑不提交该键，后端保留原登记人
        delete payload.registrar_name;
      }
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
        {/* 初步判断区块（含初步原因分析）位于故障现象之后、故障登记人之前；
            编辑模式两处 reason_analysis 字段互斥渲染（Preliminary 为空） */}
        <PreliminaryAnalysisField isEdit={isEdit}/>
        <RegistrarFields isEdit={isEdit}/>
        <ReasonAnalysisField isEdit={isEdit}/>
      </Form>
    </Modal>
  );
});

export default FaultForm;

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 工单新增/编辑表单（Modal，单系统简化 + 单账号协同流程 + 工单类型收敛）。
 * - 普通用户只需要选择一个"作业系统"（提交 ID，页面显示名称）；
 * - 提供"作业期间是否影响系统运行"直观选择（执行中且为真才进入"维修中"）；
 * - 顶层工单类型只显示故障维修/专项维护（2026-09 类型收敛）：选择专项维护后
 *   显示"维护分类"（默认一般维护），选择故障维修时隐藏；技术改造请在
 *   系统升级管理中登记，不保留看似可选但实际不可用的空选项；
 * - 不再要求负责人/参与人；创建成功后工单即为"执行中"；
 * - 编辑仅限执行中工单（后端强制校验，前端同步控制入口）；
 * - 支持故障生成工单/台账转工单的预填场景（initialValues 覆盖）。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Form, Modal, Input, Select, DatePicker, Switch } from 'antd';
import store from './store';
import {
  WORK_TYPE_CREATION_OPTIONS, WORK_TYPE_HINT, RETIRED_WORK_TYPE_TEXT,
  MAINTENANCE_SUBTYPE_DEFAULT, MAINTENANCE_SUBTYPE_OPTIONS, PRIORITY_OPTIONS,
} from './constants';

const {TextArea} = Input;
const {Option} = Select;

const formLayout = {labelCol: {span: 6}, wrapperCol: {span: 16}};

function applyRecordToForm(form, record) {
  form.setFieldsValue({
    title: record.title,
    work_type: record.work_type,
    maintenance_subtype: record.maintenance_subtype || MAINTENANCE_SUBTYPE_DEFAULT,
    priority: record.priority,
    system: record.system,
    affects_system_operation: !!record.affects_system_operation,
    work_location: record.work_location,
    work_object_desc: record.work_object_desc,
    work_requirement: record.work_requirement,
    work_steps: record.work_steps,
    material_note: record.material_note,
  });
}

/** 工单类型 + 维护分类（类型收敛交互：专项维护才显示维护分类）。 */
function WorkTypeFields() {
  const form = Form.useFormInstance();
  return (
    <Form.Item noStyle shouldUpdate={(prev, cur) => prev.work_type !== cur.work_type}>
      {({getFieldValue}) => {
        const currentType = getFieldValue('work_type');
        return (
          <>
            <Form.Item
              name="work_type"
              label="工单类型"
              rules={[{required: true, message: '请选择工单类型'}]}
              extra={WORK_TYPE_HINT}
            >
              <Select
                placeholder="请选择工单类型"
                onChange={value => form.setFieldsValue({
                  maintenance_subtype: value === 'special_maintenance'
                    ? MAINTENANCE_SUBTYPE_DEFAULT : undefined,
                })}
              >
                {WORK_TYPE_CREATION_OPTIONS.map(item => (
                  <Option value={item.value} key={item.value}>{item.label}</Option>
                ))}
                {/* 编辑历史工单时回显已下线类型：仅禁用展示当前值，不可再提交 */}
                {RETIRED_WORK_TYPE_TEXT[currentType] && (
                  <Option value={currentType} disabled>
                    {RETIRED_WORK_TYPE_TEXT[currentType]}（已下线，请改选）
                  </Option>
                )}
              </Select>
            </Form.Item>
            {currentType === 'special_maintenance' && (
              <Form.Item
                name="maintenance_subtype"
                label="维护分类"
                extra="配置变更仅作为维护分类记录，不直接修改系统档案"
                rules={[{required: true, message: '请选择维护分类'}]}
              >
                <Select placeholder="请选择维护分类">
                  {MAINTENANCE_SUBTYPE_OPTIONS.map(item => (
                    <Option value={item.value} key={item.value}>{item.label}</Option>
                  ))}
                </Select>
              </Form.Item>
            )}
          </>
        );
      }}
    </Form.Item>
  );
}

function OrderFormFields({systems, extraReason}) {
  return (
    <>
      <Form.Item
        name="title"
        label="工单标题"
        rules={[{required: true, message: '请输入工单标题'}]}
      >
        <Input maxLength={100} placeholder="请输入工单标题"/>
      </Form.Item>
      <WorkTypeFields/>
      <Form.Item name="priority" label="优先级">
        <Select>
          {PRIORITY_OPTIONS.map(item => (
            <Option value={item.value} key={item.value}>{item.label}</Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item
        name="system"
        label="作业系统"
        rules={[{required: true, message: '请选择作业系统'}]}
        extra="一张工单只关联一个系统；涉及多个系统时请分别建立工单"
      >
        <Select
          showSearch
          optionFilterProp="children"
          placeholder="请选择作业系统"
          allowClear
        >
          {systems.map(s => (
            <Option value={s.id} key={s.id}>
              {s.name}
            </Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item
        name="affects_system_operation"
        label="作业期间影响系统运行"
        valuePropName="checked"
        extra="默认关闭：拆下部件离线维修不影响系统对外服务；执行中且开启时系统才进入「维修中」"
      >
        <Switch checkedChildren="影响" unCheckedChildren="不影响"/>
      </Form.Item>
      <Form.Item name="work_location" label="作业位置">
        <Input maxLength={200} placeholder="如：机房A列01柜（选填）"/>
      </Form.Item>
      <Form.Item name="work_object_desc" label="作业对象描述">
        <TextArea rows={2} maxLength={1000} placeholder="具体作业对象描述（选填）"/>
      </Form.Item>
      <Form.Item
        name="planned_range"
        label="计划时间"
        rules={[{required: false}]}
      >
        <DatePicker.RangePicker
          showTime={{format: 'HH:mm'}}
          format="YYYY-MM-DD HH:mm"
          style={{width: '100%'}}
        />
      </Form.Item>
      <Form.Item name="work_requirement" label="作业要求">
        <TextArea rows={3} maxLength={2000} placeholder="作业要求（选填）"/>
      </Form.Item>
      <Form.Item name="work_steps" label="作业步骤">
        <TextArea rows={3} maxLength={2000} placeholder="作业步骤（选填）"/>
      </Form.Item>
      <Form.Item
        name="material_note"
        label="材料说明"
        extra="仅记录名称/型号/数量/单位/说明/外部库存编号；不含库存管理"
      >
        <TextArea rows={2} maxLength={500} placeholder="材料说明（选填）"/>
      </Form.Item>
      {extraReason && (
        <Form.Item
          name="re_dispose_reason"
          label="重新处置原因"
          rules={[{required: true, message: '该异常存在历史处置目标（已作废），必须填写重新处置原因'}]}
        >
          <TextArea rows={2} maxLength={200} placeholder="历史处置目标已作废，重新转单必须说明原因"/>
        </Form.Item>
      )}
    </>
  );
}

function WorkOrderForm({visible, onClose, isEdit = false, initialValues = null, onSubmit = null, title = null, extraReason = false}) {
  const [form] = Form.useForm();
  const submitting = store.isSubmitting;

  useEffect(() => {
    if (visible) {
      form.resetFields();
      if (isEdit && store.record && store.record.id) {
        applyRecordToForm(form, store.record);
      } else if (initialValues) {
        form.setFieldsValue(initialValues);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const handleOk = () => {
    form.validateFields().then(values => {
      const request = onSubmit ? onSubmit(values) : store.submitForm(values);
      request.then(() => {
        onClose();
      }).catch(() => {});
    }).catch(() => {});
  };

  return (
    <Modal
      visible={visible}
      title={title || (isEdit ? '编辑工单' : '新增工单')}
      width={680}
      confirmLoading={submitting}
      onCancel={onClose}
      onOk={handleOk}
      destroyOnClose
    >
      <Form form={form} {...formLayout}
            initialValues={{priority: 'normal', affects_system_operation: false,
                            maintenance_subtype: MAINTENANCE_SUBTYPE_DEFAULT}}>
        <OrderFormFields systems={store.systems} extraReason={extraReason}/>
      </Form>
    </Modal>
  );
}

// observer：表单读取 store.systems / store.isSubmitting，候选项异步返回后需触发重渲染
export default observer(WorkOrderForm);

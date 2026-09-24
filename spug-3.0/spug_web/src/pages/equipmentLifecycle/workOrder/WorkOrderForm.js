/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 工单新增/编辑表单（Modal，单系统简化）。
 * - 普通用户只需要选择一个"作业系统"（提交 ID，页面显示名称）；
 * - 提供"作业期间是否影响系统运行"直观选择（执行中且为真才进入"维修中"）；
 * - 编辑仅限待派发工单（后端强制校验，前端同步隐藏入口）；
 * - 支持故障生成工单/台账转工单的预填场景（initialValues 覆盖）。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Form, Modal, Input, Select, DatePicker, Switch } from 'antd';
import store from './store';
import { WORK_TYPE_OPTIONS, PRIORITY_OPTIONS } from './constants';

const {TextArea} = Input;
const {Option} = Select;

const formLayout = {labelCol: {span: 6}, wrapperCol: {span: 16}};

function WorkOrderForm({visible, onClose, isEdit = false, initialValues = null, onSubmit = null, title = null, extraReason = false}) {
  const [form] = Form.useForm();
  const submitting = onSubmit ? store.isSubmitting : store.isSubmitting;

  useEffect(() => {
    if (visible) {
      form.resetFields();
      if (isEdit && store.record && store.record.id) {
        const r = store.record;
        form.setFieldsValue({
          title: r.title,
          work_type: r.work_type,
          priority: r.priority,
          system: r.system,
          affects_system_operation: !!r.affects_system_operation,
          work_location: r.work_location,
          work_object_desc: r.work_object_desc,
          work_requirement: r.work_requirement,
          work_steps: r.work_steps,
          material_note: r.material_note,
        });
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
      <Form form={form} {...formLayout} initialValues={{priority: 'normal', affects_system_operation: false}}>
          <Form.Item
            name="title"
            label="工单标题"
            rules={[{required: true, message: '请输入工单标题'}]}
          >
            <Input maxLength={100} placeholder="请输入工单标题"/>
          </Form.Item>
          <Form.Item
            name="work_type"
            label="工单类型"
            rules={[{required: true, message: '请选择工单类型'}]}
          >
            <Select placeholder="请选择工单类型">
              {WORK_TYPE_OPTIONS.map(item => (
                <Option value={item.value} key={item.value}>{item.label}</Option>
              ))}
            </Select>
          </Form.Item>
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
              {store.systems.map(s => (
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
            extra="执行中的故障维修工单仅在影响运行时使系统进入「维修中」；离线部件维修、专项维护等默认关闭"
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
        </Form>
    </Modal>
  );
}

// observer：表单内直接读取 store.systems / store.isSubmitting，候选项异步返回后需触发重渲染
export default observer(WorkOrderForm);

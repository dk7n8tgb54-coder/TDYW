/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 工单新增/编辑表单（Modal）。
 * - 系统与人员一律提交 ID，页面仅展示名称；
 * - 编辑仅限待派发工单（后端强制校验，前端同步隐藏入口）；
 * - 支持故障生成工单/台账转工单的预填场景（initialValues 覆盖）。
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Form, Modal, Input, Select, DatePicker } from 'antd';
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
        const affectedIds = (r.affected_system_ids || (r.affected_systems || []).map(row => row.system))
          .filter(Boolean);
        form.setFieldsValue({
          title: r.title,
          work_type: r.work_type,
          priority: r.priority,
          target_system: r.target_system,
          affected_system_ids: affectedIds.length ? affectedIds : undefined,
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
      <Form form={form} {...formLayout} initialValues={{priority: 'normal'}}>
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
            name="target_system"
            label="目标系统"
            rules={[{required: true, message: '请选择目标系统'}]}
            extra="本次作业对象系统；受影响系统不参与系统健康状态计算"
          >
            <Select
              showSearch
              optionFilterProp="children"
              placeholder="请选择目标系统"
              allowClear
            >
              {store.systems.map(s => (
                <Option value={s.id} key={s.id}>
                  {`${s.name}（${s.system_code}）`}
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="affected_system_ids"
            label="受影响系统"
            extra="可选；不能包含目标系统，同一系统不能重复添加"
          >
            <Select
              mode="multiple"
              showSearch
              optionFilterProp="children"
              placeholder="请选择受影响系统（可多选）"
              allowClear
            >
              {store.systems.map(s => (
                <Option value={s.id} key={s.id}>
                  {`${s.name}（${s.system_code}）`}
                </Option>
              ))}
            </Select>
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

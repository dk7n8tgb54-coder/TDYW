/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, DatePicker, Select, message, Divider } from 'antd';
import store from './store';
import moment from 'moment';
import { MaintenanceFields, InspectionFields } from './components/EventFormFields';

function EventFormComponent() {
  const [form] = Form.useForm();
  const isEdit = !!store.eventFormRecord.id;
  const [eventType, setEventType] = React.useState(String(store.eventFormRecord.event_type || '1'));

  const handleSubmit = () => {
    if (store.isSubmittingEvent) return;

    form.validateFields().then(values => {
      const data = {
        ...values,
        event_time: values.event_time ? values.event_time.format('YYYY-MM-DD HH:mm') : '',
        repair_time: values.repair_time ? values.repair_time.format('YYYY-MM-DD HH:mm') : undefined,
        related_user_name: values.related_user_name
      };
      let action;
      if (isEdit) {
        data.id = store.eventFormRecord.id;
        action = store.handleUpdateEvent(data);
      } else {
        data.device_resume_id = store.eventFormDeviceResume?.id;
        action = store.handleAddEvent(data);
      }
      // 只在请求成功后关闭弹窗并提示，失败时保持弹窗打开以保留用户输入便于重试
      action.then(() => {
        message.success('保存成功');
        store.eventFormVisible = false;
      }).catch(() => {
        // 错误信息已在 store 中通过 message.error 提示，此处保持弹窗打开
      });
    });
  };

  const handleEventTypeChange = (value) => {
    setEventType(String(value));
    form.resetFields(['event_title', 'fault_part', 'fault_phenomenon_cause', 'maintenance_measures', 'repair_time']);
  };

  const getFormInitialValues = () => ({
    ...store.eventFormRecord,
    event_time: store.eventFormRecord.event_time
      ? moment(store.eventFormRecord.event_time, 'YYYY-MM-DD HH:mm')
      : moment(),
    repair_time: store.eventFormRecord.repair_time
      ? moment(store.eventFormRecord.repair_time, 'YYYY-MM-DD HH:mm')
      : null
  });

  const renderDynamicFields = () => {
    switch (eventType) {
      case '1': return <MaintenanceFields isUpdate={false} />;
      case '2': return <MaintenanceFields isUpdate={true} />;
      case '3': return <InspectionFields />;
      default: return null;
    }
  };

  return (
    <Modal
      visible={store.eventFormVisible}
      title={`${isEdit ? '编辑' : '新增'}设备事件 - ${store.eventFormDeviceResume?.device_name}（${store.eventFormDeviceResume?.device_sn}）`}
      onCancel={() => { store.eventFormVisible = false; }}
      onOk={handleSubmit}
      width={800}
      okText="保存"
      cancelText="取消"
      confirmLoading={store.isSubmittingEvent}
    >
      <Form form={form} layout="vertical" initialValues={getFormInitialValues()}>
        <Form.Item label="关联设备">
          <Input value={`${store.eventFormDeviceResume?.device_name} (${store.eventFormDeviceResume?.device_sn})`} disabled />
        </Form.Item>

        <Form.Item
          name="event_type"
          label="事件类型"
          rules={[{ required: true, message: '请选择事件类型' }]}
        >
          <Select onChange={handleEventTypeChange} disabled={isEdit} placeholder="请选择事件类型">
            <Select.Option value="1">重大故障维修</Select.Option>
            <Select.Option value="2">设备更新</Select.Option>
            <Select.Option value="3">设备检修</Select.Option>
          </Select>
        </Form.Item>

        <Divider />
        {renderDynamicFields()}
      </Form>
    </Modal>
  );
}

const EventForm = observer(EventFormComponent);

EventForm.show = (deviceResume, eventRecord = {}) => {
  store.eventFormDeviceResume = deviceResume;
  store.eventFormRecord = eventRecord;
  store.eventFormVisible = true;
};

export default EventForm;

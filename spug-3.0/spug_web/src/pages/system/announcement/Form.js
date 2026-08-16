/**
 * 公告新增/编辑表单（管理端）
 */
import React, { useState, useEffect } from 'react';
import { Modal, Form, Input, Radio, Select, Switch, DatePicker, notification } from 'antd';
import moment from 'moment';
import { http } from 'libs';
import AttachmentManager from 'components/AttachmentManager';

const { RangePicker } = DatePicker;
const SCOPE_ALL = 'all';
const SCOPE_TENANT = 'tenant';

export default function AnnouncementForm({ record, departments, onCancel, onOk }) {
  const [form] = Form.useForm();
  const [visible, setVisible] = useState(true);
  const [saving, setSaving] = useState(false);
  const [scopeType, setScopeType] = useState(record ? record.scope_type : SCOPE_ALL);

  useEffect(() => {
    if (record) {
      const init = {
        title: record.title,
        content: record.content,
        scope_type: record.scope_type,
        target_tenant_ids: record.scope_type === SCOPE_TENANT
          ? (record._scope_tenant_ids || []) : [],
        publish_department_id: record.publish_department_id || undefined,
        is_important: record.is_important,
      };
      const range = [];
      if (record.effective_start_at) range.push(moment(record.effective_start_at));
      if (record.effective_end_at) range.push(moment(record.effective_end_at));
      if (range.length) init.effective_range = range;
      form.setFieldsValue(init);
      setScopeType(record.scope_type);
    } else {
      const myTenant = sessionStorage.getItem('tenant_id') || undefined;
      form.setFieldsValue({ scope_type: SCOPE_ALL, is_important: false, publish_department_id: myTenant });
      setScopeType(SCOPE_ALL);
    }
  }, [record, form]);

  const handleOk = () => {
    form.validateFields().then(values => {
      const range = values.effective_range;
      const payload = {
        title: (values.title || '').trim(),
        content: values.content,
        scope_type: values.scope_type,
        target_tenant_ids: values.scope_type === SCOPE_TENANT ? (values.target_tenant_ids || []) : [],
        publish_department_id: values.publish_department_id,
        is_important: !!values.is_important,
      };
      if (!range || !range[0]) {
        notification.error({ message: '请填写生效开始时间' });
        return;
      }
      payload.effective_start_at = range[0].format('YYYY-MM-DD HH:mm:ss');
      payload.effective_end_at = range[1] ? range[1].format('YYYY-MM-DD HH:mm:ss') : '';
      if (record) payload.id = record.id;
      setSaving(true);
      http.post('/api/home/announcement/admin/', payload)
        .then(() => { notification.success({ message: record ? '保存成功' : '创建成功' }); onOk(); })
        .catch(() => { /* 错误已由 http 拦截器统一提示 */ })
        .finally(() => setSaving(false));
    }).catch(() => {});
  };

  return (
    <Modal
      title={record ? '编辑公告' : '新建公告'}
      visible={visible}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={saving}
      width={720}
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item name="title" label="公告标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input placeholder="请输入标题（1-200 字）" maxLength={200} showCount />
        </Form.Item>
        <Form.Item name="content" label="公告内容" rules={[{ required: true, message: '请输入内容' }]}>
          <Input.TextArea rows={6} placeholder="请输入公告内容" />
        </Form.Item>
        <Form.Item name="scope_type" label="发布范围">
          <Radio.Group onChange={e => setScopeType(e.target.value)}>
            <Radio value={SCOPE_ALL}>全平台</Radio>
            <Radio value={SCOPE_TENANT}>指定部门</Radio>
          </Radio.Group>
        </Form.Item>
        {scopeType === SCOPE_TENANT && (
          <Form.Item
            name="target_tenant_ids"
            label="指定部门"
            rules={[{ required: true, message: '请选择发布部门' }]}
          >
            <Select mode="multiple" showSearch optionFilterProp="children" placeholder="请选择可见部门">
              {departments.map(d => <Select.Option key={d.id} value={d.id}>{d.name}</Select.Option>)}
            </Select>
          </Form.Item>
        )}
        <Form.Item name="publish_department_id" label="发布部门（快照）">
          <Select showSearch optionFilterProp="children" allowClear placeholder="默认取当前部门">
            {departments.map(d => <Select.Option key={d.id} value={d.id}>{d.name}</Select.Option>)}
          </Select>
        </Form.Item>
        <Form.Item name="effective_range" label="生效时间" rules={[{ required: true, message: '请选择生效时间' }]}>
          <RangePicker showTime style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="is_important" label="重要公告" valuePropName="checked">
          <Switch />
        </Form.Item>
        {record && record.id && (
          <Form.Item label="附件">
            <AttachmentManager
              module="announcement"
              recordId={record.id}
              listUrl={`/api/home/announcement/admin/${record.id}/attachments/`}
              uploadUrl={`/api/home/announcement/admin/${record.id}/attachments/`}
              deleteUrl="/api/home/announcement/admin/attachments/"
              downloadUrlPrefix="/api/home/announcement/attachments/"
              previewUrlPrefix="/api/home/announcement/attachments/"
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

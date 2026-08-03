import React, { useState, useEffect } from 'react';
import moment from 'moment';
import { Modal, Form, Input, Switch, DatePicker, Select, InputNumber, Space, notification } from 'antd';
import { http } from 'libs';

const { TextArea } = Input;
const API_BASE = '/api/reminder/';

const REPEAT_TYPES = [
  { value: 'none', label: '不重复' },
  { value: 'daily', label: '每N天' },
  { value: 'weekly', label: '每N周' },
  { value: 'monthly', label: '每N月' },
  { value: 'yearly', label: '每N年' },
];

export default function ReminderFormModal({ visible, editing, users, onCancel, onSuccess }) {
  const [form] = Form.useForm();
  const [confirmLoading, setConfirmLoading] = useState(false);

  useEffect(() => {
    if (!visible) return;
    if (editing) {
      form.setFieldsValue({
        name: editing.name,
        enabled: editing.enabled,
        target_date: editing.target_date ? moment(editing.target_date, 'YYYY-MM-DD') : null,
        repeat_type: editing.repeat_type || 'none',
        repeat_interval: editing.repeat_interval || 1,
        content: editing.content,
        recipient_user_ids: (editing.recipient_users || []).map(u => u.id),
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        enabled: true,
        target_date: moment(),
        repeat_type: 'none',
        repeat_interval: 1,
        content: '',
      });
    }
  }, [visible, editing]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = () => {
    form.validateFields().then(values => {
      const dateStr = values.target_date ? values.target_date.format('YYYY-MM-DD') : '';
      const recipients = (values.recipient_user_ids || []).map(uid => {
        const u = users.find(x => x.id === uid);
        return { id: uid, nickname: u ? u.nickname : String(uid) };
      });
      const payload = {
        name: values.name,
        enabled: values.enabled,
        target_date: dateStr,
        repeat_type: values.repeat_type || 'none',
        repeat_interval: values.repeat_interval || 1,
        content: values.content || '',
        recipient_users: JSON.stringify(recipients),
      };
      setConfirmLoading(true);
      const url = editing ? `${API_BASE}${editing.id}/` : API_BASE;
      const method = editing ? http.patch : http.post;
      method(url, payload)
        .then(() => {
          notification.success({ message: editing ? '已保存' : '已创建' });
          onSuccess();
        })
        .catch(e => notification.error({ message: '操作失败', description: e.message || String(e) }))
        .finally(() => setConfirmLoading(false));
    }).catch(() => null);
  };

  return (
    <Modal
      title={editing ? '编辑提醒规则' : '新建提醒规则'}
      visible={visible}
      onOk={handleSubmit}
      onCancel={onCancel}
      confirmLoading={confirmLoading}
      width={640}
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="事件名称" rules={[{ required: true, message: '请输入事件名称' }]}>
          <Input placeholder="如：综合科周报提醒" />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="target_date" label="目标日" rules={[{ required: true, message: '请选择目标日' }]}>
          <DatePicker format="YYYY-MM-DD" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item label="重复">
          <Space>
            <Form.Item name="repeat_type" noStyle>
              <Select style={{ width: 120 }} onChange={() => form.setFieldsValue({ repeat_interval: 1 })}>
                {REPEAT_TYPES.map(r => (
                  <Select.Option key={r.value} value={r.value}>{r.label}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item shouldUpdate noStyle>
              {() => {
                const rt = form.getFieldValue('repeat_type');
                if (rt && rt !== 'none') {
                  return (
                    <Form.Item name="repeat_interval" noStyle>
                      <InputNumber min={1} max={365} style={{ width: 80 }} />
                    </Form.Item>
                  );
                }
                return null;
              }}
            </Form.Item>
          </Space>
        </Form.Item>
        <Form.Item name="content" label="提醒内容">
          <TextArea rows={3} placeholder="请及时完成本周周报，避免影响科室汇总。" />
        </Form.Item>
        <Form.Item
          name="recipient_user_ids"
          label="接收人"
          rules={[{ required: true, message: '请至少选择一个接收人' }]}
        >
          <Select
            mode="multiple"
            showSearch
            placeholder="选择需要提醒的人员"
            filterOption={(input, option) =>
              (option?.children || '').toLowerCase().includes(input.toLowerCase())
            }
          >
            {users.map(u => (
              <Select.Option key={u.id} value={u.id}>{u.nickname}</Select.Option>
            ))}
          </Select>
        </Form.Item>
      </Form>
    </Modal>
  );
}

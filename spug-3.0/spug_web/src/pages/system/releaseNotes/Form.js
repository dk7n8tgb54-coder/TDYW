/**
 * 更新日志新建/编辑表单
 *
 * 更新日志面向全平台所有用户，不再选择可见范围；仅超级管理员可保存。
 */
import React, {useState, useEffect} from 'react';
import {Modal, Form, Input, Select, Switch} from 'antd';
import {http} from 'libs';

export default function ReleaseNoteForm({record, onCancel, onOk}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [roles, setRoles] = useState([]);

  useEffect(() => {
    http.get('/api/account/role/')
      .then(list => setRoles(list || []))
      .catch(() => setRoles([]));
  }, []);

  useEffect(() => {
    if (record) {
      form.setFieldsValue({
        version: record.version,
        title: record.title,
        content: record.content,
        is_required: !!record.is_required,
        role_ids: record._role_ids || [],
      });
    } else {
      form.setFieldsValue({
        is_required: false,
        role_ids: [],
      });
    }
  }, [record, form]);

  function handleOk() {
    form.validateFields().then(values => {
      setLoading(true);
      const payload = {
        version: values.version,
        title: values.title,
        content: values.content,
        is_required: !!values.is_required,
        role_ids: values.role_ids || [],
      };
      if (record) payload.id = record.id;
      http.post('/api/system/release-notes/admin/', payload)
        .then(() => {
          setLoading(false);
          onOk();
        })
        .catch(() => setLoading(false));
    }).catch(() => { /* 表单校验失败，保持弹窗 */ });
  }

  return (
    <Modal
      visible
      title={record ? '编辑更新日志' : '新建更新日志'}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={loading}
      width={640}
      maskClosable={false}>
      <Form form={form} layout="vertical">
        <Form.Item name="version" label="版本号" rules={[{required: true, message: '请输入版本号'}]}>
          <Input placeholder="如 v3.3.3"/>
        </Form.Item>
        <Form.Item name="title" label="更新标题" rules={[{required: true, message: '请输入更新标题'}]}>
          <Input placeholder="一句话说明本次更新"/>
        </Form.Item>
        <Form.Item name="content" label="更新内容" rules={[{required: true, message: '请输入更新内容'}]}>
          <Input.TextArea rows={6} placeholder="详细说明更新内容"/>
        </Form.Item>
        <Form.Item name="role_ids" label="适用角色" extra="不选择表示对所有角色可见">
          <Select mode="multiple" allowClear placeholder="全部角色"
                  options={roles.map(r => ({label: r.name, value: r.id}))}/>
        </Form.Item>
        <Form.Item name="is_required" label="要求用户确认" valuePropName="checked">
          <Switch checkedChildren="是" unCheckedChildren="否"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

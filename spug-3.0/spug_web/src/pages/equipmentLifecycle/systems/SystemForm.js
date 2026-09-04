/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, message } from 'antd';
import { systemStore as store } from './store';

/**
 * 系统新建/编辑弹窗
 */
export default observer(function () {
  const [form] = Form.useForm();
  const isEdit = !!store.record.id;

  const handleSubmit = () => {
    form.validateFields().then(values => {
      const data = {
        name: (values.name || '').trim(),
        code: (values.code || '').trim(),
        description: (values.description || '').trim(),
      };
      const request = isEdit
        ? store.handleUpdate({...data, id: store.record.id})
        : store.handleAdd(data);
      request.then(() => message.success('保存成功'));
    }).catch(() => {});
  };

  return (
    <Modal
      visible={store.formVisible}
      title={isEdit ? '编辑系统' : '新增系统'}
      onCancel={() => store.closeForm()}
      onOk={handleSubmit}
      okText="保存"
      cancelText="取消"
      width={560}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: store.record.name,
          code: store.record.code,
          description: store.record.description,
        }}
      >
        <Form.Item
          name="name"
          label="系统名称"
          rules={[
            {required: true, message: '请输入系统名称'},
            {max: 100, message: '系统名称不能超过100个字符'},
          ]}
        >
          <Input placeholder="请输入系统名称"/>
        </Form.Item>
        <Form.Item
          name="code"
          label="系统编码（选填）"
          rules={[{max: 50, message: '系统编码不能超过50个字符'}]}
        >
          <Input placeholder="请输入系统编码，租户内不可重复"/>
        </Form.Item>
        <Form.Item
          name="description"
          label="系统描述"
          rules={[{max: 500, message: '系统描述不能超过500个字符'}]}
        >
          <Input.TextArea rows={3} placeholder="请输入系统描述" maxLength={500} showCount/>
        </Form.Item>
      </Form>
    </Modal>
  );
})

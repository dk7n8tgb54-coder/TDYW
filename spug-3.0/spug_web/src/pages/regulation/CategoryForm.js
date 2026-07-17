/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, InputNumber, message } from 'antd';
import { http } from 'libs';
import S from './store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const info = S.categoryRecord || {};

  React.useEffect(() => {
    form.setFieldsValue({
      name: info.name || '',
      sort_order: info.sort_order || 0,
      code: info.code || '',
    });
  }, []);

  function handleSubmit() {
    form.validateFields().then(() => {
      const formData = form.getFieldsValue();
      setLoading(true);
      if (info.id) {
        http.put(`/api/regulation/categories/${info.id}/`, formData)
          .then(() => {
            message.success('编辑成功');
            S.categoryFormVisible = false;
            S.fetchCategories();
          })
          .catch(e => message.error(e.message || '操作失败'))
          .finally(() => setLoading(false));
      } else {
        if (info.parent_id) {
          formData.parent_id = info.parent_id;
        }
        http.post('/api/regulation/categories/', formData)
          .then(() => {
            message.success('新建成功');
            S.categoryFormVisible = false;
            S.fetchCategories();
          })
          .catch(e => message.error(e.message || '操作失败'))
          .finally(() => setLoading(false));
      }
    });
  }

  const title = info.parent_name
    ? (info.id ? '编辑子分类' : `在「${info.parent_name}」下新建子分类`)
    : (info.id ? '编辑分类' : '新建根分类');

  return (
    <Modal
      visible
      width={480}
      maskClosable={false}
      title={title}
      onCancel={() => S.categoryFormVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{ span: 6 }} wrapperCol={{ span: 16 }}>
        <Form.Item name="name" label="分类名称" rules={[{ required: true, message: '请输入分类名称' }]}>
          <Input placeholder="请输入分类名称" />
        </Form.Item>
        <Form.Item name="code" label="分类编码">
          <Input placeholder="可选，如 ICAO / CAAC" />
        </Form.Item>
        <Form.Item name="sort_order" label="排序">
          <InputNumber min={0} style={{ width: '100%' }} placeholder="数字越小越靠前" />
        </Form.Item>
      </Form>
    </Modal>
  );
});

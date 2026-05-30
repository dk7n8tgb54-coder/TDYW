/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Form, Input, Modal, message } from 'antd';
import http from 'libs/http';
import store from './store';

@observer
class ComForm extends React.Component {
  handleOk = () => {
    this.form.validateFields().then((values) => {
      const isCreate = !store.record.id;
      const method = isCreate ? http.post : http.patch;
      method('/api/account/tenant/', values)
        .then(() => {
          message.success(isCreate ? '创建成功' : '更新成功');
          store.formVisible = false;
          store.fetchRecords()
        })
    })
  };

  render() {
    const record = store.record;
    return (
      <Modal
        title={record.id ? '编辑租户' : '新建租户'}
        visible
        width={560}
        onOk={this.handleOk}
        onCancel={() => store.formVisible = false}
        destroyOnClose>
        <Form
          ref={ref => this.form = ref}
          layout="vertical"
          initialValues={record}>
          <Form.Item
            name="id"
            label="租户标识"
            rules={[
              {required: true, message: '请输入租户标识'},
              {pattern: /^[a-zA-Z0-9_\-]{1,50}$/, message: '仅支持字母、数字、下划线、横线，长度1-50'},
            ]}>
            <Input placeholder="例如：tenant_a" disabled={!!record.id}/>
          </Form.Item>
          <Form.Item
            name="name"
            label="租户名称"
            rules={[{required: true, message: '请输入租户名称'}]}>
            <Input placeholder="例如：XX部门租户"/>
          </Form.Item>
          <Form.Item
            name="description"
            label="描述">
            <Input.TextArea rows={3} placeholder="可选"/>
          </Form.Item>
        </Form>
      </Modal>
    )
  }
}

export default ComForm

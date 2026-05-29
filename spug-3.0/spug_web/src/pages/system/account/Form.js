/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useState, useEffect, useRef} from 'react';
import {Link} from 'react-router-dom';
import {observer} from 'mobx-react';
import {Modal, Form, Select, Input, AutoComplete, message} from 'antd';
import {http} from 'libs';
import store from './store';
import rStore from '../role/store';


export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [tenantChoices, setTenantChoices] = useState([]);
  const isSupper = store.isSupper;
  const mountedRef = useRef(true);

  useEffect(() => {
    // 超管才加载租户选项
    if (isSupper) {
      http.get('/api/account/user/tenant_choices/')
        .then(res => { if (mountedRef.current) setTenantChoices(res) })
        .catch(() => {});
    }
    return () => { mountedRef.current = false }
  }, [isSupper]);

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    formData.id = store.record.id;
    http.post('/api/account/user/', formData)
      .then(() => {
        message.success('操作成功');
        store.formVisible = false;
        store.fetchRecords()
      }, () => { if (mountedRef.current) setLoading(false) })
  }

  return (
    <Modal
      visible
      width={700}
      maskClosable={false}
      destroyOnClose
      title={store.record.id ? '编辑账户' : '新建账户'}
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={store.record} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item required name="username" label="登录名">
          <Input placeholder="请输入登录名"/>
        </Form.Item>
        <Form.Item required name="nickname" label="姓名">
          <Input placeholder="请输入姓名"/>
        </Form.Item>
        <Form.Item required hidden={store.record.id} name="password" label="密码"
                   extra="至少8位，包含数字、小写和大写字母、特殊字符。">
          <Input.Password placeholder="请输入密码"/>
        </Form.Item>
        {isSupper && (
          <Form.Item name="tenant_id" label="所属租户"
                     extra="新建时默认使用登录名，指定后可共享同租户数据">
            <AutoComplete allowClear placeholder="请选择或输入租户"
                          filterOption={(input, option) =>
                            option.value?.toLowerCase().includes(input.toLowerCase())
                          }>
              {tenantChoices.map(item => (
                <AutoComplete.Option value={item.tenant_id} key={item.tenant_id}>
                  {item.tenant_id} ({item.user_count}人)
                </AutoComplete.Option>
              ))}
            </AutoComplete>
          </Form.Item>
        )}
        {!isSupper && (
          <Form.Item name="tenant_id" label="所属租户"
                     initialValue={store.currentTenantId}>
            <Input disabled/>
          </Form.Item>
        )}
        <Form.Item hidden={store.record.is_supper} label="角色" style={{marginBottom: 0}}>
          <Form.Item name="role_ids" style={{display: 'inline-block', width: '80%'}}
                     extra="权限最大化原则，组合多个角色权限。">
            <Select mode="multiple" placeholder="请选择">
              {rStore.records.map(item => (
                <Select.Option value={item.id} key={item.id}>{item.name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item style={{display: 'inline-block', width: '20%', textAlign: 'right'}}>
            <Link to="/system/role">新建角色</Link>
          </Form.Item>
        </Form.Item>
      </Form>
    </Modal>
  )
})

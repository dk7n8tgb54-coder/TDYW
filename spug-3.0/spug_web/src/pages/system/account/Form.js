/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, {useState, useEffect, useRef} from 'react';
import {Link} from 'react-router-dom';
import {observer} from 'mobx-react';
import {Modal, Form, Select, Input, message} from 'antd';
import {http} from 'libs';
import store from './store';


export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [tenantChoices, setTenantChoices] = useState([]);
  // 账号表单角色下拉专用数据源：只展示当前操作者可分配给目标账号的角色，
  // 不再直接复用角色管理页的 rStore.records，避免普通管理员看到平台级/系统/全局/其他租户角色。
  const [assignableRoles, setAssignableRoles] = useState([]);
  // 跟踪当前表单 tenant_id，用于 extra 文案动态判断（超管未选租户时额外提示）
  const [tenantId, setTenantId] = useState(store.record.tenant_id || undefined);
  const isSupper = store.isSupper;
  const mountedRef = useRef(true);

  const fetchAssignableRoles = (tid) => {
    const params = {};
    if (isSupper && tid) {
      params.tenant_id = tid;
    }
    return http.get('/api/account/role/assignable/', {params})
      .then(res => { if (mountedRef.current) setAssignableRoles(res) })
      .catch(() => {})
  };

  useEffect(() => {
    // 超管才加载租户选项
    if (isSupper) {
      http.get('/api/account/user/tenant_choices/')
        .then(res => { if (mountedRef.current) setTenantChoices(res) })
        .catch(() => {});
    }
    // 打开表单时拉取可分配角色：
    // 普通管理员后端忽略 tenant_id，只返回本租户普通角色；
    // 超管编辑已有 tenant_id 时按该租户返回，新建无 tenant_id 时只返回平台级+全局管理员角色。
    fetchAssignableRoles(tenantId);
    return () => { mountedRef.current = false }
  }, [isSupper]);

  function handleTenantChange(value) {
    setTenantId(value);
    // 超管切换目标租户：重新拉取可分配角色，并清空已选 role_ids，
    // 避免保留上一个租户的角色选择（后端强校验也会拦截，这里做体验优化）。
    fetchAssignableRoles(value);
    form.setFieldsValue({role_ids: []});
  }

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

  // 超管且未选择租户时，角色下拉额外提示选择租户
  const roleExtra = isSupper && !tenantId
    ? '仅显示当前账号可分配给该用户的角色；选择所属租户后可分配该租户角色'
    : '仅显示当前账号可分配给该用户的角色';

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
                   extra="至少8位，须含数字、小写和大写字母及特殊字符，仅限英文、数字、符号（不可含中文）。">
          <Input.Password placeholder="请输入密码"/>
        </Form.Item>
        {isSupper && (
          <Form.Item name="tenant_id" label="所属租户"
                     extra="选择租户后该用户将与同租户共享数据">
            <Select allowClear placeholder="请选择租户" showSearch
                    onChange={handleTenantChange}
                    filterOption={(input, option) =>
                      option.children?.toLowerCase().includes(input.toLowerCase())
                    }>
              {tenantChoices.map(item => (
                <Select.Option value={item.id} key={item.id}>
                  {item.name} ({item.id}) - {item.user_count}人
                </Select.Option>
              ))}
            </Select>
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
                     extra={roleExtra}>
            <Select mode="multiple" placeholder="请选择">
              {assignableRoles.map(item => (
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

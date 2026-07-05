/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, Switch, Alert, message } from 'antd';
import http from 'libs/http';
import store from './store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [tenants, setTenants] = useState([]);
  // 普通管理员不能创建/编辑全局管理员角色，后端会强校验，这里仅做体验优化
  const isSupper = sessionStorage.getItem('is_supper') === 'true';
  // 角色归属：'platform' 平台级角色（tenant_id=null），'tenant' 指定租户角色
  // 仅超管可见。普通管理员创建的角色后端强制归属其租户，前端不展示此项。
  const record = store.record;
  const initialBelong = record && record.tenant_id ? 'tenant' : 'platform';

  useEffect(() => {
    if (isSupper) {
      // 复用现有租户下拉接口
      http.get('/api/account/user/tenant_choices/')
        .then(res => setTenants(res || []))
        .catch(() => setTenants([]));
    }
  }, [isSupper]);

  // 勾选全局管理员时，自动切换为平台级角色，并强制 is_system=true
  // 后端会兜底强制 tenant_id=null / is_system=true，前端只是体验优化
  function handleGlobalAdminChange(checked) {
    if (checked) {
      form.setFieldsValue({
        belong: 'platform',
        tenant_id: undefined,
        is_system: true
      });
    }
  }

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    formData['id'] = store.record.id;
    // 角色归属处理：platform -> tenant_id=null，tenant -> 取选择的租户
    if (isSupper) {
      if (formData.is_global_admin) {
        // 全局管理员角色由后端强制为平台级系统角色，前端不提交 tenant_id
        formData['tenant_id'] = null;
        formData['is_system'] = true;
        delete formData.belong;
      } else if (formData.belong === 'platform') {
        formData['tenant_id'] = null;
        delete formData.belong;
      } else if (formData.belong === 'tenant' && formData.tenant_id) {
        // 保留选中的 tenant_id
        delete formData.belong;
      } else {
        // 选了租户角色但没选租户，给个兜底错误
        message.error('请选择所属租户');
        setLoading(false);
        return;
      }
    } else {
      // 普通管理员强制不提交 tenant_id/is_system/is_global_admin，避免越权
      delete formData.belong;
      delete formData.tenant_id;
      delete formData.is_system;
      formData['is_global_admin'] = false;
    }
    http.post('/api/account/role/', formData)
      .then(res => {
        message.success('操作成功');
        store.formVisible = false;
        store.fetchRecords()
      }, () => setLoading(false))
  }

  return (
    <Modal
      visible
      maskClosable={false}
      title={store.record.id ? '编辑角色' : '新建角色'}
      onCancel={() => store.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={{...store.record, belong: initialBelong}} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item required name="name" label="角色名称">
          <Input placeholder="请输入角色名称"/>
        </Form.Item>
        {isSupper && (
          <>
            <Form.Item name="is_global_admin" label="全局管理员" valuePropName="checked"
                       extra="全局管理员角色仅超级管理员可创建，普通管理员不可分配">
              <Switch onChange={handleGlobalAdminChange}/>
            </Form.Item>
            {/* 全局管理员勾选时显示提示，并禁用归属/租户/系统角色字段 */}
            <Form.Item noStyle shouldUpdate={(prev, cur) => prev.is_global_admin !== cur.is_global_admin}>
              {({ getFieldValue }) => getFieldValue('is_global_admin') ? (
                <Form.Item label="角色归属">
                  <Alert type="info" showIcon
                         message="全局管理员角色由后端强制为平台级系统角色，归属固定为平台级"/>
                </Form.Item>
              ) : (
                <>
                  <Form.Item name="belong" label="角色归属"
                             extra="平台级角色可分配给任意租户用户；租户角色仅可分配给该租户用户">
                    <Select placeholder="请选择角色归属">
                      <Select.Option value="platform">平台级角色</Select.Option>
                      <Select.Option value="tenant">指定租户角色</Select.Option>
                    </Select>
                  </Form.Item>
                  <Form.Item noStyle shouldUpdate={(prev, cur) => prev.belong !== cur.belong}>
                    {({ getFieldValue }) => getFieldValue('belong') === 'tenant' ? (
                      <Form.Item required name="tenant_id" label="所属租户">
                        <Select placeholder="请选择所属租户" allowClear>
                          {tenants.map(t => (
                            <Select.Option key={t.id} value={t.id}>
                              {t.name}（{t.id}）{t.user_count != null ? ` - ${t.user_count}人` : ''}
                            </Select.Option>
                          ))}
                        </Select>
                      </Form.Item>
                    ) : null}
                  </Form.Item>
                  <Form.Item name="is_system" label="系统角色" valuePropName="checked"
                             extra="系统角色普通管理员不可编辑/删除/分配，仅超管可管理">
                    <Switch/>
                  </Form.Item>
                </>
              )}
            </Form.Item>
          </>
        )}
        <Form.Item name="desc" label="备注信息">
          <Input.TextArea placeholder="请输入角色备注信息"/>
        </Form.Item>
      </Form>
    </Modal>
  )
})

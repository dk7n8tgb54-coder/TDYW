/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——配置组成项页签。
 * 组成项仅描述系统组成（可按类型汇总），不关联单台设备资产。
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Table, Button, Modal, Form, Input, InputNumber, Popconfirm, Divider, Spin } from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import { AuthButton, AuthDiv } from 'components';
import store from './store';
import { PERM } from './constants';

const {TextArea} = Input;

@observer
class ComponentsTab extends React.Component {
  componentDidMount() {
    store.fetchComponents();
  }

  confirmDelete = (record) => {
    store.deleteComponent(record).catch(() => {});
  };

  render() {
    if (store.isComponentsFetching && !store.components.length) {
      return <Spin style={{display: 'block', marginTop: 60}}/>;
    }
    return (
      <AuthDiv auth={PERM.CFG_VIEW}>
        <div style={{marginBottom: 12}}>
          <AuthButton
            auth={PERM.CFG_EDIT}
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showComponentForm()}
          >
            新增组成项
          </AuthButton>
          <span style={{color: '#999', marginLeft: 12}}>
            允许按类型汇总（如“接入交换机，某型号，4 台”），不要求逐台建档
          </span>
        </div>
        <Table
          rowKey="id"
          pagination={false}
          dataSource={store.components}
          columns={[{
            title: '名称', dataIndex: 'name', width: 160,
          }, {
            title: '类别', dataIndex: 'category', width: 120,
          }, {
            title: '型号或版本', dataIndex: 'model_version', width: 140,
          }, {
            title: '数量', dataIndex: 'quantity', width: 80,
          }, {
            title: '用途', dataIndex: 'purpose', width: 150, ellipsis: true,
          }, {
            title: '资产编号/序列号', dataIndex: 'asset_sn', width: 140,
          }, {
            title: '外部系统引用', dataIndex: 'external_ref', width: 140,
          }, {
            title: '备注', dataIndex: 'remark', ellipsis: true,
          }, {
            title: '操作', width: 120,
            render: (text, record) => (
              <span>
                <AuthButton auth={PERM.CFG_EDIT} type="link" size="small" style={{padding: 0}}
                            onClick={() => store.showComponentForm(record)}>
                  编辑
                </AuthButton>
                <Divider type="vertical"/>
                <Popconfirm title="确定删除该组成项？" onOk={() => this.confirmDelete(record)}>
                  <AuthButton auth={PERM.CFG_EDIT} type="link" size="small" style={{padding: 0}}>
                    删除
                  </AuthButton>
                </Popconfirm>
              </span>
            ),
          }]}
          locale={{emptyText: '暂无配置组成项'}}
        />
        <ComponentForm/>
      </AuthDiv>
    );
  }
}

const ComponentForm = observer(function ComponentForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const record = store.componentRecord;

  function handleSubmit() {
    form.validateFields().then(values => {
      setLoading(true);
      store.submitComponent(values)
        .catch(() => {})
        .finally(() => setLoading(false));
    }).catch(() => {});
  }

  return (
    <Modal
      visible={store.componentFormVisible}
      title={record.id ? '编辑组成项' : '新增组成项'}
      maskClosable={false}
      confirmLoading={loading}
      onCancel={() => store.componentFormVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}
            initialValues={{
              name: record.name,
              category: record.category,
              model_version: record.model_version,
              quantity: record.quantity,
              purpose: record.purpose,
              asset_sn: record.asset_sn,
              external_ref: record.external_ref,
              remark: record.remark,
            }}>
        <Form.Item
          name="name"
          label="名称"
          rules={[{required: true, message: '请输入组成项名称'}, {max: 100, message: '长度不能超过 100'}]}
        >
          <Input placeholder="如：接入交换机"/>
        </Form.Item>
        <Form.Item name="category" label="类别" rules={[{max: 50, message: '长度不能超过 50'}]}>
          <Input placeholder="如：网络设备 / 板卡 / 软件"/>
        </Form.Item>
        <Form.Item name="model_version" label="型号或版本" rules={[{max: 100, message: '长度不能超过 100'}]}>
          <Input/>
        </Form.Item>
        <Form.Item name="quantity" label="数量">
          <InputNumber min={0} style={{width: '100%'}} placeholder="按类型汇总时填总数"/>
        </Form.Item>
        <Form.Item name="purpose" label="用途" rules={[{max: 200, message: '长度不能超过 200'}]}>
          <TextArea rows={2}/>
        </Form.Item>
        <Form.Item name="asset_sn" label="资产编号/序列号" extra="仅定位、保修或审计确有价值时填写"
                   rules={[{max: 100, message: '长度不能超过 100'}]}>
          <Input/>
        </Form.Item>
        <Form.Item name="external_ref" label="外部系统引用" rules={[{max: 200, message: '长度不能超过 200'}]}>
          <Input placeholder="外部资产/库存系统编号"/>
        </Form.Item>
        <Form.Item name="remark" label="备注" rules={[{max: 500, message: '长度不能超过 500'}]}>
          <TextArea rows={2}/>
        </Form.Item>
      </Form>
    </Modal>
  );
});

export default ComponentsTab;

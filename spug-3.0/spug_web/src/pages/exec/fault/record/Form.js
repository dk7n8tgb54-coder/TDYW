/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { ExclamationCircleOutlined, DeploymentUnitOutlined } from '@ant-design/icons';
import { Modal, Form, Input, Select, DatePicker, Button, message, Descriptions } from 'antd';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);

  function handleSubmit() {
    setLoading(true);
    const formData = form.getFieldsValue();
    formData['id'] = S.record.id;
    if (formData['fault_date']) {
      formData['fault_date'] = formData['fault_date'].format('YYYY-MM-DD');
    }
    http.post('/api/fault/faultrecord/', formData)
      .then(() => {
        message.success('操作成功');
        S.formVisible = false;
        S.fetchRecords()
      }, () => setLoading(false))
  }

  function handleAddSystemName() {
    let systemName;
    Modal.confirm({
      icon: <ExclamationCircleOutlined/>,
      title: '添加系统名称',
      content: (
        <Form layout="vertical" style={{marginTop: 24}}>
          <Form.Item required label="系统名称">
            <Input onChange={e => systemName = e.target.value}/>
          </Form.Item>
        </Form>
      ),
      onOk: () => {
        if (systemName) {
          S.systemNames.push(systemName);
          form.setFieldsValue({system_name: systemName})
        }
      },
    })
  }

  React.useEffect(() => {
    if (S.record.id && (S.record.isViewMode || !hasPermission('exec.faultrecord.edit'))) {
      setViewMode(true);
    } else {
      setViewMode(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const info = S.record;

  if (viewMode) {
    return (
      <Modal
        visible
        width={800}
        title="故障处置记录详情"
        footer={[
          <Button key="sync" icon={<DeploymentUnitOutlined />} onClick={() => message.success('已模拟同步到设备履历模块')}>
            同步到设备履历
          </Button>,
          <Button key="close" onClick={() => S.formVisible = false}>关闭</Button>
        ]}
        onCancel={() => S.formVisible = false}>
        <Descriptions bordered column={1}>
          <Descriptions.Item label="系统名称">{info.system_name}</Descriptions.Item>
          <Descriptions.Item label="设备编号">{info.device_code}</Descriptions.Item>
          <Descriptions.Item label="日期">{info.fault_date}</Descriptions.Item>
          <Descriptions.Item label="处置人员">{info.handler}</Descriptions.Item>
          <Descriptions.Item label="记录人员">{info.recorder}</Descriptions.Item>
          <Descriptions.Item label="故障评级">{info.fault_level}</Descriptions.Item>
          <Descriptions.Item label="故障现象">
            <div style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto' }}>
              {info.fault_phenomenon}
            </div>
          </Descriptions.Item>
          <Descriptions.Item label="处置过程">
            <div style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto' }}>
              {info.handling_process}
            </div>
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    )
  }

  const initialValues = {...info};
  if (initialValues.fault_date) {
    initialValues.fault_date = moment(initialValues.fault_date);
  }

  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={S.record.id ? '编辑故障处置记录' : '新建故障处置记录'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item required label="系统名称" style={{marginBottom: 0}}>
          <Form.Item name="system_name" style={{display: 'inline-block', width: 'calc(75%)', marginRight: 8}}>
            <Select placeholder="请选择系统名称">
              {S.systemNames.map(item => (
                <Select.Option value={item} key={item}>{item}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item style={{display: 'inline-block', width: 'calc(25%-8px)'}}>
            <Button type="link" onClick={handleAddSystemName}>添加系统名称</Button>
          </Form.Item>
        </Form.Item>
        <Form.Item required name="device_code" label="设备编号">
          <Input placeholder="请输入设备编号"/>
        </Form.Item>
        <Form.Item required name="fault_date" label="日期">
          <DatePicker style={{width: '100%'}} placeholder="请选择日期"/>
        </Form.Item>
        <Form.Item required name="handler" label="处置人员">
          <Input placeholder="请输入处置人员"/>
        </Form.Item>
        <Form.Item required name="recorder" label="记录人员">
          <Input placeholder="请输入记录人员"/>
        </Form.Item>
        <Form.Item required name="fault_level" label="故障评级">
          <Select placeholder="请选择故障评级">
            <Select.Option value="A">A</Select.Option>
            <Select.Option value="B">B</Select.Option>
            <Select.Option value="C">C</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item required name="fault_phenomenon" label="故障现象">
          <Input.TextArea rows={6} placeholder="请输入故障现象"/>
        </Form.Item>
        <Form.Item required name="handling_process" label="处置过程">
          <Input.TextArea rows={6} placeholder="请输入处置过程"/>
        </Form.Item>
      </Form>
    </Modal>
  )
})

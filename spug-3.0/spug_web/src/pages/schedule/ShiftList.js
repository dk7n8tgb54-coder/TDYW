/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect, useState } from 'react';
import { observer } from 'mobx-react';
import { Table, Card, Modal, Form, Input, InputNumber, Select, Switch, message, Tag } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { http } from 'libs';
import { AuthButton, AuthDiv } from 'components';
import store from './stores';

const { Option } = Select;
const { TextArea } = Input;

function ShiftList() {
  const [form] = Form.useForm();
  const [modalVisible, setModalVisible] = useState(false);

  useEffect(() => {
    store.fetchShiftList();
  }, []);

  const handleAdd = () => {
    form.resetFields();
    setModalVisible(true);
  };

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      await http.post('/api/schedule/shift/', values);
      message.success('添加成功');
      setModalVisible(false);
      form.resetFields();
      store.fetchShiftList();
    } catch (error) {
      console.error('[ShiftList] Failed to add shift:', error);
    }
  };

  const handleDelete = (id) => {
    Modal.confirm({
      title: '删除确认',
      content: '确定要删除该班次吗？',
      onOk: () => {
        return http.delete('/api/schedule/shift/', { params: { id } })
          .then(() => {
            message.success('删除成功');
            store.fetchShiftList();
          });
      }
    });
  };

  const columns = [
    { title: '班次名称', dataIndex: 'name' },
    {
      title: '班次类型',
      dataIndex: 'shift_type',
      render: (val) => {
        const map = { 'custom': '自定义', 'work_rest': '上X休Y' };
        return map[val] || val;
      }
    },
    { title: '工作天数', dataIndex: 'work_days' },
    { title: '休息天数', dataIndex: 'rest_days' },
    {
      title: '颜色',
      dataIndex: 'color',
      render: (color) => (
        <Tag style={{ backgroundColor: color, color: '#fff' }}>●</Tag>
      )
    },
    {
      title: '是否默认',
      dataIndex: 'is_default',
      render: (val) => (val ? <Tag color="green">是</Tag> : <Tag>否</Tag>)
    },
    {
      title: '操作',
      render: (_, record) => (
        <AuthButton
          auth="schedule.shift.del"
          type="link"
          danger
          size="small"
          icon={<DeleteOutlined />}
          onClick={() => handleDelete(record.id)}
        >
          删除
        </AuthButton>
      )
    }
  ];

  return (
    <>
      <AuthDiv auth="schedule.shift.view">
        <Card title="班次管理" extra={
          <AuthButton auth="schedule.shift.add" type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加</AuthButton>
        }>
          <Table
            dataSource={store.shiftList}
            rowKey="id"
            columns={columns}
            pagination={{ pageSize: 10 }}
            size="small"
          />
        </Card>

        <Modal
          title="添加班次"
          visible={modalVisible}
          onOk={handleOk}
          onCancel={() => setModalVisible(false)}
          width={600}
          okText="确定"
          cancelText="取消"
        >
          <Form form={form} layout="vertical">
            <Form.Item label="班次名称" name="name" rules={[{ required: true, message: '请输入班次名称' }]}>
              <Input
                placeholder="请输入班次名称，如：白班、夜班"
              />
            </Form.Item>
              <Form.Item label="班次类型" name="shift_type" initialValue="custom" rules={[{ required: true, message: '请选择班次类型' }]}>
                <Select>
                  <Option value="custom">自定义</Option>
                  <Option value="work_rest">上X休Y</Option>
                </Select>
              </Form.Item>
              <Form.Item label="工作天数" name="work_days">
                <InputNumber min={0} placeholder="上X休Y模式填写" />
              </Form.Item>
              <Form.Item label="休息天数" name="rest_days">
                <InputNumber min={0} placeholder="上X休Y模式填写" />
              </Form.Item>
              <Form.Item label="描述" name="description">
                <TextArea rows={3} placeholder="班次描述" />
              </Form.Item>
              <Form.Item label="颜色标记" name="color" initialValue="#1890ff">
                <Input type="color" />
              </Form.Item>
              <Form.Item label="是否默认" name="is_default" valuePropName="checked" initialValue={false}>
                <Switch />
              </Form.Item>
            </Form>
          </Modal>
      </AuthDiv>
    </>
  );
}

export default observer(ShiftList);

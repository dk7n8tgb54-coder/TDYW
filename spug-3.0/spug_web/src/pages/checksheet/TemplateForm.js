/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Button, message, Card, Space, Divider } from 'antd';
import { PlusOutlined, MinusCircleOutlined } from '@ant-design/icons';
import store from './store';

export default observer(function TemplateForm() {
  const [form] = Form.useForm();
  const [checkItems, setCheckItems] = React.useState([]);
  const [selectedProject, setSelectedProject] = React.useState('');

  React.useEffect(() => {
    if (store.templateRecord.id) {
      const data = {...store.templateRecord};
      if (data.check_items) {
        setCheckItems(data.check_items);
      }
      if (data.project) {
        setSelectedProject(data.project);
      }
      form.setFieldsValue(data);
    } else {
      // 新建模板时清空表单
      form.resetFields();
      setCheckItems([]);
      setSelectedProject('');
    }
  }, [store.templateRecord.id]);

  const handleSubmit = () => {
    const data = {
      project: selectedProject,
      check_items: checkItems.filter(item => item.trim())
    };

    console.log('[TemplateForm] Submitting data:', data);

    if (!data.project) {
      message.error('请输入项目名称');
      return;
    }

    if (!data.check_items || data.check_items.length === 0) {
      message.error('请至少添加一个检查内容');
      return;
    }

    store.saveTemplate(data)
      .then((res) => {
        console.log('[TemplateForm] Save response:', res);
        message.success(store.templateRecord.id ? '更新成功' : '创建成功');
        store.fetchTemplates();
        store.templateFormVisible = false;
        form.resetFields();
        setCheckItems([]);
        setSelectedProject('');
      })
      .catch((error) => {
        console.error('保存模板失败:', error);
        message.error('保存失败，请重试');
      });
  };

  const handleAddItem = () => {
    setCheckItems([...checkItems, '']);
  };

  const handleRemoveItem = (index) => {
    setCheckItems(checkItems.filter((_, i) => i !== index));
  };

  const handleItemChange = (index, value) => {
    const newItems = [...checkItems];
    newItems[index] = value;
    setCheckItems(newItems);
  };

  const handleBatchAdd = () => {
    const itemsText = prompt('请输入多个检查内容，使用分号";"分隔：\n\n示例：\n导航设备运行情况;通信设备运行情况;自动化设备运行情况');
    if (itemsText) {
      const newItems = itemsText
        .replace(/；/g, ';')  // 替换所有中文分号为英文分号（使用正则全局替换）
        .split(';')
        .map(item => item.trim())
        .filter(item => item);
      setCheckItems([...checkItems, ...newItems]);
      message.success(`已添加 ${newItems.length} 个检查内容`);
    }
  };

  const handleClearAll = () => {
    Modal.confirm({
      title: '清空确认',
      content: '确定要清空所有检查内容吗？',
      onOk: () => {
        setCheckItems([]);
        message.success('已清空所有检查内容');
      }
    });
  };

  return (
    <Modal
      visible={store.templateFormVisible}
      title={store.templateRecord.id ? '编辑检查表模板' : '新建检查表模板'}
      onCancel={() => {
        store.templateFormVisible = false;
        form.resetFields();
        setCheckItems([]);
        setSelectedProject('');
      }}
      width={800}
      footer={[
        <Button key="cancel" onClick={() => {
          store.templateFormVisible = false;
          form.resetFields();
          setCheckItems([]);
          setSelectedProject('');
        }}>取消</Button>,
        <Button key="submit" type="primary" onClick={handleSubmit}>保存</Button>
      ]}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item label="项目" rules={[{required: true, message: '请输入项目名称'}]}>
          <Input
            placeholder="请输入项目名称（如：导航、通信、自动化等）"
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
          />
        </Form.Item>

        <Divider />

        <Card
          title={`现场巡视检查内容 (${checkItems.length}项)`}
          size="small"
          extra={
            <Space>
              <Button size="small" onClick={handleBatchAdd}>批量添加</Button>
              <Button size="small" onClick={handleClearAll} danger>清空</Button>
              <Button type="primary" size="small" icon={<PlusOutlined/>} onClick={handleAddItem}>
                添加检查内容
              </Button>
            </Space>
          }
        >
          {checkItems.length > 0 ? (
            <div style={{ maxHeight: 400, overflowY: 'auto' }}>
              {checkItems.map((item, index) => (
                <Form.Item key={index} style={{ marginBottom: 8 }}>
                  <Space style={{ width: '100%' }} direction="vertical">
                    <Input
                      placeholder={`检查内容 ${index + 1}`}
                      value={item}
                      onChange={(e) => handleItemChange(index, e.target.value)}
                      addonAfter={
                        <MinusCircleOutlined
                          style={{ cursor: 'pointer', color: '#ff4d4f' }}
                          onClick={() => handleRemoveItem(index)}
                        />
                      }
                    />
                  </Space>
                </Form.Item>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: '#999', padding: 40 }}>
              <p>暂无检查内容</p>
              <p>点击"添加检查内容"或"批量添加"按钮开始添加</p>
            </div>
          )}
        </Card>
      </Form>
    </Modal>
  );
})

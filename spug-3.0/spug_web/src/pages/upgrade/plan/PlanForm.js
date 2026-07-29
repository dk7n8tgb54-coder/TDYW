/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, Select, AutoComplete, Button, message, Switch,
  Empty, Tooltip
} from 'antd';
import {
  PlusOutlined, MinusCircleOutlined, HolderOutlined
} from '@ant-design/icons';
import store from '../store';
import SystemSelect from '../components/SystemSelect';

const { Option } = Select;
const { TextArea } = Input;

const UPGRADE_TYPES = ['功能升级', 'Bug修复', '安全补丁', '性能优化'];

/**
 * 方案编辑弹窗 - 基本信息 + 预设步骤（支持原生 HTML5 拖拽排序）
 *
 * props:
 *   visible, title, initialValues, onSubmit, onCancel
 *   initialValues 为 null 表示新建；为对象（含 steps）表示编辑
 */
function PlanForm({ visible, title, initialValues, onSubmit, onCancel }) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState([]);
  const [dragIndex, setDragIndex] = useState(null);

  useEffect(() => {
    if (visible) {
      if (initialValues) {
        form.setFieldsValue({
          name: initialValues.name || '',
          description: initialValues.description || '',
          system: initialValues.system || undefined,
          upgrade_type: initialValues.upgrade_type || undefined,
        });
        setSteps((initialValues.steps || []).map(s => ({
          id: s.id,
          phase: s.phase || '',
          title: s.title || '',
          description: s.description || '',
          is_required: s.is_required !== false,
          sequence: s.sequence,
        })));
      } else {
        form.resetFields();
        setSteps([]);
      }
      setDragIndex(null);
    }
  }, [visible, initialValues, form]);

  function handleAddStep() {
    setSteps([...steps, {
      phase: '', title: '', description: '', is_required: true, sequence: steps.length + 1
    }]);
  }

  function handleStepChange(index, updatedStep) {
    const newSteps = [...steps];
    newSteps[index] = updatedStep;
    setSteps(newSteps);
  }

  function handleStepRemove(index) {
    setSteps(steps.filter((_, i) => i !== index).map((s, i) => ({ ...s, sequence: i + 1 })));
  }

  // === 原生 HTML5 拖拽排序 ===
  function handleDragStart(index) {
    setDragIndex(index);
  }

  function handleDragOver(e) {
    e.preventDefault(); // 允许 drop
  }

  function handleDrop(index) {
    if (dragIndex === null || dragIndex === index) return;
    const newSteps = [...steps];
    const [moved] = newSteps.splice(dragIndex, 1);
    newSteps.splice(index, 0, moved);
    setSteps(newSteps.map((s, i) => ({ ...s, sequence: i + 1 })));
    setDragIndex(null);
  }

  function handleOk() {
    form.validateFields().then(values => {
      const validSteps = steps.filter(s => (s.title || '').trim());
      if (!initialValues && validSteps.length === 0) {
        message.warning('请至少添加一个步骤');
        return;
      }
      setLoading(true);
      onSubmit({
        ...values,
        steps: validSteps.map((s, i) => ({
          phase: s.phase || '',
          title: s.title.trim(),
          description: s.description || '',
          is_required: s.is_required,
          sequence: i + 1,
        })),
      });
    });
  }

  return (
    <Modal
      title={title}
      visible={visible}
      onCancel={() => { setLoading(false); onCancel(); }}
      onOk={handleOk}
      confirmLoading={loading}
      width={780}
      destroyOnClose
    >
      <Form form={form} labelCol={{ span: 4 }} wrapperCol={{ span: 18 }}>
        <Form.Item
          name="name"
          label="方案名称"
          rules={[{ required: true, message: '请输入方案名称' }]}
        >
          <Input placeholder="请输入方案名称" />
        </Form.Item>
        <Form.Item name="description" label="方案描述">
          <TextArea rows={2} placeholder="方案用途描述（选填）" />
        </Form.Item>
        <Form.Item name="system" label="系统">
          <SystemSelect placeholder="请选择或输入系统" />
        </Form.Item>
        <Form.Item name="upgrade_type" label="升级类型">
          <Select allowClear placeholder="请选择升级类型（可选）">
            {UPGRADE_TYPES.map(t => (
              <Option value={t} key={t}>{t}</Option>
            ))}
          </Select>
        </Form.Item>
      </Form>

      <div style={{ marginTop: 16, borderTop: '1px solid #f0f0f0', paddingTop: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, alignItems: 'center' }}>
          <span>
            <strong>预设步骤</strong>
            <span style={{ marginLeft: 8, color: '#999', fontSize: 12 }}>拖拽行手柄可调整顺序</span>
          </span>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={handleAddStep}>
            添加步骤
          </Button>
        </div>
        {steps.length === 0 ? (
          <Empty description="暂无步骤，点击上方按钮添加" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          steps.map((step, index) => (
            <div
              key={index}
              draggable
              onDragStart={() => handleDragStart(index)}
              onDragOver={handleDragOver}
              onDrop={() => handleDrop(index)}
              style={{
                display: 'flex', alignItems: 'flex-start', marginBottom: 8, gap: 8,
                padding: '4px 4px',
                background: dragIndex === index ? '#e6f7ff' : 'transparent',
                border: '1px dashed transparent',
                borderRadius: 4,
              }}
            >
              <Tooltip title="拖拽排序">
                <HolderOutlined style={{ cursor: 'grab', lineHeight: '32px', color: '#999' }} />
              </Tooltip>
              <span style={{ lineHeight: '32px', color: '#999', minWidth: 24 }}>{index + 1}.</span>
              <AutoComplete
                value={step.phase || undefined}
                onChange={v => handleStepChange(index, { ...step, phase: v || '' })}
                options={(store.filterOptions.phases || []).map(p => ({ value: p }))}
                placeholder="阶段"
                allowClear
                style={{ width: 140 }}
                size="small"
                filterOption={(input, option) =>
                  (option.value || '').toLowerCase().includes((input || '').toLowerCase())
                }
              />
              <Input
                placeholder="步骤标题"
                value={step.title}
                onChange={e => handleStepChange(index, { ...step, title: e.target.value })}
                style={{ flex: 1 }}
              />
              <TextArea
                placeholder="步骤描述（选填）"
                value={step.description}
                onChange={e => handleStepChange(index, { ...step, description: e.target.value })}
                style={{ flex: 1, minHeight: 32 }}
                autoSize={{ minRows: 1, maxRows: 3 }}
              />
              <Switch
                checked={step.is_required}
                onChange={v => handleStepChange(index, { ...step, is_required: v })}
                checkedChildren="必选"
                unCheckedChildren="可选"
                style={{ minWidth: 56 }}
              />
              <Button
                type="text"
                danger
                icon={<MinusCircleOutlined />}
                onClick={() => handleStepRemove(index)}
              />
            </div>
          ))
        )}
      </div>
    </Modal>
  );
}

export default observer(PlanForm);

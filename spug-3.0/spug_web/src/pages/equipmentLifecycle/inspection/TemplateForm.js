/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 巡检模板新增/编辑弹窗（聚合提交）：模板 → 设备名称 → 检查内容。
 * - 一个模板多个设备名称；一个设备名称多个检查内容；
 * - 录入类型：choice（正常/不正常单选，候选项固定）与 text（数字/文本）；
 * - 编辑按数组顺序作为显示顺序；载荷中缺失的既有条目将被删除
 *   （历史巡检明细依靠快照，不受影响）。
 */
import React, {useState, useEffect} from 'react';
import {Modal, Form, Input, Select, Checkbox, Button, message} from 'antd';
import {MinusCircleOutlined, PlusOutlined} from '@ant-design/icons';
import store from './store';
import {NORMAL_ABNORMAL_CHOICES} from './constants';

const {TextArea} = Input;

function emptyItem() {
  return {key: Date.now() + Math.random(), name: '', input_type: 'choice',
    is_required: true};
}

function emptyDevice() {
  return {key: Date.now() + Math.random(), device_name: '', items: [emptyItem()]};
}

function devicesFromRecord(record) {
  return (record.devices || []).map(d => ({
    key: `d${d.id}`,
    id: d.id,
    device_name: d.device_name,
    items: (d.items || []).map(i => ({
      key: `i${i.id}`, id: i.id, name: i.name, input_type: i.input_type,
      is_required: !!i.is_required,
    })),
  }));
}

function validateDevices(devices) {
  for (const d of devices) {
    if (!d.device_name.trim()) {
      return '设备名称不能为空';
    }
    if (!d.items.length) {
      return `设备「${d.device_name}」请至少配置一个检查内容`;
    }
    for (const item of d.items) {
      if (!item.name.trim()) {
        return `设备「${d.device_name}」存在未填写的检查内容`;
      }
    }
  }
  return null;
}

function buildPayload(devices, values) {
  return {
    name: values.name,
    description: values.description || '',
    devices: devices.map(d => ({
      id: d.id,
      device_name: d.device_name.trim(),
      items: d.items.map(i => ({
        id: i.id,
        name: i.name.trim(),
        input_type: i.input_type,
        is_required: !!i.is_required,
      })),
    })),
  };
}

function ItemRow({item, onItemChange, onRemoveItem}) {
  return (
    <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginBottom: 6}}>
      <Input
        style={{width: 200}}
        maxLength={200}
        placeholder="检查内容"
        value={item.name}
        onChange={e => onItemChange(item.key, {name: e.target.value})}
      />
      <Select
        style={{width: 150}}
        value={item.input_type}
        onChange={v => onItemChange(item.key, {input_type: v})}
      >
        <Select.Option value="choice">正常/不正常</Select.Option>
        <Select.Option value="text">数字/文本</Select.Option>
      </Select>
      {item.input_type === 'choice' && (
        <span style={{color: '#999'}}>候选项：{NORMAL_ABNORMAL_CHOICES.join(' / ')}</span>
      )}
      <Checkbox
        checked={item.is_required}
        onChange={e => onItemChange(item.key, {is_required: e.target.checked})}
      >
        必填
      </Checkbox>
      <a style={{color: 'red'}} onClick={() => onRemoveItem(item.key)}>删除</a>
    </div>
  );
}

function DeviceBlock({device, removable, onDeviceChange, onRemoveDevice,
                      onItemChange, onRemoveItem, onAddItem}) {
  return (
    <div style={{border: '1px solid #f0f0f0', borderRadius: 4, padding: 12, marginBottom: 12}}>
      <div style={{marginBottom: 8}}>
        <span style={{fontWeight: 'bold'}}>设备名称：</span>
        <Input
          style={{width: 260}}
          maxLength={100}
          placeholder="如 1号收发信机（不关联系统）"
          value={device.device_name}
          onChange={e => onDeviceChange({device_name: e.target.value})}
        />
        {removable && (
          <a style={{marginLeft: 12, color: 'red'}} onClick={onRemoveDevice}>
            <MinusCircleOutlined/> 移除设备
          </a>
        )}
      </div>
      {device.items.map(item => (
        <ItemRow key={item.key} item={item}
                 onItemChange={onItemChange} onRemoveItem={onRemoveItem}/>
      ))}
      <Button
        size="small"
        type="dashed"
        icon={<PlusOutlined/>}
        onClick={onAddItem}
      >
        添加检查内容
      </Button>
    </div>
  );
}

function TemplateForm() {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [devices, setDevices] = useState([emptyDevice()]);
  const record = store.tplRecord;
  const isEdit = !!record;

  useEffect(() => {
    if (isEdit) {
      form.setFieldsValue({
        name: record.name,
        description: record.description,
      });
      setDevices(devicesFromRecord(record));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateDevice(key, patch) {
    setDevices(devices.map(d => (d.key === key ? {...d, ...patch} : d)));
  }

  function updateItem(deviceKey, itemKey, patch) {
    setDevices(devices.map(d => {
      if (d.key !== deviceKey) return d;
      return {...d, items: d.items.map(i => (i.key === itemKey ? {...i, ...patch} : i))};
    }));
  }

  function handleOk() {
    form.validateFields().then(values => {
      const error = validateDevices(devices);
      if (error) {
        message.error(error);
        return;
      }
      setSubmitting(true);
      store.saveTpl(buildPayload(devices, values), isEdit ? record.id : undefined)
        .then(() => {
          message.success(isEdit ? '模板已更新' : '模板已创建');
          store.tplFormVisible = false;
          store.fetchTplList();
        })
        .catch(() => {})
        .finally(() => setSubmitting(false));
    }).catch(() => {});
  }

  return (
    <Modal
      visible={store.tplFormVisible}
      title={isEdit ? '编辑巡检模板' : '新增巡检模板'}
      width={920}
      maskClosable={false}
      confirmLoading={submitting}
      onCancel={() => store.tplFormVisible = false}
      onOk={handleOk}
    >
      <Form form={form} labelCol={{span: 4}} wrapperCol={{span: 19}}>
        <Form.Item
          name="name"
          label="模板名称"
          rules={[{required: true, message: '请输入模板名称'}]}
        >
          <Input maxLength={100} placeholder="如 机房值班巡检"/>
        </Form.Item>
        <Form.Item name="description" label="模板说明">
          <TextArea rows={2} maxLength={500} placeholder="（选填）"/>
        </Form.Item>
      </Form>
      {devices.map(d => (
        <DeviceBlock key={d.key} device={d} removable={devices.length > 1}
                     onDeviceChange={patch => updateDevice(d.key, patch)}
                     onRemoveDevice={() => setDevices(devices.filter(x => x.key !== d.key))}
                     onItemChange={(itemKey, patch) => updateItem(d.key, itemKey, patch)}
                     onRemoveItem={itemKey => updateDevice(
                       d.key, {items: d.items.filter(x => x.key !== itemKey)})}
                     onAddItem={() => updateDevice(d.key, {items: [...d.items, emptyItem()]})}/>
      ))}
      <Button
        type="dashed"
        block
        icon={<PlusOutlined/>}
        onClick={() => setDevices([...devices, emptyDevice()])}
      >
        添加设备名称
      </Button>
    </Modal>
  );
}

export default TemplateForm;

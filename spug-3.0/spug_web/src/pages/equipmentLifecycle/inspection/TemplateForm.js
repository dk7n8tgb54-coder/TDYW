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
 * - 排版：设备卡片（序号徽标 + 灰色头部）+ 检查内容网格对齐行；
 *   样式集中定义在 index.less 的 .el-tpl-form 作用域内。
 */
import React, {useState, useEffect} from 'react';
import {Modal, Form, Input, Select, Checkbox, Button, Divider, Tooltip, message} from 'antd';
import {DeleteOutlined, PlusOutlined, QuestionCircleOutlined} from '@ant-design/icons';
import store from './store';

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

function ItemRow({item, index, onItemChange, onRemoveItem}) {
  return (
    <div className="el-tpl-item-row">
      <span className="el-tpl-row-no">{index}</span>
      <Input
        maxLength={200}
        placeholder="检查内容"
        value={item.name}
        onChange={e => onItemChange(item.key, {name: e.target.value})}
      />
      <Select
        value={item.input_type}
        onChange={v => onItemChange(item.key, {input_type: v})}
      >
        <Select.Option value="choice">正常/不正常</Select.Option>
        <Select.Option value="text">数字/文本</Select.Option>
      </Select>
      <span className="el-tpl-item-required">
        <Checkbox
          checked={item.is_required}
          onChange={e => onItemChange(item.key, {is_required: e.target.checked})}
        >
          必填
        </Checkbox>
      </span>
      <Tooltip title="删除该检查内容">
        <Button
          className="el-tpl-del-btn el-tpl-item-del"
          type="text"
          size="small"
          icon={<DeleteOutlined/>}
          onClick={() => onRemoveItem(item.key)}
        />
      </Tooltip>
    </div>
  );
}

function DeviceBlock({device, index, removable, onDeviceChange, onRemoveDevice,
                      onItemChange, onRemoveItem, onAddItem}) {
  return (
    <div className="el-tpl-device">
      <div className="el-tpl-device-head">
        <span className="el-tpl-device-no">{index}</span>
        <Input
          maxLength={100}
          placeholder="如 1号收发信机（不关联系统）"
          value={device.device_name}
          onChange={e => onDeviceChange({device_name: e.target.value})}
        />
        {removable && (
          <Button
            className="el-tpl-del-btn"
            type="text"
            size="small"
            icon={<DeleteOutlined/>}
            onClick={onRemoveDevice}
          >
            移除设备
          </Button>
        )}
      </div>
      <div className="el-tpl-device-body">
        <div className="el-tpl-items">
          <div className="el-tpl-items-head">
            <span/>
            <span>检查内容</span>
            <span>
              录入类型
              <Tooltip title="「正常/不正常」为勾选式填写；「数字/文本」为手工填写读数或情况说明">
                <QuestionCircleOutlined/>
              </Tooltip>
            </span>
            <span>必填</span>
            <span/>
          </div>
          {device.items.length === 0 && (
            <div className="el-tpl-items-empty">尚未配置检查内容，请点击下方按钮添加</div>
          )}
          {device.items.map((item, idx) => (
            <ItemRow key={item.key} item={item} index={idx + 1}
                     onItemChange={onItemChange} onRemoveItem={onRemoveItem}/>
          ))}
        </div>
        <Button
          size="small"
          type="dashed"
          block
          icon={<PlusOutlined/>}
          onClick={onAddItem}
        >
          添加检查内容
        </Button>
      </div>
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
      className="el-tpl-form"
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
      <Divider className="el-tpl-divider" orientation="left" plain>模板结构</Divider>
      <div className="el-tpl-tip">
        模板由一台或多台设备及各设备下的检查内容组成；巡检单生成时保存全量快照，后续修改模板不影响历史巡检单。
      </div>
      {devices.map((d, idx) => (
        <DeviceBlock key={d.key} device={d} index={idx + 1} removable={devices.length > 1}
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

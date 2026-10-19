/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 「设备管理 → 系统配置」维护入口 —— 建立初始配置（Modal）。
 * 初始建档是独立于配置变更的明确身份：记录基线值 + 建档来源（必填），
 * 建档人/建档时间由后端写入；建档后参数修改一律走配置变更流程。
 * 只有"干净"系统可建档（无建档/无配置值/无已生效变更），拦截原因由后端给出。
 */
import React, {useState, useEffect} from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Input, Select, Button, Alert, message} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {ValueInput} from '../systemConfig/SystemConfigChangeModal';
import maintainStore from './store';
import sharedStore from '../systemConfig/store';
import {renderConfigValue} from '../systemConfig/shared';

const {TextArea} = Input;

function buildBaselinePayload(values, rows) {
  const selectedParams = rows.filter(row => row.param);
  if (!selectedParams.length) {
    return {error: '请至少为一个配置参数填写基线值'};
  }
  const paramIds = new Set();
  for (const row of rows) {
    if (row.param && paramIds.has(row.param)) {
      return {error: '同一参数不能重复建档'};
    }
    if (row.param) paramIds.add(row.param);
  }
  const items = selectedParams.map(row => {
    const param = sharedStore.configItems.find(item => item.param === row.param) || {};
    let value = row.value;
    if (param.data_type === 'date' && value) value = value.format('YYYY-MM-DD');
    if (value === undefined || value === null) value = '';
    return {param: row.param, value};
  });
  return {
    payload: {
      source: values.source,
      remark: values.remark || '',
      items,
    },
  };
}

function SystemConfigBaselineModal() {  const [form] = Form.useForm();
  const [rows, setRows] = useState([{param: undefined, value: undefined}]);

  useEffect(() => {
    if (maintainStore.baselineFormVisible) {
      form.resetFields();
      setRows([{param: undefined, value: undefined}]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maintainStore.baselineFormVisible]);

  const updateRow = (index, patch) => {
    setRows(rows.map((row, i) => (i === index ? {...row, ...patch} : row)));
  };

  function addRow() {
    setRows([...rows, {param: undefined, value: undefined}]);
  }

  function removeRow(index) {
    const next = rows.filter((_, i) => i !== index);
    setRows(next.length ? next : [{param: undefined, value: undefined}]);
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      // 建档值不允许为空：后端强校验，前端提前拦截给出明确提示
      const emptyRow = rows.find(row => {
        if (!row.param) return false;
        const param = sharedStore.configItems.find(item => item.param === row.param) || {};
        if (param.data_type === 'bool') return row.value !== true && row.value !== false;
        return row.value === undefined || row.value === null || row.value === '';
      });
      if (emptyRow) {
        message.warning('已选参数的基线值不能为空；不需要建档的参数请删除该行');
        return;
      }
      const {payload, error} = buildBaselinePayload(values, rows);
      if (error) {
        message.warning(error);
        return;
      }
      maintainStore.submitBaseline(payload)
        .then(() => message.success('初始配置已建档'))
        .catch(() => {});
    }).catch(() => {
      // 表单校验失败：antd 已在字段上展示错误
    });
  }

  function renderRow(row, index) {
    const param = sharedStore.configItems.find(item => item.param === row.param);
    return (
      <div key={index} style={{display: 'flex', alignItems: 'flex-start', marginBottom: 8}}>
        <Select
          showSearch
          optionFilterProp="children"
          style={{width: 220, flexShrink: 0}}
          placeholder="选择参数"
          value={row.param}
          onChange={v => updateRow(index, {param: v, value: undefined})}
        >
          {sharedStore.configItems.map(item => (
            <Select.Option value={item.param} key={item.param}>
              {item.param_name}（{item.param_code}）
            </Select.Option>
          ))}
        </Select>
        <div style={{margin: '0 8px', flexShrink: 0, paddingTop: 5, whiteSpace: 'nowrap'}}>
          当前：<span style={{color: '#888'}}>{param ? renderConfigValue(param) : '-'}</span>
        </div>
        <div style={{flex: 1}}>
          <ValueInput
            dataType={param ? param.data_type : 'text'}
            options={param ? param.options : []}
            required
            value={row.value}
            onChange={v => updateRow(index, {value: v})}
          />
        </div>
        <Button type="link" onClick={() => removeRow(index)}>删除</Button>
      </div>
    );
  }

  return (
    <Modal
      title="建立初始配置"
      visible={maintainStore.baselineFormVisible}
      width={820}
      confirmLoading={maintainStore.isBaselineSubmitting}
      okText="建 档"
      onCancel={() => maintainStore.hideBaselineForm()}
      onOk={handleSubmit}
      maskClosable={false}
    >
      <Alert type="info" showIcon style={{marginBottom: 12}}
        message="初始建档记录系统基线值、建档人、建档时间与来源；建档后参数修改一律走配置变更流程。"/>
      <div style={{marginBottom: 4}}>基线参数（基线值）</div>
      {rows.map((row, index) => renderRow(row, index))}
      <Button type="dashed" block onClick={addRow} style={{marginBottom: 12}}>
        <PlusOutlined/> 添加参数
      </Button>
      <Form form={form} labelCol={{span: 5}} wrapperCol={{span: 18}}>
        <Form.Item label="建档来源" name="source"
          rules={[{required: true, message: '请填写建档来源（如验收文档、出厂技术资料）'}]}>
          <Input maxLength={200} placeholder="如：验收文档 / 出厂技术资料 / 人工核定"/>
        </Form.Item>
        <Form.Item label="备注" name="remark">
          <TextArea rows={2} maxLength={200} placeholder="选填"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default observer(SystemConfigBaselineModal);

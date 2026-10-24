/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板创建弹窗（2026-10-21，与 ExcelLedgerCreateModal 同构精简版）。
 *
 * - 打开时拉取 create-options（系统清单 + 生成周期选项，复用 Excel 同构
 *   语义：一模板一系统、周月维护=每周/每月、季维护=每航季）；
 * - 只创建模板容器（名称/类型/说明/适用系统/生成周期），表单内容在创建
 *   后进入编辑抽屉配置；生成周期允许"待配置"（不参与自动生成）；
 * - 创建成功回调 onCreated（父级打开编辑抽屉）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Form, Input, Modal, Radio, Select} from 'antd';
import {LEDGER_TYPE_TEXT} from '../constants';
import {formTemplateStore} from './formTemplateStore';

function FormTemplateCreateModal({visible, onCancel, onCreated}) {
  const [form] = Form.useForm();
  const store = formTemplateStore;
  const ledgerType = Form.useWatch('ledger_type', form) || 'week_month';
  const periods = store.createOptions
    && (store.createOptions.periods || {})[ledgerType];

  useEffect(() => {
    if (!visible) return;
    form.resetFields();
    form.setFieldsValue({ledger_type: 'week_month', system: undefined, generation_period: ''});
    store.openCreateModal();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const handleOk = () => {
    form.validateFields().then(values => {
      store.submitCreate(values).then(template => {
        onCreated && onCreated(template);
      }).catch(() => {});
    }).catch(() => {});
  };

  return (
    <Modal title="新建数字表单模板" visible={visible} confirmLoading={store.creating}
           destroyOnClose okText="创建并编辑表单" cancelText="取消"
           onOk={handleOk} onCancel={onCancel}>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="模板名称" rules={[
          {required: true, whitespace: true, message: '请输入模板名称'},
          {max: 100, message: '模板名称不能超过100个字'},
        ]}>
          <Input placeholder="如：设备周维护记录（数字表单）"/>
        </Form.Item>
        <Form.Item name="ledger_type" label="维护类型" rules={[{required: true}]}>
          <Radio.Group disabled={store.creating}>
            <Radio.Button value="week_month">{LEDGER_TYPE_TEXT.week_month}</Radio.Button>
            <Radio.Button value="seasonal">{LEDGER_TYPE_TEXT.seasonal}</Radio.Button>
          </Radio.Group>
        </Form.Item>
        <Form.Item name="system" label="适用系统（一模板对应一个系统，可稍后配置）">
          <Select allowClear placeholder="待配置（不参与本期自动生成）"
                  loading={!store.createOptions}>
            {(store.createOptions ? store.createOptions.systems : []).map(system => (
              <Select.Option key={system.id} value={system.id} disabled={!system.is_active}>
                {system.name}（{system.system_code}）{system.is_active ? '' : '（已停用）'}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="generation_period" label="生成周期">
          <Select allowClear placeholder="待配置">
            {(periods || []).map(period => (
              <Select.Option key={period.value} value={period.value}>{period.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="description" label="说明" rules={[{max: 500}]}>
          <Input.TextArea rows={2} placeholder="模板用途说明（选填）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default observer(FormTemplateCreateModal);

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录研判弹窗（2026-10 第二版）。
 * 一次研判动作完成：跟进结论（需要跟进/无需跟进/转为正式故障）+ 可选的
 * 影响判定、重要标记、研判人/时间/说明。
 * - 小问题只需给出跟进结论，不强制填写复杂字段；
 * - 转为正式故障必须填写研判说明，且不能同时标记需要跟进（后端独立校验）；
 * - 标记重要必须填写原因，履历只在普通 → 重要升级时由后端生成一次；
 * - 前端仅控制展示，权限与状态流转以后端校验为准；错误由 http 拦截器统一提示。
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Radio, Input, DatePicker, Select, Switch, Checkbox, message } from 'antd';
import moment from 'moment';
import store from './store';
import { FAULT_IMPACT_OPTIONS } from '../constants';

const {TextArea} = Input;

const OUTCOME_FOLLOW_UP = 'follow_up';
const OUTCOME_NO_FOLLOW_UP = 'no_follow_up';
const OUTCOME_CONVERT = 'convert_fault';

// 结论联动区使用 shouldUpdate 渲染属性模式（antd 4.21）
function OutcomeDetail({form, alreadyImportant}) {
  const outcome = form.getFieldValue('outcome');
  return (
    <>
      {outcome === OUTCOME_FOLLOW_UP && (
        <>
          <Form.Item name="follow_up_name" label="跟进人">
            <Input placeholder="跟进人姓名（选填，可多人顿号分隔）"/>
          </Form.Item>
          <Form.Item name="planned_handle_at" label="计划处理时间">
            <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm"
                        style={{width: '100%'}} placeholder="选填，待办超期判定依据"/>
          </Form.Item>
        </>
      )}
      {outcome === OUTCOME_CONVERT && (
        <Form.Item
          name="triage_note"
          label="研判说明"
          rules={[{required: true, message: '转为正式故障时必须填写研判说明'}]}
        >
          <TextArea rows={2} placeholder="说明确认依据，如：现场检查确认设备故障，需正式处置"/>
        </Form.Item>
      )}
      <Form.Item
        name="mark_important"
        label="纳入重要履历"
        valuePropName="checked"
        extra="重要运行记录会进入系统履历，须填写原因"
      >
        <Checkbox disabled={alreadyImportant}>标记为重要运行记录</Checkbox>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={(prev, cur) =>
        prev.mark_important !== cur.mark_important}>
        {({getFieldValue}) => getFieldValue('mark_important') && !alreadyImportant ? (
          <Form.Item
            name="importance_reason"
            label="重要原因"
            preserve={false}
            rules={[{required: true, message: '标记重要时必须填写原因'}]}
          >
            <Input placeholder="标记为重要的原因（必填）"/>
          </Form.Item>
        ) : null}
      </Form.Item>
    </>
  );
}

const TriageModal = observer(function TriageModal({visible, onClose}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const d = store.detail;
  const alreadyImportant = d.importance === 'important';

  useEffect(() => {
    if (visible) {
      form.resetFields();
      form.setFieldsValue({
        outcome: OUTCOME_NO_FOLLOW_UP,
        affects_system_operation: !!d.affects_system_operation,
        impact_status: d.impact_status || undefined,
        triaged_at: moment(),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  function handleSubmit() {
    form.validateFields().then(values => {
      setLoading(true);
      const payload = {
        needs_follow_up: values.outcome === OUTCOME_FOLLOW_UP,
        convert_to_fault: values.outcome === OUTCOME_CONVERT,
        triage_note: values.triage_note || '',
        mark_important: !!values.mark_important && !alreadyImportant,
        importance_reason: values.importance_reason || '',
        triaged_by_name: values.triaged_by_name || '',
        triaged_at: values.triaged_at
          ? values.triaged_at.format('YYYY-MM-DD HH:mm') : '',
        follow_up_name: values.follow_up_name || '',
        planned_handle_at: values.planned_handle_at
          ? values.planned_handle_at.format('YYYY-MM-DD HH:mm') : '',
      };
      if (values.affects_system_operation !== undefined) {
        payload.affects_system_operation = !!values.affects_system_operation;
        payload.impact_status = values.impact_status || '';
      }
      store.submitTriage(payload)
        .then(() => {
          message.success('研判结论已保存');
          setLoading(false);
          onClose();
        })
        .catch(() => setLoading(false));
    }).catch(() => {});
  }

  return (
    <Modal
      visible={visible}
      title={`研判 - ${d.record_no || ''}`}
      confirmLoading={loading}
      maskClosable={false}
      destroyOnClose
      onCancel={() => {
        onClose();
        form.resetFields();
      }}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item
          name="outcome"
          label="跟进结论"
          rules={[{required: true, message: '请选择跟进结论'}]}
        >
          <Radio.Group>
            <Radio value={OUTCOME_FOLLOW_UP}>需要跟进</Radio>
            <Radio value={OUTCOME_NO_FOLLOW_UP}>无需跟进</Radio>
            <Radio value={OUTCOME_CONVERT}>转为正式故障</Radio>
          </Radio.Group>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, cur) =>
          prev.outcome !== cur.outcome ||
          prev.mark_important !== cur.mark_important}>
          {() => <OutcomeDetail form={form} alreadyImportant={alreadyImportant}/>}
        </Form.Item>
        <MetaFields form={form}/>
      </Form>
    </Modal>
  );
});

// 影响判定 + 研判人/时间/说明（独立小组件，避免弹窗主组件过长）
function MetaFields({form}) {
  return (
    <>
      <Form.Item
        name="affects_system_operation"
        label="影响系统运行"
        valuePropName="checked"
        extra="影响运行时请选择影响程度；普通记录升级为影响运行会从确认时写入系统履历"
      >
        <Switch checkedChildren="影响" unCheckedChildren="不影响"/>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={(prev, cur) =>
        prev.affects_system_operation !== cur.affects_system_operation}>
        {({getFieldValue}) => getFieldValue('affects_system_operation') ? (
          <Form.Item
            name="impact_status"
            label="影响程度"
            preserve={false}
            rules={[{required: true, message: '请选择影响程度'}]}
          >
            <Select placeholder="降级 / 故障 / 中断">
              {FAULT_IMPACT_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        ) : null}
      </Form.Item>
      <Form.Item name="triaged_by_name" label="研判人">
        <Input placeholder="缺省当前登录用户，可手输姓名"/>
      </Form.Item>
      <Form.Item
        name="triaged_at"
        label="研判时间"
        rules={[{required: true, message: '请选择研判时间'}]}
      >
        <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm"
                    style={{width: '100%'}}/>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={(prev, cur) =>
        prev.outcome !== cur.outcome}>
        {({getFieldValue}) => getFieldValue('outcome') !== OUTCOME_CONVERT ? (
          <Form.Item name="triage_note" label="研判说明">
            <TextArea rows={2} placeholder="选填；转为正式故障时必须填写"/>
          </Form.Item>
        ) : null}
      </Form.Item>
    </>
  );
}

export default TriageModal;

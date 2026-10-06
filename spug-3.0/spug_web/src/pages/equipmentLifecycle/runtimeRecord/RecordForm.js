/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行异常记录新增/编辑弹窗（2026-10 第一版；2026-10-04 信息
 * 分层收敛；2026-10-05 第四版研判不再是必经步骤）。
 * - 统一录入入口：用户不需要先判断"故障/事件/其他类型"，只描述运行情况；
 * - 表单承载"运行事实"：所属系统/发生时间/标题/情况描述/登记人 五项必填 +
 *   异常类别 选填（登记人 2026-10 新增，参照故障登记人：手输姓名、不预填
 *   登录账号）；具体对象名称/对象型号/影响系统运行（含影响程度）已删除
 *   （2026-10-06），不再出现在表单中；
 * - "标记重要"已删除（2026-10-06）：新增/详情均不再提供重要程度设置；
 * - 不再提供 跟进安排（跟进人/计划处理时间）与处理过程（已采取措施/
 *   处理结果）、原因判断（初步原因/影响范围）录入——跟进由"开始跟进 +
 *   首条跟进记录"触发，处理过程统一在处理进展时间线追加（历史字段后端
 *   保留，详情页以"历史记录"只读展示，不在此编辑）；
 * - 新增成功即"已记录"，用户可以直接离开，无需任何研判或关闭操作；
 * - 新增时生成 client_token 幂等令牌防重复提交；
 * - 不提供"故障/维护/配置变更/升级"类型选择——各业务由各自模块负责。
 */
import React, { useState, useEffect, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Select, Input, DatePicker, message } from 'antd';
import moment from 'moment';
import store from './store';
import { RUNTIME_CATEGORY_OPTIONS } from '../constants';

const {TextArea} = Input;

// 幂等令牌：同一表单会话内唯一即可（后端按租户 + client_token 防重复创建）
function makeClientToken() {
  return `rt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function SystemOptionLabel({system}) {
  if (!system) return null;
  return (
    <span>
      {system.name}
      <span style={{color: '#bbb', marginLeft: 6}}>{system.install_location}</span>
    </span>
  );
}

// 编辑回填只带事实字段；跟进/处理等历史字段不进编辑表单
// （后端对未提交字段保留原值，历史数据不受编辑影响）
function applyDetailToForm(form, detail) {
  form.setFieldsValue({
    system: detail.system,
    occurred_at: detail.occurred_at ? moment(detail.occurred_at, 'YYYY-MM-DD HH:mm') : null,
    title: detail.title,
    description: detail.description,
    category: detail.category || undefined,
  });
}

function SystemFields({systems}) {
  return (
    <>
      <Form.Item
        name="system"
        label="所属系统"
        rules={[{required: true, message: '请选择所属系统'}]}
      >
        <Select
          showSearch
          optionFilterProp="children"
          placeholder="请选择所属系统（显示名称、安装地点）"
          allowClear
        >
          {systems.map(s => (
            <Select.Option value={s.id} key={s.id}>
              <SystemOptionLabel system={s}/>
            </Select.Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item
        name="occurred_at"
        label="发生时间"
        rules={[{required: true, message: '请选择发生时间'}]}
      >
        <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
      </Form.Item>
      <Form.Item
        name="title"
        label="标题"
        rules={[
          {required: true, message: '请填写标题'},
          {max: 200, message: '长度不能超过 200'},
        ]}
      >
        <Input placeholder="一句话概括运行情况，如 主用链路短暂中断"/>
      </Form.Item>
      <Form.Item
        name="description"
        label="情况描述"
        rules={[
          {required: true, message: '请填写情况描述'},
          {max: 2000, message: '长度不能超过 2000'},
        ]}
      >
        <TextArea rows={3} placeholder="只描述发生了什么、观察到了什么；原因判断与处理过程在处理进展中追加"/>
      </Form.Item>
    </>
  );
}

// 登记人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），只表示
// 实际添加这条运行异常记录的人，与登录账号审计字段独立；
// 必填、不预填默认姓名（参照故障登记人口径）。
// 仅新增可填，编辑不渲染（后端保留原登记人）
function RegistrarFields({isEdit}) {
  if (isEdit) return null;
  return (
    <Form.Item
      name="registrar_names"
      label="登记人"
      rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
    >
      {/* open=false：仅手输姓名（回车/失焦添加），与故障登记人输入一致 */}
      <Select
        mode="tags"
        open={false}
        placeholder="输入姓名后回车确认（可多个）"
      />
    </Form.Item>
  );
}

// 结构化事实字段（第二版）：全部选填，不增加录入负担；
// 具体对象名称/对象型号/影响系统运行（含影响程度）已删除（2026-10-06）
function FactFields() {
  return (
    <Form.Item name="category" label="异常类别">
      <Select allowClear placeholder="（选填）设备/信号/链路/供电/环境/软件等">
        {RUNTIME_CATEGORY_OPTIONS.map(item => (
          <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
        ))}
      </Select>
    </Form.Item>
  );
}

const RecordForm = observer(function RecordForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);
  const record = store.record;
  const isEdit = !!record.id;

  useEffect(() => {
    mountedRef.current = true;
    return () => {mountedRef.current = false;};
  }, []);

  useEffect(() => {
    if (!isEdit) return;
    setLoading(true);
    store.fetchDetailById(record.id)
      .then(detail => {
        if (!mountedRef.current) return;
        applyDetailToForm(form, detail);
      })
      .catch(() => {})
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSubmit() {
    form.validateFields().then(values => {
      const payload = {
        ...values,
        occurred_at: values.occurred_at ? values.occurred_at.format('YYYY-MM-DD HH:mm') : null,
        // 标签数组以顿号拼接为登记人姓名文本（多人）
        registrar_name: (values.registrar_names || []).join('、'),
      };
      delete payload.registrar_names;
      if (isEdit) {
        // 登记人仅新增可填：编辑不提交该键，后端保留原登记人
        delete payload.registrar_name;
        // 事实字段未提交时后端保留原值（措施/结果/原因等历史字段
        // 不在编辑表单中，编辑不会触碰）
      } else {
        // 幂等令牌：同一表单提交多次只创建一条记录
        payload.client_token = makeClientToken();
      }
      setLoading(true);
      store.submitForm(payload)
        .then(() => {
          if (mountedRef.current) {
            message.success(isEdit ? '运行异常记录已更新' : '运行异常记录已创建（已记录），可直接离开或开始跟进');
          }
        })
        .catch(() => {})
        .finally(() => {
          if (mountedRef.current) setLoading(false);
        });
    }).catch(() => {});
  }

  return (
    <Modal
      visible={store.formVisible}
      title={isEdit ? '编辑运行异常记录' : '新增运行异常记录'}
      width={760}
      maskClosable={false}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <SystemFields systems={store.systems}/>
        <RegistrarFields isEdit={isEdit}/>
        <FactFields/>
      </Form>
    </Modal>
  );
});

export default RecordForm;

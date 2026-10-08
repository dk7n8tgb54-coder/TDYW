/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录新增/编辑弹窗（2026-10 第一版；2026-10-04 信息
 * 分层收敛；2026-10-05 第四版研判不再是必经步骤；2026-10-07 模块更名
 * "运行记录"并扩展 record_type，兼容日常运行记录与异常事件记录）。
 * - 记录类型（record_type）：日常运行（routine）/ 异常事件（abnormal），
 *   新增时 Radio 选择（默认日常运行），创建后不可修改（编辑时禁用）；
 * - 公共字段（两种类型一致）：所属系统/发生时间/标题/情况描述/登记人 +
 *   类别选填（异常事件显示"异常类别"、日常运行显示"记录类别"，同一
 *   后端 category 字段）；
 * - 类型专属字段：
 *   · 日常运行：作业内容/操作结果或检查结果（复用后端 measures_taken/
 *     handling_result 字段），不进入异常研判、跟进、转故障流程；
 *   · 异常事件：沿用既有异常字段与流程；
 * - "标记重要"已删除（2026-10-06）：新增/详情均不再提供重要程度设置；
 * - 跟进安排（跟进人/计划处理时间，2026-10-06 已删除）与处理过程、原因
 *   判断不进表单——异常事件的跟进由"追加处理进展"触发，处理过程统一在
 *   处理进展工作区追加（历史字段后端保留，详情页不展示，不在此编辑）；
 * - 新增成功即"已记录"，用户可以直接离开，无需任何研判或关闭操作；
 * - 新增时生成 client_token 幂等令牌防重复提交；
 * - 不提供"故障/维护/配置变更/升级"类型选择——各业务由各自模块负责。
 */
import React, { useState, useEffect, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Select, Input, DatePicker, Radio, message } from 'antd';
import moment from 'moment';
import store from './store';
import { RUNTIME_CATEGORY_OPTIONS, RUNTIME_RECORD_TYPE_OPTIONS } from '../constants';

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
// 日常运行记录的作业内容/操作结果（measures_taken/handling_result）随类型回填
function applyDetailToForm(form, detail) {
  form.setFieldsValue({
    record_type: detail.record_type || 'abnormal',
    system: detail.system,
    occurred_at: detail.occurred_at ? moment(detail.occurred_at, 'YYYY-MM-DD HH:mm') : null,
    title: detail.title,
    description: detail.description,
    category: detail.category || undefined,
    measures_taken: detail.record_type === 'routine' ? (detail.measures_taken || '') : undefined,
    handling_result: detail.record_type === 'routine' ? (detail.handling_result || '') : undefined,
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
        <Input placeholder="一句话概括运行情况，如 UPS电源切换及南山UPS电池检查紧固"/>
      </Form.Item>
      <Form.Item
        name="description"
        label="情况描述"
        rules={[
          {required: true, message: '请填写情况描述'},
          {max: 2000, message: '长度不能超过 2000'},
        ]}
      >
        <TextArea rows={3} placeholder="只描述发生了什么、观察到了什么；异常事件的原因判断与处理过程在处理进展中追加"/>
      </Form.Item>
    </>
  );
}

// 记录类型（2026-10-07）：新增必选（默认日常运行），创建后不可修改
// （编辑时禁用；后端对不一致值独立拒绝）。
// onChange 双通道：Form.Item 注入的 onChange 更新表单值，随后调用原
// onChange 同步本地 state 驱动类型专属字段显隐
function RecordTypeFields({isEdit, onChange}) {
  return (
    <Form.Item
      name="record_type"
      label="记录类型"
      initialValue="routine"
      rules={[{required: true, message: '请选择记录类型'}]}
    >
      <Radio.Group
        disabled={isEdit}
        onChange={e => onChange && onChange(e.target.value)}
      >
        {RUNTIME_RECORD_TYPE_OPTIONS.map(item => (
          <Radio value={item.value} key={item.value}>{item.label}</Radio>
        ))}
      </Radio.Group>
    </Form.Item>
  );
}

// 登记人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），只表示
// 实际添加这条运行记录的人，与登录账号审计字段独立；
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

// 类别（公共字段，选填）：同一后端 category 字段按记录类型展示口径——
// 异常事件"异常类别"、日常运行"记录类别"
function FactFields({recordType}) {
  return (
    <Form.Item name="category" label={recordType === 'routine' ? '记录类别' : '异常类别'}>
      <Select allowClear placeholder="（选填）设备/信号/链路/供电/环境/软件等">
        {RUNTIME_CATEGORY_OPTIONS.map(item => (
          <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
        ))}
      </Select>
    </Form.Item>
  );
}

// 日常运行专属：作业内容/操作结果或检查结果（复用后端 measures_taken/
// handling_result 字段承载，语义一致，不新增重复列）
function RoutineFields() {
  return (
    <>
      <Form.Item
        name="measures_taken"
        label="作业内容"
        rules={[{max: 1000, message: '长度不能超过 1000'}]}
      >
        <TextArea rows={3} placeholder="（选填）本次执行的作业内容，如 UPS电源切换、电池检查紧固等"/>
      </Form.Item>
      <Form.Item
        name="handling_result"
        label="操作结果/检查结果"
        rules={[{max: 1000, message: '长度不能超过 1000'}]}
      >
        <TextArea rows={3} placeholder="（选填）作业完成情况或检查结论"/>
      </Form.Item>
    </>
  );
}

// 异常事件专属字段已随"记录关联"功能整体移除（2026-10-07，用户决策）：
// 异常事件沿用既有异常字段，无关联日常运行选择器

const RecordForm = observer(function RecordForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);
  const record = store.record;
  const isEdit = !!record.id;
  // 记录类型驱动类型专属字段显隐（Form.Item 未挂载的字段不出现在提交值中，
  // 提交时再按类型显式组装，避免 antd preserve 把切换前残留值带给后端）
  const [recordType, setRecordType] = useState(record.record_type || 'routine');

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
        setRecordType(detail.record_type || 'abnormal');
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
      const isRoutine = recordType === 'routine';
      // 类型专属字段按当前记录类型显式组装：日常运行提交作业内容/操作结果；
      // 异常事件无类型专属字段；切换类型前残留的 Form 值（preserve）不提交
      if (isRoutine) {
        // 作业内容/操作结果提交
      } else {
        delete payload.measures_taken;
        delete payload.handling_result;
      }
      if (isEdit) {
        // 登记人仅新增可填：编辑不提交该键，后端保留原登记人
        delete payload.registrar_name;
        // record_type 创建后不可修改：编辑不提交该键
        delete payload.record_type;
      } else {
        // 新前端显式传值；幂等令牌：同一表单提交多次只创建一条记录
        payload.record_type = recordType;
        payload.client_token = makeClientToken();
      }
      setLoading(true);
      store.submitForm(payload)
        .then(() => {
          if (mountedRef.current) {
            message.success(isEdit ? '运行记录已更新' : '运行记录已创建（已记录），可直接离开或开始跟进');
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
      title={isEdit ? '编辑运行记录' : '新增运行记录'}
      width={760}
      maskClosable={false}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <RecordTypeFields isEdit={isEdit} onChange={setRecordType}/>
        <SystemFields systems={store.systems}/>
        <RegistrarFields isEdit={isEdit}/>
        <FactFields recordType={recordType}/>
        {recordType === 'routine' && <RoutineFields/>}
      </Form>
    </Modal>
  );
});

export default RecordForm;

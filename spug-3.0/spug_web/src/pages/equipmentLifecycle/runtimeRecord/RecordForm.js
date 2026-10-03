/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录新增/编辑弹窗（2026-10 第一版）。
 * - 统一录入入口：用户不需要先判断"故障/事件/其他类型"，只描述运行情况；
 * - 第一屏显示 所属系统/发生时间/标题/情况描述/登记人 五项必填
 *   （登记人 2026-10 新增，参照故障登记人：手输姓名、不预填登录账号）；
 * - 通过"更多信息"展开可选字段：需要跟进 / 影响系统运行(+程度) /
 *   已采取措施 / 处理结果 / 重要程度(+原因)；附件在详情页上传
 *   （新建阶段对象尚不存在，无临时附件回填模式）；
 * - 新增时生成 client_token 幂等令牌防重复提交；
 * - 标记重要必须填写原因（后端独立校验）；
 * - 不提供"故障/维护/配置变更/升级"类型选择——各业务由各自模块负责。
 */
import React, { useState, useEffect, useRef } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Select, Input, DatePicker, Switch, Button, message } from 'antd';
import { DownOutlined, UpOutlined } from '@ant-design/icons';
import moment from 'moment';
import store from './store';
import { FAULT_IMPACT_OPTIONS, RUNTIME_CATEGORY_OPTIONS } from '../constants';

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

function applyDetailToForm(form, detail) {
  form.setFieldsValue({
    system: detail.system,
    occurred_at: detail.occurred_at ? moment(detail.occurred_at, 'YYYY-MM-DD HH:mm') : null,
    title: detail.title,
    description: detail.description,
    needs_follow_up: !!detail.needs_follow_up,
    affects_system_operation: !!detail.affects_system_operation,
    impact_status: detail.impact_status || undefined,
    measures_taken: detail.measures_taken,
    handling_result: detail.handling_result,
    object_name: detail.object_name,
    object_model: detail.object_model,
    category: detail.category || undefined,
    initial_reason: detail.initial_reason,
    impact_scope: detail.impact_scope,
  });
}

function RequiredFields({systems, isEdit}) {
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
        <TextArea rows={3} placeholder="描述观察到的运行情况（不必判断是否为故障）"/>
      </Form.Item>
      <RegistrarFields isEdit={isEdit}/>
    </>
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

function OptionalFields({isEdit}) {
  return (
    <>
      <Form.Item
        name="needs_follow_up"
        label="需要跟进"
        valuePropName="checked"
        extra="开启后可在详情中标记为跟进中，持续记录处理进展"
      >
        <Switch checkedChildren="需要" unCheckedChildren="不需要"/>
      </Form.Item>
      <Form.Item
        name="affects_system_operation"
        label="影响系统运行"
        valuePropName="checked"
        extra="默认不影响运行；影响运行时请选择影响程度（该记录会进入系统履历）"
      >
        <Switch checkedChildren="影响" unCheckedChildren="不影响"/>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={
        (prev, cur) => prev.affects_system_operation !== cur.affects_system_operation
      }>
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
      <Form.Item name="measures_taken" label="已采取措施">
        <TextArea rows={2} placeholder="（选填）已经采取的临时或正式措施"/>
      </Form.Item>
      <Form.Item name="handling_result" label="处理结果">
        <TextArea rows={2} placeholder="（选填）当前处理结果，普通小问题可直接处理后关闭"/>
      </Form.Item>
      {/* 结构化补充字段（第二版）：全部选填，不增加录入负担；
          转正式故障时随转换带入故障对象/原因字段 */}
      <Form.Item name="category" label="异常类别">
        <Select allowClear placeholder="（选填）设备/信号/链路/供电/环境/软件等">
          {RUNTIME_CATEGORY_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item name="object_name" label="具体对象名称">
        <Input placeholder="（选填）如 DVOR 信标机"/>
      </Form.Item>
      <Form.Item name="object_model" label="对象型号/编号">
        <Input placeholder="（选填）如 VR12 / 序列号"/>
      </Form.Item>
      <Form.Item name="initial_reason" label="初步原因">
        <Input placeholder="（选填）如 疑为功放模块老化"/>
      </Form.Item>
      <Form.Item name="impact_scope" label="影响范围">
        <Input placeholder="（选填）如 本场航路导航、通信指挥"/>
      </Form.Item>
      {!isEdit && <ImportanceFields/>}
    </>
  );
}

// 重要程度仅新增表单提供（创建时直接标记重要须填原因）；编辑不渲染——
// 记录从普通升级为重要走详情页"标记重要"动作（履历只从升级时生成）。
function ImportanceFields() {
  return (
    <>
      <Form.Item
        name="importance"
        label="重要程度"
        initialValue="normal"
        extra="标记为重要的记录会进入系统履历"
      >
        <Select>
          <Select.Option value="normal">普通</Select.Option>
          <Select.Option value="important">重要</Select.Option>
        </Select>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={
        (prev, cur) => prev.importance !== cur.importance
      }>
        {({getFieldValue}) => getFieldValue('importance') === 'important' ? (
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

const RecordForm = observer(function RecordForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [moreVisible, setMoreVisible] = useState(false);
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
        setMoreVisible(true);
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
        // 重要程度仅新增表单提供：编辑提交不携带该键，后端保留原值
        delete payload.importance;
        delete payload.importance_reason;
        // 登记人仅新增可填：编辑不提交该键，后端保留原登记人
        delete payload.registrar_name;
      } else {
        // 幂等令牌：同一表单提交多次只创建一条记录
        payload.client_token = makeClientToken();
      }
      setLoading(true);
      store.submitForm(payload)
        .then(() => {
          if (mountedRef.current) message.success(isEdit ? '运行记录已更新' : '运行记录已创建');
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
      <Form
        form={form}
        labelCol={{span: 6}}
        wrapperCol={{span: 16}}
        initialValues={{affects_system_operation: false, needs_follow_up: false}}
      >
        <RequiredFields systems={store.systems} isEdit={isEdit}/>
        {moreVisible ? (
          <OptionalFields isEdit={isEdit}/>
        ) : (
          <Form.Item wrapperCol={{offset: 6, span: 16}}>
            <Button
              type="link"
              icon={<DownOutlined/>}
              onClick={() => setMoreVisible(true)}
            >
              需要跟进或更多信息（影响程度、措施、结果、重要程度）
            </Button>
          </Form.Item>
        )}
        {moreVisible && !isEdit && (
          <Form.Item wrapperCol={{offset: 6, span: 16}}>
            <Button
              type="link"
              icon={<UpOutlined/>}
              onClick={() => setMoreVisible(false)}
            >
              收起更多信息
            </Button>
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
});

export default RecordForm;

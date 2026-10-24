/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行处置记录新增/编辑弹窗（2026-10-11 合并改造）。
 * 统一表单承载三种记录类型（record_type，创建后不可修改，编辑时禁用）：
 * - 一般记录（routine）：简洁录入（系统/发生时间/标题/情况描述/登记人 +
 *   记录类别选填），不进入故障状态机；
 * - 异常事件（abnormal）：同上 + 异常类别；可在详情页认定设备故障；
 * - 设备故障（fault）：直接登记（须 operation_record.add_fault 权限），
 *   额外展示故障专用字段：影响系统运行开关 + 影响程度（影响运行时必填）/
 *   故障等级（选填固定四级）/ 故障部位设备（选填）/初步原因分析（选填）；
 *   创建即"处置中"。
 * 故障专用字段只在直接登记故障（或详情认定故障弹窗）时显示；
 * 编辑提交不携带登记人（后端保留原登记人）；未提交的对象快照/原因分析
 * 字段后端保留原值，不静默清空历史数据。
 * 2026-10-14 体验二轮：类型选项附用途说明（选中即在下方展示），无
 * add_fault 权限时"设备故障"选项前置禁用并说明（不让用户填完才被拒）；
 * 登记人输入附确认方式说明；提交中防重复触发。
 */
import React, {useState, useEffect, useRef} from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Select, Input, DatePicker, Radio, Switch, Alert, message} from 'antd';
import moment from 'moment';
import {hasPermission} from 'libs';
import store from './store';
import {
  PERM, RECORD_CATEGORY_OPTIONS, RECORD_TYPE_OPTIONS, RECORD_TYPE_HINTS,
  FAULT_IMPACT_OPTIONS, FAULT_LEVEL_OPTIONS,
} from '../constants';

const {TextArea} = Input;

// 幂等令牌：同一表单会话内唯一即可（后端按租户 + client_token 防重复创建）
function makeClientToken() {
  return `op-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
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

// 编辑回填：公共事实字段 + 故障专用字段（未提交键后端保留原值）
function applyDetailToForm(form, detail) {
  form.setFieldsValue({
    system: detail.system,
    occurred_at: detail.occurred_at ? moment(detail.occurred_at, 'YYYY-MM-DD HH:mm') : null,
    title: detail.title,
    description: detail.description,
    category: detail.category || undefined,
    affects_system_operation: detail.record_type === 'fault'
      ? !!detail.affects_system_operation : false,
    impact_status: detail.impact_status || undefined,
    fault_level: detail.fault_level || undefined,
    fault_object_name: detail.fault_object_name,
    reason_analysis: detail.reason_analysis,
  });
}

// 记录类型（新增必选，默认一般记录；创建后不可修改——编辑时禁用，
// 后端对不一致值独立拒绝）。onChange 双通道：Form.Item 注入的 onChange 更新
// 表单值，随后调用原 onChange 同步本地 state 驱动故障字段显隐。
// 选中类型在下方展示用途说明；无 add_fault 权限时"设备故障"选项前置禁用
// （不让用户填完表单才被后端拒绝，后端仍独立校验权限）
function RecordTypeFields({isEdit, recordType, onChange}) {
  const faultAllowed = hasPermission(PERM.OP_ADD_FAULT);
  return (
    <>
      <Form.Item
        name="record_type"
        label="记录类型"
        initialValue="routine"
        rules={[{required: true, message: '请选择记录类型'}]}
        extra="创建后类型不可修改；不同类型进入不同的处置流程"
      >
        <Radio.Group
          disabled={isEdit}
          onChange={e => onChange && onChange(e.target.value)}
        >
          {RECORD_TYPE_OPTIONS.map(item => (
            <Radio
              value={item.value}
              key={item.value}
              disabled={item.value === 'fault' && !faultAllowed && !isEdit}
            >
              {item.label}
            </Radio>
          ))}
        </Radio.Group>
      </Form.Item>
      {RECORD_TYPE_HINTS[recordType] && (
        <Alert
          type="info"
          showIcon
          style={{marginBottom: 16}}
          message={RECORD_TYPE_HINTS[recordType]}
        />
      )}
      {!faultAllowed && !isEdit && (
        <p style={{color: 'rgba(0, 0, 0, 0.45)', margin: '0 0 16px'}}>
          "设备故障"需要单独授权（operation_record.add_fault）；如需登记故障请联系管理员，
          或先登记"异常事件"再在详情中认定。
        </p>
      )}
    </>
  );
}

// 登记人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），只表示
// 实际添加这条记录的人，与登录账号审计字段独立；必填、不预填默认姓名。
// 仅新增可填，编辑不渲染（后端保留原登记人）
function RegistrarFields({isEdit}) {
  if (isEdit) return null;
  return (
    <Form.Item
      name="registrar_names"
      label="登记人"
      rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
      extra="输入姓名后按回车（或移开焦点）确认，姓名会成为灰色标签；可连续添加多位"
    >
      {/* open=false：仅手输姓名（回车/失焦添加），与原故障登记人输入一致 */}
      <Select
        mode="tags"
        open={false}
        placeholder="输入姓名后回车确认（可多个）"
      />
    </Form.Item>
  );
}

// 类别（选填）：一般记录显示"记录类别"、异常事件显示"异常类别"；
// 设备故障不适用（后端拒绝）
function CategoryField({recordType}) {
  if (recordType === 'fault') return null;
  return (
    <Form.Item name="category" label={recordType === 'routine' ? '记录类别' : '异常类别'}>
      <Select allowClear placeholder="（选填）设备/信号/链路/供电/环境/软件等">
        {RECORD_CATEGORY_OPTIONS.map(item => (
          <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
        ))}
      </Select>
    </Form.Item>
  );
}

// 设备故障专用字段块（2026-10-11 合并改造）：只在 record_type=fault 时渲染。
// 默认"部件故障但不影响系统运行"；影响程度依"影响系统运行"开关显隐
// （preserve=false：关闭时不残留已选值提交后端）
function FaultFields() {
  return (
    <>
      <div style={{
        fontWeight: 600, margin: '4px 0 16px',
        borderTop: '1px dashed #e8e8e8', paddingTop: 12,
      }}>
        故障登记（设备故障专用）
      </div>
      <Form.Item
        name="affects_system_operation"
        label="影响系统运行"
        valuePropName="checked"
        extra="默认关闭：部件故障、离线维修不影响系统对外服务；开启后按影响程度参与系统健康状态计算"
      >
        <Switch checkedChildren="影响" unCheckedChildren="不影响"/>
      </Form.Item>
      <Form.Item noStyle shouldUpdate={
        (prev, cur) => prev.affects_system_operation !== cur.affects_system_operation
      }>
        {({getFieldValue}) => getFieldValue('affects_system_operation') ? (
          <Form.Item
            name="impact_status"
            label="系统影响程度"
            preserve={false}
            rules={[{required: true, message: '请选择系统影响程度'}]}
          >
            <Select placeholder="降级 / 故障 / 中断">
              {FAULT_IMPACT_OPTIONS.map(item => (
                <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
              ))}
            </Select>
          </Form.Item>
        ) : null}
      </Form.Item>
      <Form.Item
        name="fault_level"
        label="故障等级"
        extra="选填：按运维规程固定四级，处置过程中可在编辑中修改"
      >
        <Select allowClear placeholder="一级 / 二级 / 三级 / 四级">
          {FAULT_LEVEL_OPTIONS.map(item => (
            <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
          ))}
        </Select>
      </Form.Item>
      <Form.Item name="fault_object_name" label="故障部位/设备">
        <Input placeholder="故障的部位或设备，如 信道机 / 天馈系统（选填）"/>
      </Form.Item>
      <Form.Item name="reason_analysis" label="初步原因分析">
        <TextArea
          rows={2}
          placeholder="已知时填写，暂时无法判断可留空，处置过程中可继续补充"
        />
      </Form.Item>
    </>
  );
}

// 公共事实字段（三种记录类型一致）：所属系统/发生时间/标题/情况描述
function BaseFields({systems}) {
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
            {store.systems.map(s => (
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
          <Input placeholder="一句话概括运行情况或故障"/>
        </Form.Item>
        <Form.Item
          name="description"
          label="情况描述"
          rules={[
            {required: true, message: '请填写情况描述'},
            {max: 2000, message: '长度不能超过 2000'},
          ]}
        >
          <TextArea rows={3} placeholder="只描述发生了什么、观察到了什么；处理过程在记录详情的进展页签中追加"/>
        </Form.Item>
    </>
  );
}

const RecordForm = observer(function RecordForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);
  const record = store.record;
  const isEdit = !!record.id;
  // 记录类型驱动故障字段显隐（Form.Item 未挂载的字段不出现在提交值中，
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
        setRecordType(detail.record_type || 'routine');
      })
      .catch(() => {})
      .finally(() => {
        if (mountedRef.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSubmit() {
    // 提交中防重复：确认按钮 loading 已禁点，这里再挡住回车等重复触发
    if (loading) return;
    form.validateFields().then(values => {
      const payload = {
        ...values,
        occurred_at: values.occurred_at ? values.occurred_at.format('YYYY-MM-DD HH:mm') : null,
        // 标签数组以顿号拼接为登记人姓名文本（多人）
        registrar_name: (values.registrar_names || []).join('、'),
      };
      delete payload.registrar_names;
      const isFault = recordType === 'fault';
      if (!isFault) {
        // 一般记录/异常事件：故障专用字段不提交（切换类型前残留值不带给后端）
        delete payload.affects_system_operation;
        delete payload.impact_status;
        delete payload.fault_level;
        delete payload.fault_object_name;
        delete payload.fault_object_model;
        delete payload.fault_object_sn;
        delete payload.reason_analysis;
      } else if (form.isFieldTouched('fault_level')) {
        // 等级被触碰过才显式提交（含清空后的空串=未选择）；未触碰不提交，
        // 后端保留原值（编辑回填值原样带上无害，防御详情拉取失败的空表单误清）
        payload.fault_level = values.fault_level || '';
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
            message.success(isEdit ? '记录已更新'
              : isFault ? '故障已登记（处置中）' : '记录已创建（已记录），可直接离开或开始跟进');
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
      title={isEdit ? '编辑记录' : '新增记录'}
      width={760}
      style={{maxWidth: 'calc(100vw - 24px)'}}
      maskClosable={false}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}
        initialValues={{affects_system_operation: false}}>
        <RecordTypeFields isEdit={isEdit} recordType={recordType} onChange={setRecordType}/>
        <BaseFields systems={store.systems}/>
        <RegistrarFields isEdit={isEdit}/>
        <CategoryField recordType={recordType}/>
        {recordType === 'fault' && <FaultFields/>}
      </Form>
    </Modal>
  );
});

export default RecordForm;

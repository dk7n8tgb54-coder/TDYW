/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 「设备管理 → 系统配置」维护入口 —— 参数定义新增/编辑（Modal）。
 * - 分类必选：硬件规格=整套系统静态规格（如系统额定功率、容量；仅属于某台
 *   设备的规格不得登记为系统规格）；运行参数=可调整设定值；
 * - 编码创建后不可修改；枚举类型须提供 ≥2 个选项；校验正则仅文本类型生效；
 * - 停用保留全部历史记录（参数定义无删除接口）；敏感词（密码/令牌/密钥）
 *   由后端拒绝保存。
 */
import React, {useEffect} from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Input, Select, Switch, Radio, message} from 'antd';
import maintainStore from './store';
import {
  PARAM_TYPE_OPTIONS, PARAM_CATEGORY_OPTIONS, PARAM_CATEGORY_RUNTIME,
} from '../constants';

const {TextArea} = Input;

const PARAM_CODE_PATTERN = /^[a-z][a-z0-9_]{1,49}$/;

const TYPE_OPTIONS = PARAM_TYPE_OPTIONS.map(item => (
  <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
));

const CATEGORY_OPTIONS = PARAM_CATEGORY_OPTIONS.map(item => (
  <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
));

// 表单字段区（渲染在 Form 上下文内，经 form 实例与外层 Modal 关联）
function ParamFormFields({form, editing, systemOptions}) {
  const typeValue = Form.useWatch('data_type', form);
  const scopeValue = Form.useWatch('scope_type', form);
  return (
    <React.Fragment>
      <Form.Item label="参数编码" name="param_code"
        rules={[
          {required: true, message: '请填写参数编码'},
          {pattern: PARAM_CODE_PATTERN, message: '小写字母开头，仅含小写字母/数字/下划线，2-50 位'},
        ]}>
        <Input maxLength={50} disabled={editing} placeholder="如 rated_power（创建后不可修改）"/>
      </Form.Item>
      <Form.Item label="参数名称" name="param_name"
        rules={[{required: true, message: '请填写参数名称'}]}>
        <Input maxLength={100} placeholder="如 系统额定功率"/>
      </Form.Item>
      <Form.Item label="参数分类" name="category"
        rules={[{required: true, message: '请选择参数分类'}]}
        extra="硬件规格描述整套系统（如额定功率/容量），单台设备的规格请勿登记为系统规格；运行参数是可调整的设定值。">
        <Select placeholder="请选择分类">{CATEGORY_OPTIONS}</Select>
      </Form.Item>
      <Form.Item label="数据类型" name="data_type"
        rules={[{required: true, message: '请选择数据类型'}]}>
        <Select placeholder="请选择类型">{TYPE_OPTIONS}</Select>
      </Form.Item>
      {typeValue === 'choice' && (
        <Form.Item label="枚举选项" name="enum_options"
          rules={[
            {required: true, message: '枚举类型必须提供至少 2 个选项'},
            {validator: (_, value) => (
              !value || value.length >= 2 ? Promise.resolve() : Promise.reject(new Error('至少 2 个选项'))
            )},
          ]}>
          <Select mode="tags" open={false} tokenSeparators={[',', '，']}
            placeholder="输入选项后回车，至少 2 个（如 主用 / 备用）"/>
        </Form.Item>
      )}
      <Form.Item label="单位" name="unit">
        <Input maxLength={20} placeholder="选填，如 dB、MHz、kW"/>
      </Form.Item>
      <Form.Item label="适用范围" name="scope_type"
        rules={[{required: true, message: '请选择适用范围'}]}>
        <Radio.Group>
          <Radio value="all">全部系统</Radio>
          <Radio value="specific">指定系统</Radio>
        </Radio.Group>
      </Form.Item>
      {scopeValue === 'specific' && (
        <Form.Item label="适用系统" name="system_ids"
          rules={[{required: true, message: '指定系统范围时必须选择至少一个适用系统'}]}>
          <Select mode="multiple" showSearch optionFilterProp="children"
            placeholder="选择适用的系统">
            {systemOptions.map(system => (
              <Select.Option value={system.id} key={system.id}>
                {system.name}（{system.system_code}{system.is_active ? '' : '，已停用'}）
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
      )}
      <Form.Item label="必填" name="is_required" valuePropName="checked"
        extra="必填参数在记录变更时不允许提交空值。">
        <Switch/>
      </Form.Item>
      {typeValue === 'text' && (
        <Form.Item label="校验正则" name="validation_regex"
          extra="选填，仅对文本类型生效；填入后值必须完整匹配该正则。">
          <Input maxLength={200} placeholder="如 ^[0-9A-Za-z\\-]+$"/>
        </Form.Item>
      )}
      {editing && (
        <Form.Item label="启用" name="is_enabled" valuePropName="checked"
          extra="停用后不再出现在当前配置与变更候选中，历史记录全部保留。">
          <Switch/>
        </Form.Item>
      )}
      <Form.Item label="备注" name="remark">
        <TextArea rows={2} maxLength={200} placeholder="选填"/>
      </Form.Item>
    </React.Fragment>
  );
}

function SystemConfigParamModal() {
  const [form] = Form.useForm();
  const editing = !!maintainStore.paramRecord;

  useEffect(() => {
    if (maintainStore.paramFormVisible) {
      const record = maintainStore.paramRecord || {};
      form.setFieldsValue({
        param_code: record.param_code,
        param_name: record.param_name,
        category: record.category || PARAM_CATEGORY_RUNTIME,
        data_type: record.data_type || 'text',
        unit: record.unit || '',
        scope_type: record.scope_type || 'all',
        system_ids: record.system_ids || [],
        is_required: !!record.is_required,
        enum_options: record.options || [],
        validation_regex: record.validation_regex || '',
        is_enabled: record.id ? !!record.is_enabled : true,
        remark: record.remark || '',
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maintainStore.paramFormVisible, maintainStore.paramRecord]);

  function buildPayload(values) {
    return {
      param_code: values.param_code,
      param_name: values.param_name,
      category: values.category,
      data_type: values.data_type,
      unit: values.unit || '',
      scope_type: values.scope_type,
      system_ids: values.scope_type === 'specific' ? (values.system_ids || []) : [],
      is_required: !!values.is_required,
      enum_options: values.data_type === 'choice' ? (values.enum_options || []) : [],
      validation_regex: values.data_type === 'text' ? (values.validation_regex || '') : '',
      is_enabled: values.is_enabled !== false,
      remark: values.remark || '',
    };
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      const payload = buildPayload(values);
      maintainStore.submitParam(payload, maintainStore.paramRecord && maintainStore.paramRecord.id)
        .then(() => message.success('参数定义已保存'))
        .catch(() => {});
    }).catch(() => {
      // 表单校验失败：antd 已在字段上展示错误
    });
  }

  return (
    <Modal
      title={editing ? '编辑参数定义' : '新增参数定义'}
      visible={maintainStore.paramFormVisible}
      width={640}
      confirmLoading={maintainStore.isParamSubmitting}
      okText="保 存"
      onCancel={() => maintainStore.hideParamForm()}
      onOk={handleSubmit}
      maskClosable={false}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 17}}>
        <ParamFormFields
          form={form}
          editing={editing}
          systemOptions={maintainStore.systemOptions}
        />
      </Form>
      {editing && (
        <div style={{color: '#888', fontSize: 12}}>
          参数编码创建后不可修改；停用参数不删除，历史记录全部保留。
        </div>
      )}
    </Modal>
  );
}

export default observer(SystemConfigParamModal);

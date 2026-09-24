/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统新增/编辑弹窗（聚合提交）。
 * 统一包含：固定基础字段 + 已有自定义字段 + 本次临时新增自定义字段 +
 * 配置组成项；一次填写、一次提交，无需先保存系统再补录字段值。
 * 有 system_config.field 权限的用户可在表单内联新增自定义字段（字段定义
 * 由后端生成稳定编码并随本次提交一并创建）。
 */
import React, { useState, useEffect, useRef } from 'react';
import moment from 'moment';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, InputNumber, Select, DatePicker, Row, Col, Button, Divider,
  Tag, Switch, message,
} from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { AuthButton } from 'components';
import store from './store';
import { HEALTH_STATUS_COLOR, FIELD_TYPE_OPTIONS, PERM } from './constants';
import DynamicFieldControl, { parseChoices } from './DynamicFieldControl';

const {TextArea} = Input;

// 内联新增字段不开放附件/明细表：附件依赖已创建的系统，明细表列定义请在系统详情「配置字段」页签管理
const INLINE_FIELD_TYPE_OPTIONS = FIELD_TYPE_OPTIONS.filter(
  item => item.value !== 'attachment' && item.value !== 'detail_table');

function isEmptyValue(value) {
  if (value === undefined || value === null || value === '') return true;
  if (Array.isArray(value) && value.length === 0) return true;
  return false;
}

function sameDynamicValue(a, b) {
  return JSON.stringify(a === undefined ? '' : a) === JSON.stringify(b === undefined ? '' : b);
}

function SystemForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [fieldsLoading, setFieldsLoading] = useState(false);
  const [dynamicFields, setDynamicFields] = useState([]);
  const [fieldValues, setFieldValues] = useState({});
  const [tempFields, setTempFields] = useState([]);
  const [components, setComponents] = useState([]);
  const [componentsLoaded, setComponentsLoaded] = useState(false);
  const [defModalVisible, setDefModalVisible] = useState(false);
  const mountedRef = useRef(true);
  const baselineRef = useRef({});
  const displayRef = useRef({});
  const tempSeqRef = useRef(0);
  useEffect(() => () => { mountedRef.current = false; }, []);
  const record = store.record;
  const isEdit = !!record.id;

  useEffect(() => {
    if (!isEdit) return;
    form.setFieldsValue({
      name: record.name,
      system_model: record.system_model,
      install_location: record.install_location,
      geo_coordinate: record.geo_coordinate,
      system_purpose: record.system_purpose,
      manufacturer: record.manufacturer,
      install_unit: record.install_unit,
      use_unit: record.use_unit,
      install_time: record.install_time ? moment(record.install_time) : undefined,
      enable_time: record.enable_time ? moment(record.enable_time) : undefined,
      responsible_user_name: record.responsible_user_name,
      remark: record.remark,
    });
    setFieldsLoading(true);
    store.fetchFormFields({system: record.id})
      .then(res => {
        if (!mountedRef.current) return;
        const list = res.data || [];
        const values = {};
        const baseline = {};
        const displays = {};
        list.forEach(f => {
          const entry = res.values ? res.values[String(f.id)] : null;
          const raw = entry ? entry.value : '';
          values[f.id] = raw;
          baseline[f.id] = raw;
          displays[f.id] = entry ? entry.display : '';
        });
        baselineRef.current = baseline;
        displayRef.current = displays;
        setDynamicFields(list);
        setFieldValues(values);
        setComponents((res.components || []).map(c => ({...c, __key: `exist_${c.id}`})));
        setComponentsLoaded(true);
      })
      .catch(() => {})
      .finally(() => {
        if (mountedRef.current) setFieldsLoading(false);
      });
  }, []);

  const addTempField = (spec) => {
    tempSeqRef.current += 1;
    const clientKey = `temp_${tempSeqRef.current}`;
    const field = {
      id: clientKey,
      client_key: clientKey,
      scope_type: 'custom',
      display_name: spec.display_name,
      field_type: spec.field_type,
      is_required: !!spec.is_required,
      is_sensitive: !!spec.is_sensitive,
      is_exportable: !!spec.is_exportable,
      help_text: spec.help_text || '',
      display_order: 1000 + tempSeqRef.current,
      choices_parsed: spec.choices_parsed || [],
      number_min: spec.number_min === undefined ? null : spec.number_min,
      number_max: spec.number_max === undefined ? null : spec.number_max,
      text_regex: spec.text_regex || '',
      is_active: true,
      is_temp: true,
    };
    setTempFields(prev => [...prev, field]);
    setFieldValues(prev => ({...prev, [clientKey]: ''}));
  };

  const removeTempField = (clientKey) => {
    setTempFields(prev => prev.filter(f => f.client_key !== clientKey));
    setFieldValues(prev => {
      const next = {...prev};
      delete next[clientKey];
      return next;
    });
  };

  const addComponent = () => {
    setComponents(prev => [...prev, {
      __key: `new_${Date.now()}_${prev.length}`,
      name: '', category: '', model_version: '', quantity: undefined,
      purpose: '', remark: '',
    }]);
  };

  const updateComponent = (key, patch) => {
    setComponents(prev => prev.map(c => (c.__key === key ? {...c, ...patch} : c)));
  };

  const removeComponent = (key) => {
    setComponents(prev => prev.filter(c => c.__key !== key));
  };

  const validateDynamicRequired = () => {
    const missing = [];
    dynamicFields.filter(f => f.is_active !== false && f.is_required).forEach(f => {
      const value = fieldValues[f.id];
      const hasDefault = !isEmptyValue(f.default_parsed);
      if (isEmptyValue(value) && !hasDefault) missing.push(f.display_name);
    });
    tempFields.filter(f => f.is_required).forEach(f => {
      if (isEmptyValue(fieldValues[f.client_key])) missing.push(f.display_name);
    });
    return missing;
  };

  const buildCustomFieldSpec = (f) => ({
    client_key: f.client_key,
    name: f.display_name,
    field_type: f.field_type,
    required: !!f.is_required,
    value: fieldValues[f.client_key] === undefined ? '' : fieldValues[f.client_key],
    choices: f.choices_parsed || [],
    number_min: f.number_min === null || f.number_min === undefined ? null : f.number_min,
    number_max: f.number_max === null || f.number_max === undefined ? null : f.number_max,
    text_regex: f.text_regex || '',
    help_text: f.help_text || '',
    is_sensitive: !!f.is_sensitive,
    is_exportable: !!f.is_exportable,
  });

  function buildPayload(values) {
    const system = {
      name: values.name,
      system_model: values.system_model,
      install_location: values.install_location,
      geo_coordinate: values.geo_coordinate || '',
      system_purpose: values.system_purpose || '',
      manufacturer: values.manufacturer,
      install_unit: values.install_unit,
      use_unit: values.use_unit,
      install_time: values.install_time ? values.install_time.format('YYYY-MM-DD HH:mm') : undefined,
      enable_time: values.enable_time ? values.enable_time.format('YYYY-MM-DD HH:mm') : undefined,
      responsible_user_name: values.responsible_user_name,
      remark: values.remark || '',
    };
    // 系统编号由后端自动生成，前端不传
    const payload = {system};

    const activeFields = dynamicFields.filter(f => f.is_active !== false);
    if (isEdit) {
      // 只提交发生变化的已有字段值，后端对比前后值记录变更历史
      const configValues = {};
      activeFields.forEach(f => {
        const current = fieldValues[f.id] === undefined ? '' : fieldValues[f.id];
        if (!sameDynamicValue(current, baselineRef.current[f.id])) {
          configValues[f.id] = current;
        }
      });
      if (Object.keys(configValues).length > 0) payload.config_values = configValues;
    }
    if (tempFields.length > 0) {
      payload.custom_fields = tempFields.map(buildCustomFieldSpec);
    }
    // 新增模式恒提交组成项（可为空数组）；编辑模式仅在成功加载过时提交（全量同步）
    if (!isEdit || componentsLoaded) {
      payload.components = components.map((c, idx) => ({
        id: c.id,
        name: c.name,
        category: c.category || '',
        model_version: c.model_version || '',
        quantity: c.quantity === undefined || c.quantity === null || c.quantity === ''
          ? null : Number(c.quantity),
        purpose: c.purpose || '',
        asset_sn: c.asset_sn || '',
        external_ref: c.external_ref || '',
        remark: c.remark || '',
        display_order: c.display_order === undefined ? idx : c.display_order,
      }));
    }
    return payload;
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      const missing = validateDynamicRequired();
      if (missing.length > 0) {
        message.error(`以下必填字段未填写：${missing.join('、')}`);
        return;
      }
      setLoading(true);
      store.submitForm(buildPayload(values))
        .catch(() => {})
        .finally(() => {
          if (mountedRef.current) setLoading(false);
        });
    }).catch(() => {});
  }

  const renderDynamicItem = (field, isTemp = false) => {
    const key = isTemp ? field.client_key : field.id;
    const value = fieldValues[key] === undefined ? '' : fieldValues[key];
    return (
      <Form.Item
        key={key}
        label={(
          <span>
            {field.display_name}
            {field.is_required && <span style={{color: '#f5222d'}}> *</span>}
            {field.is_sensitive && <Tag color="orange" style={{marginLeft: 6}}>敏感</Tag>}
            {isTemp && <Tag color="blue" style={{marginLeft: 6}}>本次新增</Tag>}
          </span>
        )}
        extra={field.help_text}
      >
        <div style={{display: 'flex', alignItems: 'flex-start'}}>
          <div style={{flex: 1, minWidth: 0}}>
            <DynamicFieldControl
              field={field}
              value={value}
              systemId={isEdit ? record.id : 0}
              onChange={v => setFieldValues(prev => ({...prev, [key]: v}))}
            />
          </div>
          {isTemp && (
            <a
              style={{marginLeft: 8, lineHeight: '32px', whiteSpace: 'nowrap'}}
              onClick={() => removeTempField(field.client_key)}
            >
              移除
            </a>
          )}
        </div>
      </Form.Item>
    );
  };

  const activeDynamic = dynamicFields.filter(f => f.is_active !== false);
  const customFields = activeDynamic.filter(f => f.scope_type === 'custom');
  const inactiveFields = dynamicFields.filter(f => f.is_active === false);

  return (
    <Modal
      visible
      width={960}
      maskClosable={false}
      title={isEdit ? '编辑系统' : '新增系统'}
      okText={isEdit ? '保 存' : '确 定'}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 17}}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="name"
              label="系统名称"
              rules={[{required: true, message: '请输入系统名称'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入系统正式名称"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="system_model"
              label="系统型号"
              rules={[{required: true, message: '请输入系统型号'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入系统型号"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="install_location"
              label="安装地点"
              rules={[{required: true, message: '请输入安装地点'}, {max: 200, message: '长度不能超过 200'}]}
            >
              <Input placeholder="请输入安装地点"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="geo_coordinate"
              label="安装经纬度"
              rules={[{pattern: /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/, message: '格式: 经度,纬度'}]}
            >
              <Input placeholder="选填，格式: 经度,纬度"/>
            </Form.Item>
          </Col>
        </Row>
        <Form.Item labelCol={{span: 3}} wrapperCol={{span: 20}} name="system_purpose" label="系统用途"
                   rules={[{max: 500, message: '长度不能超过 500'}]}>
          <TextArea rows={2} placeholder="选填"/>
        </Form.Item>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="manufacturer"
              label="生产厂家"
              rules={[{required: true, message: '请输入生产厂家'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入生产厂家"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="install_unit"
              label="安装单位"
              rules={[{required: true, message: '请输入安装单位'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入安装单位"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="use_unit"
              label="使用单位"
              rules={[{required: true, message: '请输入使用单位'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入使用单位"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="install_time" label="安装时间" rules={[{required: true, message: '请选择安装时间'}]}>
              <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="enable_time" label="启用时间" rules={[{required: true, message: '请选择启用时间'}]}>
              <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="responsible_user_name"
              label="系统负责人"
              rules={[{required: true, message: '请输入系统负责人'}, {max: 100, message: '长度不能超过 100'}]}
            >
              <Input placeholder="请输入负责人姓名"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="运行健康状态" tooltip="由故障与工单统一计算，不能手动修改">
              {isEdit && record.health_status_text
                ? <Tag color={HEALTH_STATUS_COLOR[record.health_status]} style={{fontSize: 14, padding: '2px 10px'}}>
                    {record.health_status_text}
                  </Tag>
                : <Tag color={HEALTH_STATUS_COLOR.normal} style={{fontSize: 14, padding: '2px 10px'}}>正常</Tag>}
            </Form.Item>
          </Col>
        </Row>
        <Form.Item labelCol={{span: 3}} wrapperCol={{span: 20}} name="remark" label="备注"
                   rules={[{max: 1000, message: '长度不能超过 1000'}]}>
          <TextArea rows={2} placeholder="选填"/>
        </Form.Item>

        {fieldsLoading && <div style={{color: '#999', marginBottom: 8}}>正在加载字段……</div>}
        {customFields.length > 0 && (
          <Divider orientation="left" plain>系统自定义字段</Divider>
        )}
        {customFields.map(f => renderDynamicItem(f))}
        {tempFields.length > 0 && (
          <Divider orientation="left" plain>本次新增自定义字段</Divider>
        )}
        {tempFields.map(f => renderDynamicItem(f, true))}
        <AuthButton
          auth={PERM.CFG_FIELD}
          type="dashed"
          block
          icon={<PlusOutlined/>}
          onClick={() => setDefModalVisible(true)}
        >
          添加自定义字段
        </AuthButton>
        {dynamicFields.length === 0 && !isEdit && (
          <div style={{color: '#999', marginTop: 8}}>
            如需扩展字段，可点击上方「添加自定义字段」。
          </div>
        )}

        {inactiveFields.length > 0 && (
          <>
            <Divider orientation="left" plain>已停用字段（历史值只读）</Divider>
            {inactiveFields.map(f => (
              <Form.Item
                key={f.id}
                label={(
                  <span>
                    {f.display_name}
                    <Tag style={{marginLeft: 6}}>已停用</Tag>
                  </span>
                )}
              >
                <Input disabled value={displayRef.current[f.id] || '-'}/>
              </Form.Item>
            ))}
          </>
        )}

        <Divider orientation="left" plain>配置组成项</Divider>
        {components.map((comp, idx) => (
          <Row key={comp.__key || comp.id || idx} gutter={8} style={{marginBottom: 8}}>
            <Col span={5}>
              <Input
                placeholder="名称（必填）"
                value={comp.name}
                onChange={e => updateComponent(comp.__key, {name: e.target.value})}
              />
            </Col>
            <Col span={4}>
              <Input
                placeholder="类别"
                value={comp.category}
                onChange={e => updateComponent(comp.__key, {category: e.target.value})}
              />
            </Col>
            <Col span={4}>
              <Input
                placeholder="型号/版本"
                value={comp.model_version}
                onChange={e => updateComponent(comp.__key, {model_version: e.target.value})}
              />
            </Col>
            <Col span={3}>
              <InputNumber
                placeholder="数量"
                min={0}
                style={{width: '100%'}}
                value={comp.quantity}
                onChange={v => updateComponent(comp.__key, {quantity: v === undefined ? '' : v})}
              />
            </Col>
            <Col span={6}>
              <Input
                placeholder="备注"
                value={comp.remark}
                onChange={e => updateComponent(comp.__key, {remark: e.target.value})}
              />
            </Col>
            <Col span={2}>
              <Button
                type="link"
                icon={<DeleteOutlined/>}
                onClick={() => removeComponent(comp.__key)}
              >
                删除
              </Button>
            </Col>
          </Row>
        ))}
        <Button type="dashed" block icon={<PlusOutlined/>} onClick={addComponent}>
          添加组成项
        </Button>
      </Form>
      {defModalVisible && (
        <CustomFieldDefModal
          onClose={() => setDefModalVisible(false)}
          onSaved={(spec) => {
            setDefModalVisible(false);
            addTempField(spec);
          }}
        />
      )}
    </Modal>
  );
}

/**
 * 内联新增自定义字段定义弹窗：只定义字段，不在此填写字段值；
 * 保存定义后字段立即加入当前表单，值随本次系统保存一并提交。
 */
function CustomFieldDefModal({onClose, onSaved}) {
  const [form] = Form.useForm();
  const [fieldType, setFieldType] = useState('text');
  const isChoice = fieldType === 'choice' || fieldType === 'multi_choice';

  function handleSubmit() {
    form.validateFields().then(values => {
      const spec = {
        display_name: values.display_name,
        field_type: values.field_type,
        is_required: !!values.is_required,
        is_sensitive: !!values.is_sensitive,
        is_exportable: !!values.is_exportable,
        help_text: values.help_text || '',
        text_regex: values.text_regex || '',
        number_min: values.number_min === undefined ? null : values.number_min,
        number_max: values.number_max === undefined ? null : values.number_max,
        choices_parsed: isChoice
          ? (values.choices_raw || '').split('\n').map(x => x.trim()).filter(Boolean)
          : [],
      };
      if (isChoice && spec.choices_parsed.length === 0) {
        message.error('单选/多选字段必须提供候选项');
        return;
      }
      onSaved(spec);
    }).catch(() => {});
  }

  return (
    <Modal
      visible
      title="添加自定义字段"
      maskClosable={false}
      okText="添 加"
      cancelText="取 消"
      onCancel={() => {
        form.resetFields();
        onClose();
      }}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}} initialValues={{field_type: 'text'}}>
        <Form.Item
          name="display_name"
          label="显示名称"
          rules={[{required: true, message: '请输入显示名称'}, {max: 100, message: '长度不能超过 100'}]}
        >
          <Input placeholder="如：天线高度"/>
        </Form.Item>
        <Form.Item name="field_type" label="字段类型" rules={[{required: true}]}>
          <Select onChange={v => setFieldType(v)}>
            {INLINE_FIELD_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        {isChoice && (
          <Form.Item
            name="choices_raw"
            label="候选项"
            extra="每行一个候选项"
            rules={[{required: true, message: '请输入候选项'}]}
          >
            <TextArea rows={3}/>
          </Form.Item>
        )}
        {fieldType === 'number' && (
          <Form.Item label="数值范围">
            <Input.Group compact>
              <Form.Item name="number_min" noStyle>
                <InputNumber placeholder="最小值" style={{width: '50%'}}/>
              </Form.Item>
              <Form.Item name="number_max" noStyle>
                <InputNumber placeholder="最大值" style={{width: '50%'}}/>
              </Form.Item>
            </Input.Group>
          </Form.Item>
        )}
        {fieldType === 'text' && (
          <Form.Item name="text_regex" label="格式校验" extra="选填，JavaScript 正则表达式">
            <Input placeholder="如 ^[0-9.]+MHz$"/>
          </Form.Item>
        )}
        <Form.Item name="help_text" label="帮助文字" rules={[{max: 200, message: '长度不能超过 200'}]}>
          <Input/>
        </Form.Item>
        <Form.Item name="is_required" label="是否必填" valuePropName="checked">
          <Switch/>
        </Form.Item>
        <Form.Item name="is_sensitive" label="敏感配置" valuePropName="checked">
          <Switch/>
        </Form.Item>
        <Form.Item name="is_exportable" label="允许导出" valuePropName="checked">
          <Switch/>
        </Form.Item>
      </Form>
      <div style={{color: '#999'}}>
        字段编码由系统自动生成；字段仅作用于本系统，保存定义后立即加入当前表单，
        填写值后随本次保存一并提交。附件与明细表字段请在系统创建后于系统详情的「配置字段」页签中定义。
      </div>
    </Modal>
  );
}

export default observer(SystemForm);

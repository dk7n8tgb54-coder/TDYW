/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情 → 配置页签 —— 记录配置变更（Modal，非独立页面）。
 * - 选择一个或多个配置参数，自动显示当前值，填写变更后值；
 * - 变更原因必填；可填写验证说明；可选是否纳入重要系统履历（须填原因）；
 * - 附件在变更创建成功后按收集到的文件依次上传到该变更下；
 * - 提交成功等待后端真实结果（先创建变更拿到编号，再传附件），不乐观更新。
 */
import React, {Fragment, useState, useEffect} from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Input, Select, InputNumber, DatePicker, Switch, Upload, Button, Alert, message} from 'antd';
import {PlusOutlined, UploadOutlined} from '@ant-design/icons';
import store from './store';

const {TextArea} = Input;

// 幂等令牌：同一表单会话内唯一即可（后端按租户 + client_token 防重复创建）
function makeClientToken() {
  return `cfg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

// 按参数数据类型渲染"变更后值"输入控件
function ValueInput({dataType, options, value, onChange, required}) {
  if (dataType === 'number') {
    return <InputNumber style={{width: '100%'}} value={value || null} onChange={onChange}
      placeholder={required ? '必填' : '选填'}/>;
  }
  if (dataType === 'bool') {
    return (
      <Select style={{width: '100%'}} value={value === null || value === undefined ? undefined : value}
        onChange={onChange} allowClear placeholder={required ? '必填' : '选填'}>
        <Select.Option value={true}>是</Select.Option>
        <Select.Option value={false}>否</Select.Option>
      </Select>
    );
  }
  if (dataType === 'date') {
    return (
      <DatePicker style={{width: '100%'}} value={value || null} onChange={onChange}
        placeholder={required ? '必填' : '选填'}/>
    );
  }
  if (dataType === 'choice') {
    return (
      <Select style={{width: '100%'}} value={value || undefined} onChange={onChange}
        allowClear placeholder={required ? '必填' : '选填'}>
        {(options || []).map(option => (
          <Select.Option value={option} key={option}>{option}</Select.Option>
        ))}
      </Select>
    );
  }
  return <Input value={value || ''} onChange={e => onChange(e.target.value)}
    maxLength={500} placeholder={required ? '必填' : '选填'}/>;
}

// 校验并组装提交 payload：至少一个参数、不重复、date 格式化；失败返回 {error}
function buildChangePayload(systemId, values, rows, configItems) {
  const selectedParams = rows.filter(row => row.param);
  if (!selectedParams.length) {
    return {error: '请至少选择一个配置参数'};
  }
  const paramIds = new Set();
  for (const row of rows) {
    if (row.param && paramIds.has(row.param)) {
      return {error: '同一参数不能重复提交'};
    }
    if (row.param) paramIds.add(row.param);
  }
  const items = selectedParams.map(row => {
    const param = configItems.find(item => item.param === row.param) || {};
    let new_value = row.new_value;
    if (param.data_type === 'date' && new_value) new_value = new_value.format('YYYY-MM-DD');
    if (new_value === undefined || new_value === null) new_value = '';
    return {param: row.param, new_value, remark: row.remark || ''};
  });
  return {
    payload: {
      system: systemId,
      reason: values.reason,
      items,
      include_in_history: !!values.include_in_history,
      history_reason: values.include_in_history ? values.history_reason : '',
      verify_note: values.verify_note || '',
      client_token: makeClientToken(),
    },
  };
}

const SystemConfigChangeModal = observer(function SystemConfigChangeModal({systemId}) {
  const [form] = Form.useForm();
  const [rows, setRows] = useState([{param: undefined, new_value: undefined, remark: ''}]);
  const [files, setFiles] = useState([]);
  const includeHistory = Form.useWatch('include_in_history', form) ||
    form.getFieldValue('include_in_history');

  useEffect(() => {
    if (store.formVisible) {
      form.resetFields();
      setRows([{param: undefined, new_value: undefined, remark: ''}]);
      setFiles([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.formVisible]);

  const updateRow = (index, patch) => {
    setRows(rows.map((row, i) => (i === index ? {...row, ...patch} : row)));
  };

  function addRow() {
    setRows([...rows, {param: undefined, new_value: undefined, remark: ''}]);
  }

  function removeRow(index) {
    const next = rows.filter((_, i) => i !== index);
    setRows(next.length ? next : [{param: undefined, new_value: undefined, remark: ''}]);
  }

  function collectFiles(file) {
    setFiles([...files, file]);
    return false;  // 阻止自动上传：变更创建成功后统一上传
  }

  function removeFile(file) {
    setFiles(files.filter(f => f.uid !== file.uid));
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      const {payload, error} = buildChangePayload(systemId, values, rows, store.configItems);
      if (error) {
        message.warning(error);
        return;
      }
      store.submitChange(systemId, payload, files)
        .then(() => {
          message.success('配置变更已保存');
        })
        .catch(() => {});
    }).catch(() => {
      // 表单校验失败：antd 已在字段上展示错误，无需额外处理
    });
  }

  function renderRow(row, index) {
    return (
      <ParamRow
        key={index}
        row={row}
        configItems={store.configItems}
        onParamChange={v => updateRow(index, {param: v, new_value: undefined})}
        onValueChange={v => updateRow(index, {new_value: v})}
        onRemarkChange={v => updateRow(index, {remark: v})}
        onRemove={() => removeRow(index)}
      />
    );
  }

  return (
    <Modal
      title="记录配置变更"
      visible={store.formVisible}
      width={860}
      confirmLoading={store.isSubmitting}
      okText="提 交"
      onCancel={() => store.hideForm()}
      onOk={handleSubmit}
      maskClosable={false}
    >
      <Alert type="info" showIcon style={{marginBottom: 12}}
        message="变更保存后为草稿，需在变更详情中确认应用后才会生效。"/>
      <div style={{marginBottom: 4}}>配置参数（变更后值）</div>
      {rows.map((row, index) => renderRow(row, index))}
      <Button type="dashed" block onClick={addRow} style={{marginBottom: 12}}>
        <PlusOutlined/> 添加参数
      </Button>
      <Form form={form} labelCol={{span: 5}} wrapperCol={{span: 18}}>
        <ChangeFormFields
          includeHistory={includeHistory}
          files={files}
          onCollectFiles={collectFiles}
          onRemoveFile={removeFile}
        />
      </Form>
    </Modal>
  );
});

// 单个参数行：参数选择 + 当前值展示 + 变更后值输入 + 备注
function ParamRow({row, configItems, onParamChange, onValueChange, onRemarkChange, onRemove}) {
  const param = configItems.find(item => item.param === row.param);
  return (
    <div style={{display: 'flex', alignItems: 'flex-start', marginBottom: 8}}>
      <Select
        showSearch
        optionFilterProp="children"
        style={{width: 220, flexShrink: 0}}
        placeholder="选择参数"
        value={row.param}
        onChange={onParamChange}
      >
        {configItems.map(item => (
          <Select.Option value={item.param} key={item.param}>
            {item.param_name}（{item.param_code}）
          </Select.Option>
        ))}
      </Select>
      <div style={{margin: '0 8px', flexShrink: 0, paddingTop: 5, whiteSpace: 'nowrap'}}>
        当前：<span style={{color: '#888'}}>{param ? param.display_value : '-'}</span>
        {param && param.unit ? `（${param.unit}）` : ''}
      </div>
      <div style={{flex: 1, marginRight: 8}}>
        <ValueInput
          dataType={param ? param.data_type : 'text'}
          options={param ? param.options : []}
          required={param ? param.is_required : false}
          value={row.new_value}
          onChange={onValueChange}
        />
      </div>
      <div style={{flex: 1, marginRight: 8}}>
        <Input value={row.remark} onChange={e => onRemarkChange(e.target.value)}
          maxLength={200} placeholder="备注（选填）"/>
      </div>
      <Button type="link" onClick={onRemove}>删除</Button>
    </div>
  );
}

// 变更表单字段区（渲染在 Form 上下文内；经 name 属性与 form 关联）
function ChangeFormFields({includeHistory, files, onCollectFiles, onRemoveFile}) {
  return (
    <Fragment>
      <Form.Item label="变更原因" name="reason"
        rules={[{required: true, message: '请填写变更原因'}]}>
        <TextArea rows={2} maxLength={500} placeholder="请说明本次配置变更的原因"/>
      </Form.Item>
      <Form.Item label="验证说明" name="verify_note">
        <Input maxLength={500} placeholder="选填，如预期验证方式或说明"/>
      </Form.Item>
      <Form.Item label="纳入系统履历" name="include_in_history" valuePropName="checked"
        extra="重要配置变更可纳入系统履历">
        <Switch/>
      </Form.Item>
      {includeHistory && (
        <Form.Item label="纳入原因" name="history_reason"
          rules={[{required: true, message: '纳入系统履历的重要变更必须填写原因'}]}>
          <Input maxLength={500} placeholder="请说明纳入系统履历的原因"/>
        </Form.Item>
      )}
      <Form.Item label="附件">
        <Upload
          multiple
          beforeUpload={onCollectFiles}
          onRemove={onRemoveFile}
          fileList={files.map((f, i) => ({uid: f.uid || `f-${i}`, name: f.name, status: 'done'}))}
        >
          <Button><UploadOutlined/> 选择附件</Button>
        </Upload>
      </Form.Item>
    </Fragment>
  );
}

export default SystemConfigChangeModal;

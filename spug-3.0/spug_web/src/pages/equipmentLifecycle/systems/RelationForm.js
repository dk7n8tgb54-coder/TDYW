/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Select, DatePicker, Switch, Input, message } from 'antd';
import moment from 'moment';
import { relationStore as store, ROLE_OPTIONS } from './store';

/**
 * 系统设备关系新建/编辑弹窗
 * 时间段语义：生效日期（含）~ 失效日期（不含，选填=长期有效）；
 * 失效日期必须晚于生效日期；编辑时系统与设备不可变。
 *
 * 三种上下文（互为镜像，均复用同一表单与后端校验）：
 * - 系统详情页：systemId 传入、systemSelectable 缺省 → 系统锁定，选设备；
 * - 设备关系页：systemSelectable → 系统、设备均自选；
 * - 设备详情弹窗：deviceId/deviceLabel 传入 + systemSelectable → 设备锁定，选系统。
 */
export default observer(function ({ systemId, systemSelectable, deviceId, deviceLabel }) {
  const [form] = Form.useForm();
  const isEdit = !!store.record.id;
  const record = store.record || {};

  React.useEffect(() => {
    if (!isEdit) {
      if (systemSelectable) store.fetchSystemOptions();
      // 打开弹窗即加载设备选项，无需先输入关键字（设备已锁定时无需加载）
      if (!deviceId) store.searchDevices('');
    }
  }, [systemSelectable, isEdit, deviceId]);

  const handleDeviceSearch = (keyword) => {
    if (keyword) store.searchDevices(keyword);
  };

  const disabledEndDate = (endValue) => {
    const startValue = form.getFieldValue('valid_from');
    if (!endValue || !startValue) return false;
    // 失效日期必须晚于生效日期（同日禁选）
    return endValue.isSameOrBefore(startValue, 'day');
  };

  const handleSubmit = () => {
    form.validateFields().then(values => {
      const data = {
        system_id: systemSelectable ? values.system_id : systemId,
        role: values.role,
        is_primary: !!values.is_primary,
        valid_from: values.valid_from.format('YYYY-MM-DD'),
        valid_to: values.valid_to ? values.valid_to.format('YYYY-MM-DD') : '',
        remark: (values.remark || '').trim(),
      };
      const request = isEdit
        ? store.handleUpdate({...data, id: record.id})
        : store.handleAdd({...data, device_id: deviceId || values.device_id});
      request.then(() => message.success('保存成功'));
    }).catch(() => {});
  };

  const deviceOptions = isEdit
    ? [{value: record.device_id, label: `${record.device_sn}（${record.device_name}）`}]
    : store.deviceOptions.map(d => ({value: d.id, label: `${d.device_sn}（${d.device_name}）`}));

  return (
    <Modal
      visible={store.formVisible}
      title={isEdit ? '编辑关系' : '新增关系'}
      onCancel={() => store.closeForm()}
      onOk={handleSubmit}
      okText="保存"
      cancelText="取消"
      width={560}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          device_id: isEdit ? record.device_id : undefined,
          role: isEdit ? record.role : undefined,
          is_primary: !!record.is_primary,
          valid_from: record.valid_from ? moment(record.valid_from, 'YYYY-MM-DD') : null,
          valid_to: record.valid_to ? moment(record.valid_to, 'YYYY-MM-DD') : null,
          remark: record.remark,
        }}
      >
        {systemSelectable && (isEdit ? (
          <Form.Item label="所属系统">
            <Input value={record.system_name || '-'} disabled/>
          </Form.Item>
        ) : (
          <Form.Item
            name="system_id"
            label="所属系统"
            rules={[{required: true, message: '请选择系统'}]}
          >
            <Select
              showSearch
              allowClear
              optionFilterProp="label"
              options={store.systemOptions.map(sys => ({
                value: sys.id,
                label: sys.code ? `${sys.name}（${sys.code}）` : sys.name,
              }))}
              placeholder="请选择系统"
            />
          </Form.Item>
        ))}
        {deviceId && !isEdit ? (
          <Form.Item label="设备" extra="设备已由当前详情锁定">
            <Input value={deviceLabel || '-'} disabled/>
          </Form.Item>
        ) : (
          <Form.Item
            name="device_id"
            label="设备"
            rules={[{required: true, message: '请选择设备'}]}
            extra={isEdit ? '关系建立后不可更换设备' : '输入编号或名称搜索本租户设备'}
          >
            <Select
              showSearch
              allowClear
              disabled={isEdit}
              filterOption={false}
              onSearch={handleDeviceSearch}
              options={deviceOptions}
              placeholder="请输入设备编号/名称搜索"
              notFoundContent="暂无匹配设备"
            />
          </Form.Item>
        )}
        <Form.Item
          name="role"
          label="关系角色"
          rules={[{required: true, message: '请选择关系角色'}]}
        >
          <Select options={ROLE_OPTIONS} placeholder="请选择关系角色"/>
        </Form.Item>
        <Form.Item name="is_primary" label="主要归属" valuePropName="checked">
          <Switch checkedChildren="是" unCheckedChildren="否"/>
        </Form.Item>
        <Form.Item
          name="valid_from"
          label="生效日期（含）"
          rules={[{required: true, message: '请选择生效日期'}]}
        >
          <DatePicker style={{width: '100%'}} format="YYYY-MM-DD" placeholder="请选择生效日期"/>
        </Form.Item>
        <Form.Item
          name="valid_to"
          label="失效日期（不含，选填=长期有效）"
          extra="同一系统下同设备的同角色关系时间段不可重叠"
        >
          <DatePicker style={{width: '100%'}} format="YYYY-MM-DD" placeholder="请选择失效日期"
                      disabledDate={disabledEndDate}/>
        </Form.Item>
        <Form.Item name="remark" label="备注" rules={[{max: 500, message: '备注不能超过500个字符'}]}>
          <Input.TextArea rows={2} placeholder="请输入备注" maxLength={500} showCount/>
        </Form.Item>
      </Form>
    </Modal>
  );
})

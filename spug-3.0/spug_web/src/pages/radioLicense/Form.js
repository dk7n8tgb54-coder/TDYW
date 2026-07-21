/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button, message, Descriptions, Tag, Divider, Space } from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';
import { AttachmentManager } from 'components';

const STATUS_TAG_MAP = {
  normal: {color: 'green', text: '正常'},
  expiring: {color: 'orange', text: '即将到期'},
  expired: {color: 'red', text: '已过期'},
};

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  // 直接根据 store 状态计算是否详情模式，避免 state 与 useEffect 时序问题
  // （原来的 setViewMode + useEffect([form]) 组合会导致模式切换时
  //  form 实例未连接到 Form 元素，触发 "useForm is not connected" 警告）
  const viewMode = S.detailVisible;

  React.useEffect(() => {
    // 详情模式不需要填充表单
    if (viewMode) return;
    const initialValues = {...S.record};

    // 处理频率初始值
    if (initialValues.frequencies && initialValues.frequencies.length > 0) {
      initialValues.frequencies = initialValues.frequencies.map(f => ({
        frequency_value: String(f.frequency_value || ''),
        frequency_unit: f.frequency_unit || 'MHz',
        frequency_text: f.frequency_text || '',
      }));
    } else {
      initialValues.frequencies = [{frequency_value: '', frequency_unit: 'MHz', frequency_text: ''}];
    }

    // 处理日期
    if (initialValues.valid_from) {
      initialValues.valid_from = moment(initialValues.valid_from);
    }
    if (initialValues.valid_to) {
      initialValues.valid_to = moment(initialValues.valid_to);
    }

    form.setFieldsValue(initialValues);
    // 加载可选责任人列表（必填项需要）
    S.fetchResponsibleUsers();
  }, [form, viewMode, S.record]);

  function handleSubmit() {
    form.validateFields().then(() => {
      setLoading(true);
      const formData = form.getFieldsValue();

      // 转换日期格式
      if (formData.valid_from) {
        formData.valid_from = formData.valid_from.format('YYYY-MM-DD');
      }
      if (formData.valid_to) {
        formData.valid_to = formData.valid_to.format('YYYY-MM-DD');
      }

      // 处理频率列表
      if (formData.frequencies) {
        formData.frequencies = formData.frequencies
          .filter(f => f && f.frequency_value)
          .map((f, idx) => ({
            frequency_value: parseFloat(f.frequency_value) || 0,
            frequency_unit: f.frequency_unit || 'MHz',
            frequency_text: f.frequency_text || '',
            sort_order: idx,
          }));
      }

      if (S.record.id) {
        formData.id = S.record.id;
      }

      http.post('/api/radio-license/', formData)
        .then(() => {
          message.success('操作成功');
          S.formVisible = false;
          S.fetchRecords();
        })
        .catch(e => {
          console.error('[电台执照] 提交表单失败:', e);
          message.error(e.message || '操作失败，请稍后重试');
        })
        .finally(() => setLoading(false));
    });
  }

  const info = S.record;

  // 详情模式
  if (viewMode) {
    const tagInfo = STATUS_TAG_MAP[info.computed_status] || STATUS_TAG_MAP.normal;
    return (
      <Modal
        visible
        width={900}
        title="执照详情"
        footer={[
          <Button key="close" onClick={() => S.detailVisible = false}>关闭</Button>,
          hasPermission('radio_license.license.edit') && (
            <Button key="edit" type="primary" onClick={() => {
              S.detailVisible = false;
              S.showForm(info);
            }}>编辑</Button>
          ),
        ]}
        onCancel={() => S.detailVisible = false}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="台站">{info.station_name}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={tagInfo.color}>{tagInfo.text}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="起始日期">{info.valid_from}</Descriptions.Item>
          <Descriptions.Item label="截止日期">{info.valid_to}</Descriptions.Item>
          <Descriptions.Item label="剩余天数">
            {info.days_left < 0
              ? <span style={{color: '#ff4d4f'}}>已过期 {Math.abs(info.days_left)} 天</span>
              : info.days_left <= 45
                ? <span style={{color: '#fa8c16'}}>{info.days_left} 天</span>
                : <span>{info.days_left} 天</span>
            }
          </Descriptions.Item>
          <Descriptions.Item label="责任人">{info.responsible_user_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="用途" span={2}>{info.purpose || '-'}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            <div style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto' }}>
              {info.remark || '-'}
            </div>
          </Descriptions.Item>
        </Descriptions>

        {info.frequencies && info.frequencies.length > 0 && (
          <>
            <Divider orientation="left">频率明细</Divider>
            <Descriptions bordered column={1} size="small">
              {info.frequencies.map((f, idx) => (
                <Descriptions.Item key={f.id || idx} label={`频率 ${idx + 1}`}>
                  {`${f.frequency_value} ${f.frequency_unit}`}{f.frequency_text ? `（${f.frequency_text}）` : ''}
                  {f.remark ? `（${f.remark}）` : ''}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </>
        )}

        <Divider orientation="left">附件</Divider>
        {info.id && (
          <AttachmentManager
            module="radio_license"
            objectType="license"
            recordId={info.id}
            listUrl={`/api/radio-license/${info.id}/attachments/`}
            uploadUrl={`/api/radio-license/${info.id}/attachments/`}
            deleteUrl="/api/radio-license/attachments/"
            downloadUrlPrefix="/api/radio-license/attachments/"
            previewUrlPrefix="/api/radio-license/attachments/"
            readOnly={false}
            uploadPerm="radio_license.attachment.upload"
            deletePerm="radio_license.attachment.delete"
            previewPerm="radio_license.license.view"
            maxFileSize={50}
            accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z"
          />
        )}

        <Descriptions bordered column={2} style={{marginTop: 16}}>
          <Descriptions.Item label="创建人">{info.created_by_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{info.created_at || '-'}</Descriptions.Item>
          <Descriptions.Item label="更新人">{info.updated_by_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{info.updated_at || '-'}</Descriptions.Item>
        </Descriptions>
      </Modal>
    );
  }

  // 编辑/新增模式
  const initialValues = {...info};
  if (initialValues.frequencies && initialValues.frequencies.length > 0) {
    initialValues.frequencies = initialValues.frequencies.map(f => ({
      frequency_value: String(f.frequency_value || ''),
      frequency_unit: f.frequency_unit || 'MHz',
      frequency_text: f.frequency_text || '',
    }));
  } else {
    initialValues.frequencies = [{frequency_value: '', frequency_unit: 'MHz', frequency_text: ''}];
  }
  if (initialValues.valid_from) {
    initialValues.valid_from = moment(initialValues.valid_from);
  }
  if (initialValues.valid_to) {
    initialValues.valid_to = moment(initialValues.valid_to);
  }

  return (
    <Modal
      visible
      width={800}
      maskClosable={false}
      title={S.record.id ? '编辑执照' : '新建执照'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{span: 6}} wrapperCol={{span: 14}}>
        <Form.Item required name="station_name" label="台站" rules={[{required: true, message: '请输入台站名称'}]}>
          <Input placeholder="请输入台站名称"/>
        </Form.Item>
        <Form.Item required name="valid_from" label="起始日期" rules={[{required: true, message: '请选择起始日期'}]}>
          <DatePicker style={{width: '100%'}} placeholder="请选择起始日期"/>
        </Form.Item>
        <Form.Item required name="valid_to" label="截止日期" rules={[{required: true, message: '请选择截止日期'}]}>
          <DatePicker style={{width: '100%'}} placeholder="请选择截止日期"/>
        </Form.Item>
        <Form.Item required name="purpose" label="用途" rules={[{required: true, message: '请输入用途'}]}>
          <Input.TextArea rows={3} placeholder="请输入用途"/>
        </Form.Item>
        <Form.Item
          required
          name="responsible_user_id"
          label="责任人"
          rules={[{required: true, message: '请选择责任人'}]}>
          <Select
            showSearch
            allowClear
            placeholder="请选择责任人（必填，按姓名/账号搜索）"
            optionFilterProp="label"
            loading={!S.responsibleUsersLoaded}
            notFoundContent={S.responsibleUsersLoaded ? '暂无可选用户' : '加载中...'}
            onChange={(value) => {
              // 选中后自动回填姓名（后端也会校验并覆盖一次）
              const u = S.responsibleUsers.find(x => x.id === value);
              if (u) form.setFieldsValue({responsible_user_name: u.nickname || u.username});
            }}>
            {S.responsibleUsers.map(u => (
              <Select.Option
                key={u.id}
                value={u.id}
                label={`${u.nickname} ${u.username}`}>
                {u.nickname}（{u.username}）
              </Select.Option>
            ))}
          </Select>
        </Form.Item>
        {/* 隐藏字段，提交时同步携带姓名（后端会自动用真名覆盖） */}
        <Form.Item name="responsible_user_name" hidden noStyle>
          <Input/>
        </Form.Item>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} placeholder="请输入备注（非必填）"/>
        </Form.Item>

        <Divider orientation="left">频率明细</Divider>
        <Form.List name="frequencies">
          {(fields, {add, remove}) => (
            <>
              {fields.map(({key, name, ...restField}) => (
                <Space key={key} style={{display: 'flex', marginBottom: 8}} align="baseline">
                  <Form.Item
                    {...restField}
                    name={[name, 'frequency_value']}
                    rules={[{required: true, message: '请输入频率'}]}>
                    <Input placeholder="频率值" style={{width: 120}}/>
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'frequency_unit']}>
                    <Select style={{width: 90}}>
                      {S.frequencyUnitOptions.map(item => (
                        <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, 'frequency_text']}>
                    <Input placeholder="显示文本（选填）" style={{width: 150}}/>
                  </Form.Item>
                  {fields.length > 1 && (
                    <MinusCircleOutlined
                      style={{color: '#ff4d4f', fontSize: 18}}
                      onClick={() => remove(name)}
                    />
                  )}
                </Space>
              ))}
              <Form.Item wrapperCol={{offset: 6}}>
                <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined/>}>
                  添加频率
                </Button>
              </Form.Item>
            </>
          )}
        </Form.List>
      </Form>
    </Modal>
  )
})

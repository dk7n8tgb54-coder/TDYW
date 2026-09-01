/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, DatePicker, Select, InputNumber, Button, message, Descriptions, Divider, Row, Col } from 'antd';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';
import { AttachmentManager } from 'components';

// 单位选项（与后端模型 choices 一致，不做数值换算，显式标注录入单位）
export const ALTITUDE_UNIT_OPTIONS = [
  {value: 'm', label: '米'},
  {value: 'ft', label: '英尺'},
];

export const DURATION_UNIT_OPTIONS = [
  {value: 's', label: '秒'},
  {value: 'min', label: '分钟'},
  {value: 'h', label: '小时'},
];

// 构建提交载荷（独立导出便于单元测试）
// 告警高度/持续时间清空时显式提交空串，后端按「清除」处理
export function buildAirPayload(formData, recordId, tempId) {
  const payload = {...formData};
  if (payload.datetime) {
    // 日期时间业务精度到分钟
    payload.datetime = payload.datetime.format('YYYY-MM-DD HH:mm');
  }
  if (payload.alert_altitude === undefined || payload.alert_altitude === null) {
    payload.alert_altitude = '';
  }
  if (payload.duration === undefined || payload.duration === null) {
    payload.duration = '';
  }
  if (recordId) {
    payload.id = recordId;
  } else {
    // 新建时传递临时附件 ID，后端将临时附件关联到新记录
    payload.attachment_temp_id = tempId;
  }
  return payload;
}

export default observer(function () {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState(false);
  // 新建阶段生成临时 ID，用于关联尚未保存记录的附件
  const [tempId] = useState(() => 'temp-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9));

  function handleSubmit() {
    form.validateFields().then(() => {
      setLoading(true);
      const formData = form.getFieldsValue();
      const payload = buildAirPayload(formData, S.record.id, tempId);
      http.post('/api/interference/air/', payload)
        .then(() => {
          message.success('操作成功');
          S.formVisible = false;
          S.fetchRecords();
        })
        .catch(() => {
          // 错误提示由 http 拦截器统一处理，此处仅恢复状态
        })
        .finally(() => setLoading(false));
    }).catch(() => {
      // 校验失败：字段下方已显示错误信息，无需额外提示
    });
  }

  React.useEffect(() => {
    const isViewDisabled = !hasPermission('interference.interference.edit');
    setViewMode(!!S.record.id && (S.record.isViewMode || isViewDisabled));

    const initialValues = {...S.record};
    if (initialValues.datetime) {
      initialValues.datetime = moment(initialValues.datetime);
    }
    if (!initialValues.alert_altitude_unit) initialValues.alert_altitude_unit = 'm';
    if (!initialValues.duration_unit) initialValues.duration_unit = 'min';
    form.setFieldsValue(initialValues);

    return () => {
      form.resetFields();
    };
  }, [form]);

  const info = S.record;
  // 附件管理器所需的 recordId：新建时用临时 ID，编辑/查看时用真实 ID
  const attachmentRecordId = info.id || tempId;
  const attachmentProps = {
    module: 'interference',
    objectType: 'air_interference',
    recordId: attachmentRecordId,
    listUrl: `/api/interference/air/${attachmentRecordId}/attachments/`,
    uploadUrl: `/api/interference/air/${attachmentRecordId}/attachments/`,
    deleteUrl: '/api/interference/attachments/',
    downloadUrlPrefix: '/api/interference/attachments/',
    previewUrlPrefix: '/api/interference/attachments/',
    readOnly: false,
    maxFileSize: 50,
    accept: '.pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z',
    uploadMode: 'dragger',
    multiple: true,
    maxFilesPerBatch: 20,
  };

  if (viewMode) {
    return (
      <Modal
        visible
        width={960}
        title="空中干扰详情"
        footer={[
          <Button key="close" onClick={() => S.formVisible = false}>关闭</Button>,
          hasPermission('interference.interference.edit') && (
            <Button key="edit" type="primary" onClick={() => setViewMode(false)}>编辑</Button>
          ),
        ]}
        onCancel={() => S.formVisible = false}>
        <Descriptions bordered column={2}>
          <Descriptions.Item label="日期时间">{(info.datetime || '').slice(0, 16)}</Descriptions.Item>
          <Descriptions.Item label="航班号">{info.flight_number || '-'}</Descriptions.Item>
          <Descriptions.Item label="机型">{info.aircraft_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="航线">{info.route || '-'}</Descriptions.Item>
          <Descriptions.Item label="被扰频率">{info.alert_form || '-'}</Descriptions.Item>
          <Descriptions.Item label="告警高度">{info.alert_altitude_text || '-'}</Descriptions.Item>
          <Descriptions.Item label="告警航段">{info.alert_segment || '-'}</Descriptions.Item>
          <Descriptions.Item label="持续时间">{info.duration_text || '-'}</Descriptions.Item>
          <Descriptions.Item label="现象" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.phenomenon}</div>
          </Descriptions.Item>
          <Descriptions.Item label="处置方式" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.handling_method || '-'}</div>
          </Descriptions.Item>
          <Descriptions.Item label="原因分析" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.cause_analysis || '-'}</div>
          </Descriptions.Item>
        </Descriptions>

        {info.id && (
          <>
            <Divider orientation="left">附件</Divider>
            <AttachmentManager {...attachmentProps} />
          </>
        )}
      </Modal>
    )
  }

  const initialValues = {...info};
  if (initialValues.datetime) {
    initialValues.datetime = moment(initialValues.datetime);
  }
  if (!initialValues.alert_altitude_unit) initialValues.alert_altitude_unit = 'm';
  if (!initialValues.duration_unit) initialValues.duration_unit = 'min';

  return (
    <Modal
      visible
      width={960}
      maskClosable={false}
      title={S.record.id ? '编辑空中干扰记录' : '新建空中干扰记录'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{span: 8}} wrapperCol={{span: 15}}>
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="datetime" label="日期时间"
                       rules={[{ required: true, message: '请选择日期时间' }]}>
              <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm"
                          style={{width: '100%'}} placeholder="请选择日期时间（到分钟）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="flight_number" label="航班号">
              <Input placeholder="请输入航班号（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="aircraft_type" label="机型">
              <Input placeholder="请输入机型（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="route" label="航线">
              <Input placeholder="请输入航线（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="alert_form" label="被扰频率">
              <Input placeholder="请输入被扰频率（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="alert_segment" label="告警航段">
              <Input placeholder="请输入告警航段（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="告警高度" style={{marginBottom: 0}}>
              <Form.Item name="alert_altitude"
                         rules={[{validator: (rule, value) => (value === undefined || value === null || value > 0) ? Promise.resolve() : Promise.reject(new Error('告警高度必须大于0'))}]}
                         style={{display: 'inline-block', width: '55%', marginBottom: 0}}>
                <InputNumber style={{width: '100%'}} min={0} step={0.01} placeholder="数值"/>
              </Form.Item>
              <Form.Item name="alert_altitude_unit" style={{display: 'inline-block', width: '40%', marginBottom: 0, marginLeft: '2%'}}>
                <Select options={ALTITUDE_UNIT_OPTIONS} placeholder="单位"/>
              </Form.Item>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="持续时间" style={{marginBottom: 0}}>
              <Form.Item name="duration"
                         rules={[{validator: (rule, value) => (value === undefined || value === null || value > 0) ? Promise.resolve() : Promise.reject(new Error('持续时间必须大于0'))}]}
                         style={{display: 'inline-block', width: '55%', marginBottom: 0}}>
                <InputNumber style={{width: '100%'}} min={0} step={0.01} placeholder="数值"/>
              </Form.Item>
              <Form.Item name="duration_unit" style={{display: 'inline-block', width: '40%', marginBottom: 0, marginLeft: '2%'}}>
                <Select options={DURATION_UNIT_OPTIONS} placeholder="单位"/>
              </Form.Item>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="phenomenon" label="现象"
                       labelCol={{span: 4}} wrapperCol={{span: 19}}
                       rules={[{ required: true, message: '请输入现象' }]}>
              <Input.TextArea rows={4} placeholder="请输入现象"/>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="handling_method" label="处置方式"
                       labelCol={{span: 4}} wrapperCol={{span: 19}}>
              <Input.TextArea rows={3} placeholder="请输入处置方式（选填）"/>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="cause_analysis" label="原因分析"
                       labelCol={{span: 4}} wrapperCol={{span: 19}}>
              <Input.TextArea rows={3} placeholder="请输入原因分析（选填）"/>
            </Form.Item>
          </Col>
        </Row>
      </Form>

      <Divider orientation="left">附件</Divider>
      <div style={{ marginLeft: 0 }}>
        <AttachmentManager {...attachmentProps} />
      </div>
    </Modal>
  )
})

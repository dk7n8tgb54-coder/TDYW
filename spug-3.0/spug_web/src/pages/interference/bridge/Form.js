/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, DatePicker, Button, message, Descriptions, Divider, Row, Col } from 'antd';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import S from './store';
import { AttachmentManager } from 'components';

// 构建提交载荷（独立导出便于单元测试）
export function buildBridgePayload(formData, recordId, tempId) {
  const payload = {...formData};
  if (payload.datetime) {
    // 日期时间业务精度到分钟
    payload.datetime = payload.datetime.format('YYYY-MM-DD HH:mm');
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
      const payload = buildBridgePayload(formData, S.record.id, tempId);
      http.post('/api/interference/bridge/', payload)
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
    objectType: 'bridge_interference',
    recordId: attachmentRecordId,
    listUrl: `/api/interference/bridge/${attachmentRecordId}/attachments/`,
    uploadUrl: `/api/interference/bridge/${attachmentRecordId}/attachments/`,
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
        title="地面无线电通信异常/干扰详情"
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
          <Descriptions.Item label="机号">{info.aircraft_no || '-'}</Descriptions.Item>
          <Descriptions.Item label="机型">{info.aircraft_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="位置/机位" tooltip="廊桥/航站楼位置或具体机位编号">{info.location || '-'}</Descriptions.Item>
          <Descriptions.Item label="频率">{info.frequency || '-'}</Descriptions.Item>
          <Descriptions.Item label="现象" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.phenomenon}</div>
          </Descriptions.Item>
          <Descriptions.Item label="处置方式" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.handling_method || '-'}</div>
          </Descriptions.Item>
          <Descriptions.Item label="原因分析" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.cause_analysis || '-'}</div>
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            <div style={{whiteSpace: 'pre-wrap'}}>{info.remark || '-'}</div>
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

  return (
    <Modal
      visible
      width={960}
      maskClosable={false}
      title={S.record.id ? '编辑地面干扰记录' : '新建地面干扰记录'}
      onCancel={() => S.formVisible = false}
      confirmLoading={loading}
      onOk={handleSubmit}>
      <Form form={form} initialValues={initialValues} labelCol={{span: 6}} wrapperCol={{span: 18}}>
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
            <Form.Item name="aircraft_no" label="机号">
              <Input placeholder="请输入机号（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="aircraft_type" label="机型">
              <Input placeholder="请输入机型（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="location" label="位置/机位">
              <Input placeholder="廊桥/航站楼位置或机位编号（选填）"/>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="frequency" label="频率"
                       rules={[{ pattern: /^\d+(\.\d+)?$/, message: '频率请输入数字' }]}>
              <Input placeholder="请输入频率（选填）"/>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="phenomenon" label="现象"
                       labelCol={{span: 3}} wrapperCol={{span: 20}}
                       rules={[{ required: true, message: '请输入现象' }]}>
              <Input.TextArea rows={4} placeholder="请输入现象"/>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="handling_method" label="处置方式"
                       labelCol={{span: 3}} wrapperCol={{span: 20}}>
              <Input.TextArea rows={3} placeholder="请输入处置方式（选填）"/>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="cause_analysis" label="原因分析"
                       labelCol={{span: 3}} wrapperCol={{span: 20}}>
              <Input.TextArea rows={3} placeholder="请输入原因分析（选填）"/>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item name="remark" label="备注" labelCol={{span: 3}} wrapperCol={{span: 20}}>
              <Input.TextArea rows={2} placeholder="请输入备注（选填）"/>
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

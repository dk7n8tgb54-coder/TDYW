import React, {useEffect, useState} from 'react';
import {Button, Col, DatePicker, Form, Input, InputNumber, Modal, Row, Select, Table, Tabs, message} from 'antd';
import moment from 'moment';
import {http, hasPermission} from 'libs';
import {AttachmentManager} from 'components';
import store from './store';

const STATUS_OPTIONS = [
  {value: 'draft', label: '草稿'},
  {value: 'observing', label: '持续观察'},
  {value: 'measuring', label: '测量中'},
  {value: 'concluded', label: '已形成结论'},
  {value: 'closed', label: '已结束'},
  {value: 'cancelled', label: '已取消'},
];

export function buildInvestigationPayload(values, investigationId, eventIds) {
  const payload = {...values};
  ['start_at', 'end_at'].forEach(key => {
    if (payload[key] && payload[key].format) payload[key] = payload[key].format('YYYY-MM-DD HH:mm:ss');
  });
  if (eventIds && eventIds.length) payload.event_ids = eventIds;
  if (investigationId) payload.id = investigationId;
  return payload;
}

export function buildMeasurementPayload(values) {
  const payload = {...values};
  if (payload.measured_at && payload.measured_at.format) payload.measured_at = payload.measured_at.format('YYYY-MM-DD HH:mm:ss');
  return payload;
}

function measurementColumns(canViewAttachments, canEditAttachments) {
  return [
    {title: '测量时间', dataIndex: 'measured_at', render: value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'},
    {title: '地点', dataIndex: 'location'},
    {title: '仪器', dataIndex: 'instrument_model'},
    {title: '频率范围', dataIndex: 'frequency_range'},
    {title: '测量结果', dataIndex: 'result', ellipsis: true},
    ...(canViewAttachments ? [{
      title: '附件',
      key: 'attachments',
      width: 220,
      render: (_, record) => <AttachmentManager
        module="interference"
        objectType="interference_measurement"
        recordId={record.id}
        listUrl={`/api/interference/measurements/${record.id}/attachments/`}
        uploadUrl={`/api/interference/measurements/${record.id}/attachments/`}
        deleteUrl="/api/interference/attachments/"
        downloadUrlPrefix="/api/interference/attachments/"
        previewUrlPrefix="/api/interference/attachments/"
        uploadPerm="interference.measurement.add|interference.measurement.edit"
        deletePerm="interference.measurement.edit|interference.measurement.del"
        previewPerm="interference.measurement.view"
        downloadPerm="interference.measurement.view"
        readOnly={!canEditAttachments}
        hiddenColumns={['file_size', 'uploaded_by_name', 'created_at']}
        maxFileSize={50}
      />,
    }] : []),
  ];
}

export default function InvestigationForm() {
  const [form] = Form.useForm();
  const [measurementForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [measurementVisible, setMeasurementVisible] = useState(false);
  const [detail, setDetail] = useState(store.investigation || {});
  const info = store.investigation || {};
  const infoId = info.id;
  const visible = store.investigationModalVisible;
  const canEdit = !info.isViewMode && (
    hasPermission('interference.investigation.edit') ||
    (!infoId && hasPermission('interference.investigation.add'))
  );
  const canViewMeasurementAttachments = hasPermission('interference.measurement.view');
  const canEditMeasurementAttachments = canEdit && hasPermission(
    'interference.measurement.add|interference.measurement.edit'
  );

  useEffect(() => {
    let active = true;
    if (!visible) return undefined;
    const request = infoId ? store.fetchInvestigation(infoId) : Promise.resolve(info);
    request.then(data => {
      if (!active) return;
      setDetail(data || info);
      form.setFieldsValue({
        ...(data || info),
        start_at: data && data.start_at ? moment(data.start_at) : undefined,
        end_at: data && data.end_at ? moment(data.end_at) : undefined,
      });
    }).catch(() => {});
    return () => {
      active = false;
      form.resetFields();
    };
  }, [visible, info, infoId, form]);

  function close() {
    form.resetFields();
    measurementForm.resetFields();
    setMeasurementVisible(false);
    store.closeInvestigation();
  }

  function submit() {
    if (loading || !canEdit) return;
    setLoading(true);
    form.validateFields().then(values => {
      const payload = buildInvestigationPayload(values, info.id, info.event_ids);
      const request = info.id
        ? http.put(`/api/interference/investigations/${info.id}/`, payload)
        : http.post('/api/interference/investigations/', payload);
      return request;
    }).then(() => {
      message.success('保存成功');
      close();
      return store.fetchInvestigations();
    }).catch(() => {}).finally(() => setLoading(false));
  }

  function addMeasurement() {
    if (loading || !canEdit || !info.id) return;
    setLoading(true);
    measurementForm.validateFields().then(values => {
      return http.post(`/api/interference/investigations/${info.id}/measurements/`, buildMeasurementPayload(values));
    }).then(() => {
      message.success('测量记录已保存');
      measurementForm.resetFields();
      setMeasurementVisible(false);
      return store.fetchInvestigation(info.id).then(setDetail);
    }).catch(() => {}).finally(() => setLoading(false));
  }

  const events = detail.events || [];
  const measurements = detail.measurements || [];
  return <Modal visible={visible} width={1080} title={info.id ? '规律调查详情' : '新建规律调查'} onCancel={close} maskClosable={false} destroyOnClose footer={canEdit ? [<Button key="cancel" onClick={close}>取消</Button>, <Button key="save" type="primary" loading={loading} onClick={submit}>保存</Button>] : [<Button key="close" onClick={close}>关闭</Button>] }>
    <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}} disabled={!canEdit}>
      <Row gutter={16}>
        <Col span={12}><Form.Item name="name" label="调查名称" rules={[{required: true, message: '请输入调查名称'}]}><Input/></Form.Item></Col>
        <Col span={12}><Form.Item name="status" label="调查状态"><Select options={STATUS_OPTIONS}/></Form.Item></Col>
        <Col span={12}><Form.Item name="owner" label="负责人"><Input/></Form.Item></Col>
        <Col span={12}><Form.Item name="trigger_reason" label="触发原因"><Input/></Form.Item></Col>
        <Col span={12}><Form.Item name="start_at" label="开始时间"><DatePicker showTime style={{width: '100%'}}/></Form.Item></Col>
        <Col span={12}><Form.Item name="end_at" label="结束时间"><DatePicker showTime style={{width: '100%'}}/></Form.Item></Col>
        <Col span={24}><Form.Item name="scope" label="调查范围"><Input.TextArea rows={2}/></Form.Item></Col>
        <Col span={24}><Form.Item name="remark" label="备注"><Input.TextArea rows={2}/></Form.Item></Col>
      </Row>
    {info.id && <Tabs defaultActiveKey="overview">
      <Tabs.TabPane tab="概览" key="overview"><p>关联事件：{detail.event_count || events.length} 条</p><p>首次发生：{detail.first_event_datetime || '-'}</p><p>最近发生：{detail.last_event_datetime || '-'}</p></Tabs.TabPane>
      <Tabs.TabPane tab="关联事件" key="events"><Table rowKey="id" columns={[{title: '发生时间', dataIndex: 'datetime'}, {title: '场景', dataIndex: 'scene_text'}, {title: '现象', dataIndex: 'phenomenon'}]} dataSource={events} pagination={false}/></Tabs.TabPane>
      <Tabs.TabPane tab="频谱测量" key="measurements">
        <Button type="primary" disabled={!canEdit || !hasPermission('interference.measurement.add|interference.measurement.edit')} onClick={() => setMeasurementVisible(true)}>录入测量</Button>
        <Table style={{marginTop: 12}} rowKey="id" columns={measurementColumns(canViewMeasurementAttachments, canEditMeasurementAttachments)} dataSource={measurements} pagination={false}/>
      </Tabs.TabPane>
      <Tabs.TabPane tab="调查结论" key="conclusion"><div><Form.Item name="conclusion" label="调查结论"><Input.TextArea rows={5}/></Form.Item><Form.Item name="follow_up_advice" label="后续建议"><Input.TextArea rows={4}/></Form.Item></div></Tabs.TabPane>
      <Tabs.TabPane tab="附件" key="attachments"><AttachmentManager module="interference" objectType="interference_investigation" recordId={info.id} listUrl={`/api/interference/investigations/${info.id}/attachments/`} uploadUrl={`/api/interference/investigations/${info.id}/attachments/`} deleteUrl="/api/interference/attachments/" downloadUrlPrefix="/api/interference/attachments/" previewUrlPrefix="/api/interference/attachments/" uploadPerm="interference.investigation.add|interference.investigation.edit" deletePerm="interference.investigation.edit|interference.investigation.del" previewPerm="interference.investigation.view" downloadPerm="interference.investigation.view" readOnly={!canEdit} maxFileSize={50}/></Tabs.TabPane>
    </Tabs>}
    </Form>
    <Modal visible={measurementVisible} title="录入频谱测量" onCancel={() => {measurementForm.resetFields(); setMeasurementVisible(false);}} onOk={addMeasurement} confirmLoading={loading}>
      <Form form={measurementForm} labelCol={{span: 7}} wrapperCol={{span: 15}}>
        <Form.Item name="measured_at" label="测量时间" rules={[{required: true, message: '请选择测量时间'}]}><DatePicker showTime style={{width: '100%'}}/></Form.Item>
        <Form.Item name="location" label="测量地点"><Input/></Form.Item>
        <Form.Item name="instrument_model" label="仪器型号"><Input/></Form.Item>
        <Form.Item name="instrument_no" label="仪器编号"><Input/></Form.Item>
        <Form.Item name="frequency_range" label="频率范围"><Input/></Form.Item>
        <Form.Item name="center_frequency" label="中心频率"><InputNumber style={{width: '100%'}}/></Form.Item>
        <Form.Item name="bandwidth" label="带宽"><InputNumber style={{width: '100%'}}/></Form.Item>
        <Form.Item name="field_strength" label="场强"><InputNumber style={{width: '100%'}}/></Form.Item>
        <Form.Item name="power" label="功率"><InputNumber style={{width: '100%'}}/></Form.Item>
        <Form.Item name="measurement_unit" label="测量单位"><Input/></Form.Item>
        <Form.Item name="antenna_polarization" label="天线/极化"><Input/></Form.Item>
        <Form.Item name="result" label="测量结果"><Input.TextArea rows={3}/></Form.Item>
        <Form.Item name="conclusion" label="测量结论"><Input.TextArea rows={2}/></Form.Item>
        <Form.Item name="remark" label="备注"><Input.TextArea rows={2}/></Form.Item>
      </Form>
    </Modal>
  </Modal>;
}

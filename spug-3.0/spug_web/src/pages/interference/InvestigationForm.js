import React, {useEffect, useState} from 'react';
import {Button, Col, DatePicker, Form, Input, InputNumber, Modal, Row, Table, Tabs, message} from 'antd';
import moment from 'moment';
import {http, hasPermission} from 'libs';
import {AttachmentManager} from 'components';
import store from './store';

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

// 录入频谱测量内层弹窗（2026-10-26 审查R2）：自 InvestigationForm 抽出以满足
// 组件函数 120 行门禁（同文件 measurementColumns 为既有先例）。纯 JSX 搬迁、
// 零行为变化：form 实例仍由宿主持有并传入，字段名/校验/布局/回调语义不变。
function MeasurementModal({visible, form, loading, onCancel, onOk}) {
  return <Modal visible={visible} title="录入频谱测量" onCancel={onCancel} onOk={onOk} confirmLoading={loading}>
    <Form form={form} labelCol={{span: 7}} wrapperCol={{span: 15}}>
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
  </Modal>;
}

export default function InvestigationForm({onSaved} = {}) {
  const [form] = Form.useForm();
  const [measurementForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [measurementVisible, setMeasurementVisible] = useState(false);
  const [detail, setDetail] = useState(store.investigation || {});
  const info = store.investigation || {};
  const infoId = info.id;
  const visible = store.investigationModalVisible;
  // 门禁对齐后端矩阵（views.py:520 POST=investigation.add|interference.add、
  // :609 PUT=仅 investigation.edit 无 OR 支不得放宽）：创建态 edit-only 不再可编辑
  const canEdit = !info.isViewMode && (infoId
    ? hasPermission('interference.investigation.edit')
    : hasPermission('interference.investigation.add|interference.interference.add'));
  const canViewMeasurementAttachments = hasPermission('interference.measurement.view');
  // 录入测量入口对齐后端 POST /investigations/<pk>/measurements/ 的 OR 口径
  // （measurement.add | investigation.edit）；measurement.edit 仅用于编辑既有
  // 测量与测量附件、不被录入端点接受，单独持有不得打开录入入口。
  // 2026-10-26 产品决策：查看态不阻断后端授权的测量录入（调查字段仍由
  // canEdit 的 isViewMode 因子保持只读）。
  const canEnterMeasurement = hasPermission(
    'interference.measurement.add|interference.investigation.edit'
  );
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
      if (onSaved) onSaved(); // 宿主刷新回调（问题1配套：事件页传 fetchEvents 刷新调查状态列）
      return store.fetchInvestigations();
    }).catch(() => {}).finally(() => setLoading(false));
  }

  function addMeasurement() {
    if (loading || !canEnterMeasurement || !info.id) return;
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
    {/* 调查字段逐一 disabled={!canEdit}，不用 Form 级 disabled：antd Form 的禁用
        上下文会强制禁用其内所有 Button（Button 取 customDisabled || 上下文，无逃逸口），
        导致仅持 measurement.add 的用户点不了录入测量入口（canEnterMeasurement 为
        true 也被压掉）。调查字段编辑与测量录入是两个独立操作口径，须分开控制。 */}
    <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
      <Row gutter={16}>
        <Col span={12}><Form.Item name="name" label="调查名称" rules={[{required: true, message: '请输入调查名称'}]}><Input disabled={!canEdit}/></Form.Item></Col>
        {/* 调查状态已生命周期动作化（2026-10-26）：状态不再随表单提交（后端拒绝
            status 键），推进入口为列表行「结束调查/取消调查」弹窗，当前状态在
            概览页签只读展示 */}
        <Col span={12}><Form.Item name="owner" label="负责人"><Input disabled={!canEdit}/></Form.Item></Col>
        <Col span={12}><Form.Item name="trigger_reason" label="触发原因"><Input disabled={!canEdit}/></Form.Item></Col>
        <Col span={12}><Form.Item name="start_at" label="开始时间"><DatePicker showTime style={{width: '100%'}} disabled={!canEdit}/></Form.Item></Col>
        <Col span={12}><Form.Item name="end_at" label="结束时间"><DatePicker showTime style={{width: '100%'}} disabled={!canEdit}/></Form.Item></Col>
        <Col span={24}><Form.Item name="scope" label="调查范围"><Input.TextArea rows={2} disabled={!canEdit}/></Form.Item></Col>
        <Col span={24}><Form.Item name="remark" label="备注"><Input.TextArea rows={2} disabled={!canEdit}/></Form.Item></Col>
      </Row>
    {info.id && <Tabs defaultActiveKey="overview">
      <Tabs.TabPane tab="概览" key="overview"><p>调查状态：{detail.status_text || '-'}</p><p>调查结果：{detail.result_text || '-'}</p>{detail.status === 'cancelled' && <p>取消原因：{detail.cancel_reason || '-'}</p>}<p>关联事件：{detail.event_count || events.length} 条</p><p>首次发生：{detail.first_event_datetime || '-'}</p><p>最近发生：{detail.last_event_datetime || '-'}</p></Tabs.TabPane>
      <Tabs.TabPane tab="关联事件" key="events"><Table rowKey="id" columns={[{title: '发生时间', dataIndex: 'datetime'}, {title: '场景', dataIndex: 'scene_text'}, {title: '现象', dataIndex: 'phenomenon'}]} dataSource={events} pagination={false}/></Tabs.TabPane>
      <Tabs.TabPane tab="频谱测量" key="measurements">
        <Button type="primary" disabled={!canEnterMeasurement} onClick={() => setMeasurementVisible(true)}>录入测量</Button>
        <Table style={{marginTop: 12}} rowKey="id" columns={measurementColumns(canViewMeasurementAttachments, canEditMeasurementAttachments)} dataSource={measurements} pagination={false}/>
      </Tabs.TabPane>
      <Tabs.TabPane tab="调查结论" key="conclusion"><div><Form.Item name="conclusion" label="调查结论"><Input.TextArea rows={5} disabled={!canEdit}/></Form.Item><Form.Item name="follow_up_advice" label="后续建议"><Input.TextArea rows={4} disabled={!canEdit}/></Form.Item></div></Tabs.TabPane>
      <Tabs.TabPane tab="附件" key="attachments"><AttachmentManager module="interference" objectType="interference_investigation" recordId={info.id} listUrl={`/api/interference/investigations/${info.id}/attachments/`} uploadUrl={`/api/interference/investigations/${info.id}/attachments/`} deleteUrl="/api/interference/attachments/" downloadUrlPrefix="/api/interference/attachments/" previewUrlPrefix="/api/interference/attachments/" uploadPerm="interference.investigation.add|interference.investigation.edit" deletePerm="interference.investigation.edit|interference.investigation.del" previewPerm="interference.investigation.view" downloadPerm="interference.investigation.view" readOnly={!canEdit} maxFileSize={50}/></Tabs.TabPane>
    </Tabs>}
    </Form>
    <MeasurementModal visible={measurementVisible} form={measurementForm} loading={loading} onCancel={() => {measurementForm.resetFields(); setMeasurementVisible(false);}} onOk={addMeasurement}/>
  </Modal>;
}

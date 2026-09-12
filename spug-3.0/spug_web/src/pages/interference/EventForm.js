import React, {useEffect, useState} from 'react';
import {Button, Col, DatePicker, Divider, Form, Input, InputNumber, Modal, Row, Select, message} from 'antd';
import moment from 'moment';
import {http, hasPermission} from 'libs';
import {AttachmentManager} from 'components';
import store from './store';

const SCENE_OPTIONS = [
  {value: 'ground', label: '地面'},
  {value: 'air', label: '空中'},
  {value: 'cross', label: '跨场景'},
  {value: 'unknown', label: '未知'},
];
const KIND_OPTIONS = [
  {value: 'noise', label: '杂音'},
  {value: 'intermittent', label: '间歇中断'},
  {value: 'communication_loss', label: '完全失联'},
  {value: 'frequency_occupy', label: '频率占用'},
  {value: 'blocking', label: '阻塞'},
  {value: 'false_alarm', label: '虚警'},
  {value: 'other', label: '其他'},
  {value: 'unknown', label: '未知'},
];
const SYSTEM_OPTIONS = [
  {value: 'communication', label: '通信'},
  {value: 'navigation', label: '导航'},
  {value: 'surveillance', label: '监视'},
  {value: 'datalink', label: '数据链'},
  {value: 'equipment', label: '设备电磁兼容'},
  {value: 'other', label: '其他'},
];
const SOURCE_OPTIONS = [
  {value: 'ground_equipment', label: '地面设备'},
  {value: 'vehicle_power', label: '车辆/电源'},
  {value: 'aircraft_equipment', label: '机载设备'},
  {value: 'external_transmitter', label: '外部发射源'},
  {value: 'environment', label: '环境'},
  {value: 'unknown', label: '未知'},
];

export function buildEventPayload(values, eventId) {
  const payload = {...values};
  if (payload.datetime && payload.datetime.format) {
    payload.datetime = payload.datetime.format('YYYY-MM-DD HH:mm:ss');
  }
  const scene = payload.scene_code;
  const ground = {
    location: payload.ground_location,
    frequency: payload.ground_frequency,
    ground_equipment: payload.ground_equipment,
    remark: payload.ground_remark,
  };
  const air = {
    route: payload.route,
    alert_frequency: payload.alert_frequency,
    alert_altitude: payload.alert_altitude,
    alert_altitude_unit: payload.alert_altitude_unit,
    alert_segment: payload.alert_segment,
    duration: payload.duration,
    duration_unit: payload.duration_unit,
  };
  delete payload.ground_location;
  delete payload.ground_frequency;
  delete payload.ground_equipment;
  delete payload.ground_remark;
  delete payload.route;
  delete payload.alert_frequency;
  delete payload.alert_altitude;
  delete payload.alert_altitude_unit;
  delete payload.alert_segment;
  delete payload.duration;
  delete payload.duration_unit;
  if (scene === 'ground' || scene === 'cross') payload.ground_detail = ground;
  if (scene === 'air' || scene === 'cross') payload.air_detail = air;
  if (eventId) payload.id = eventId;
  return payload;
}

function valuesFromEvent(event) {
  const ground = event.ground_detail || {};
  const air = event.air_detail || {};
  return {
    ...event,
    datetime: event.datetime ? moment(event.datetime) : undefined,
    ground_location: ground.location,
    ground_frequency: ground.frequency,
    ground_equipment: ground.ground_equipment,
    ground_remark: ground.remark,
    route: air.route,
    alert_frequency: air.alert_frequency,
    alert_altitude: air.alert_altitude,
    alert_altitude_unit: air.alert_altitude_unit || 'm',
    alert_segment: air.alert_segment,
    duration: air.duration,
    duration_unit: air.duration_unit || 'min',
  };
}

function DetailFields({scene}) {
  if (scene === 'ground') {
    return <GroundFields/>;
  }
  if (scene === 'air') {
    return <AirFields/>;
  }
  if (scene === 'cross') {
    return <><GroundFields/><Divider orientation="left">空中明细</Divider><AirFields/></>;
  }
  return <div style={{color: '#8c8c8c', marginBottom: 16}}>未知场景暂不要求专属明细。</div>;
}

function GroundFields() {
  return <>
    <Divider orientation="left">地面明细</Divider>
    <Row gutter={16}>
      <Col span={12}><Form.Item name="ground_location" label="位置/机位"><Input/></Form.Item></Col>
      <Col span={12}><Form.Item name="ground_frequency" label="频率"><Input/></Form.Item></Col>
      <Col span={12}><Form.Item name="ground_equipment" label="地面设备"><Input/></Form.Item></Col>
      <Col span={24}><Form.Item name="ground_remark" label="地面备注"><Input.TextArea rows={2}/></Form.Item></Col>
    </Row>
  </>;
}

function AirFields() {
  return <>
    <Divider orientation="left">空中明细</Divider>
    <Row gutter={16}>
      <Col span={12}><Form.Item name="route" label="航线"><Input/></Form.Item></Col>
      <Col span={12}><Form.Item name="alert_frequency" label="被扰频率"><Input/></Form.Item></Col>
      <Col span={12}><Form.Item name="alert_altitude" label="告警高度"><InputNumber min={0} style={{width: '65%'}}/></Form.Item></Col>
      <Col span={12}><Form.Item name="alert_altitude_unit" label="高度单位"><Select options={[{value: 'm', label: '米'}, {value: 'ft', label: '英尺'}]}/></Form.Item></Col>
      <Col span={12}><Form.Item name="alert_segment" label="告警航段"><Input/></Form.Item></Col>
      <Col span={12}><Form.Item name="duration" label="持续时间"><InputNumber min={0} style={{width: '65%'}}/></Form.Item></Col>
      <Col span={12}><Form.Item name="duration_unit" label="时间单位"><Select options={[{value: 's', label: '秒'}, {value: 'min', label: '分钟'}, {value: 'h', label: '小时'}]}/></Form.Item></Col>
    </Row>
  </>;
}

export default function EventForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const info = store.event || {};
  const infoId = info.id;
  const visible = store.eventModalVisible;
  const canEdit = !info.isViewMode && (
    hasPermission('interference.interference.edit') ||
    (!infoId && hasPermission('interference.interference.add'))
  );

  useEffect(() => {
    let active = true;
    if (!visible) return undefined;
    const load = infoId && (!info.ground_detail && !info.air_detail)
      ? store.fetchEvent(infoId)
      : Promise.resolve(info);
    load.then(data => {
      if (active) form.setFieldsValue(valuesFromEvent(data || info));
    }).catch(() => {}).finally(() => {});
    return () => {
      active = false;
      form.resetFields();
    };
  }, [visible, info, infoId, form]);

  function close() {
    form.resetFields();
    store.closeEvent();
  }

  function submit() {
    if (loading) return;
    setLoading(true);
    form.validateFields().then(values => (
      http.post('/api/interference/events/', buildEventPayload(values, info.id))
    )).then(() => {
      message.success('保存成功');
      close();
      return store.fetchEvents();
    }).catch(() => {}).finally(() => setLoading(false));
  }

  return <Modal
    visible={visible}
    width={960}
    title={info.isViewMode ? '干扰事件详情' : (info.id ? '编辑干扰事件' : '新建干扰事件')}
    onCancel={close}
    maskClosable={false}
    destroyOnClose
    footer={canEdit ? [
      <Button key="cancel" onClick={close}>取消</Button>,
      <Button key="submit" type="primary" loading={loading} onClick={submit}>保存</Button>,
    ] : [<Button key="close" onClick={close}>关闭</Button>]}
  >
    <Form form={form} labelCol={{span: 7}} wrapperCol={{span: 16}} disabled={!canEdit}>
      <Row gutter={16}>
        <Col span={12}><Form.Item name="datetime" label="发生时间" rules={[{required: true, message: '请选择发生时间'}]}><DatePicker showTime style={{width: '100%'}}/></Form.Item></Col>
        <Col span={12}><Form.Item name="scene_code" label="发生场景" rules={[{required: true, message: '请选择发生场景'}]}><Select options={SCENE_OPTIONS}/></Form.Item></Col>
        <Col span={12}><Form.Item name="classification_status" label="分类状态"><Select options={[{value: 'pending', label: '待分类'}, {value: 'confirmed', label: '已确认'}]}/></Form.Item></Col>
        <Col span={12}><Form.Item name="interference_kind_code" label="具体干扰类型"><Select options={KIND_OPTIONS}/></Form.Item></Col>
        <Col span={12}><Form.Item name="affected_system_code" label="受影响系统"><Select options={SYSTEM_OPTIONS}/></Form.Item></Col>
        <Col span={12}><Form.Item name="source_type_code" label="疑似干扰源"><Select options={SOURCE_OPTIONS}/></Form.Item></Col>
        <Col span={8}><Form.Item name="flight_number" label="航班号"><Input/></Form.Item></Col>
        <Col span={8}><Form.Item name="aircraft_no" label="机号"><Input/></Form.Item></Col>
        <Col span={8}><Form.Item name="aircraft_type" label="机型"><Input/></Form.Item></Col>
        <Col span={24}><Form.Item name="phenomenon" label="现象"><Input.TextArea rows={3}/></Form.Item></Col>
        <Col span={24}><Form.Item name="initial_assessment" label="初步判断"><Input.TextArea rows={2}/></Form.Item></Col>
        <Col span={24}><Form.Item name="remark" label="备注"><Input.TextArea rows={2}/></Form.Item></Col>
      </Row>
      <Form.Item noStyle shouldUpdate={(previous, current) => previous.scene_code !== current.scene_code}>
        {({getFieldValue}) => <DetailFields scene={getFieldValue('scene_code')}/>} 
      </Form.Item>
    </Form>
    {info.id && <>
      <Divider orientation="left">附件</Divider>
      <AttachmentManager
        module="interference"
        objectType="interference_event"
        recordId={info.id}
        listUrl={`/api/interference/events/${info.id}/attachments/`}
        uploadUrl={`/api/interference/events/${info.id}/attachments/`}
        deleteUrl="/api/interference/attachments/"
        downloadUrlPrefix="/api/interference/attachments/"
        previewUrlPrefix="/api/interference/attachments/"
        uploadPerm="interference.interference.edit"
        deletePerm="interference.interference.edit|interference.interference.del"
        previewPerm="interference.interference.view"
        downloadPerm="interference.interference.view"
        readOnly={!canEdit}
        maxFileSize={50}
      />
    </>}
  </Modal>;
}

import React, {useEffect, useState} from 'react';
import {Button, Col, DatePicker, Form, Input, InputNumber, Modal, Row, Select, message} from 'antd';
import moment from 'moment';
import {observer} from 'mobx-react';
import {http, hasPermission} from 'libs';
import {AttachmentManager} from 'components';
import store from './store';
import styles from './EventForm.module.less';

const SCENE_OPTIONS = [
  {value: 'ground', label: '地面'},
  {value: 'air', label: '空中'},
  {value: 'cross', label: '地面+空中'},
  {value: 'unknown', label: '未知'},
];
// 三个分类下拉的具体干扰类型/受影响系统/疑似干扰源选项由接口下发，
// 此处仅维护字段名与选项分组键的对应关系。
const CATEGORY_FIELDS = ['interference_kind_code', 'affected_system_code', 'source_type_code'];
const CATEGORY_TEXT_KEYS = {
  interference_kind_code: 'interference_kind_text',
  affected_system_code: 'affected_system_text',
  source_type_code: 'source_type_text',
};
// 新建事件分类字段统一采用明确的「未知/待查」语义，不再默认「其他」
const CATEGORY_DEFAULTS = {
  interference_kind_code: 'unknown',
  affected_system_code: 'unknown',
  source_type_code: 'unknown',
};

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
    alert_segment: payload.alert_segment,
    duration: payload.duration,
  };
  delete payload.ground_location;
  delete payload.ground_frequency;
  delete payload.ground_equipment;
  delete payload.ground_remark;
  delete payload.route;
  delete payload.alert_frequency;
  delete payload.alert_altitude;
  delete payload.alert_segment;
  delete payload.duration;
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
    alert_segment: air.alert_segment,
    duration: air.duration,
  };
}

// 编辑历史事件时，当前值若不在接口选项里（如已停用编码）也要有 label 可显示
export function mergeCategoryOptions(options, event) {
  const merged = {...options};
  for (const field of CATEGORY_FIELDS) {
    const value = event ? event[field] : undefined;
    if (!value || (merged[field] || []).some(item => item.value === value)) continue;
    merged[field] = [
      ...(merged[field] || []),
      {value, label: (event && event[CATEGORY_TEXT_KEYS[field]]) || value},
    ];
  }
  return merged;
}

function DetailFields({scene}) {
  if (scene === 'ground') {
    return <GroundFields/>;
  }
  if (scene === 'air') {
    return <AirFields/>;
  }
  if (scene === 'cross') {
    return <><GroundFields/><AirFields/></>;
  }
  return <div className={styles.emptyDetail}>未知场景暂不要求专属明细。</div>;
}

function GroundFields() {
  return <div className={styles.section}>
    <div className={styles.sectionTitle}>地面明细</div>
    <Row gutter={[20, 0]}>
      <Col span={12} className={styles.halfField}><Form.Item name="ground_location" label="位置/机位"><Input/></Form.Item></Col>
      <Col span={12} className={styles.halfField}><Form.Item name="ground_frequency" label="频率"><Input/></Form.Item></Col>
      <Col span={12} className={styles.halfField}><Form.Item name="ground_equipment" label="地面设备"><Input/></Form.Item></Col>
      <Col span={24}><Form.Item name="ground_remark" label="地面备注"><Input.TextArea rows={1}/></Form.Item></Col>
    </Row>
  </div>;
}

function AirFields() {
  return <div className={styles.section}>
    <div className={styles.sectionTitle}>空中明细</div>
    <Row gutter={[20, 0]}>
      <Col span={12} className={styles.halfField}><Form.Item name="route" label="航线"><Input/></Form.Item></Col>
      <Col span={12} className={styles.halfField}><Form.Item name="alert_frequency" label="被扰频率"><Input/></Form.Item></Col>
      <Col span={12} className={styles.halfField}><Form.Item name="alert_altitude" label="告警高度"><InputNumber min={0} style={{width: '65%'}}/></Form.Item></Col>
      <Col span={12} className={styles.halfField}><Form.Item name="alert_segment" label="告警航段"><Input/></Form.Item></Col>
      <Col span={12} className={styles.halfField}><Form.Item name="duration" label="持续时间"><InputNumber min={0} style={{width: '65%'}}/></Form.Item></Col>
    </Row>
  </div>;
}

// 新建事件时对未设置的分类字段应用「未知/待查」缺省；编辑保留存量值
export function withCategoryDefaults(values, isEdit) {
  if (isEdit) return values;
  const merged = {...values};
  for (const field of CATEGORY_FIELDS) {
    const current = merged[field];
    if (current === undefined || current === null || current === '') {
      merged[field] = CATEGORY_DEFAULTS[field];
    }
  }
  return merged;
}

function EventForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const info = store.event || {};
  const infoId = info.id;
  const visible = store.eventModalVisible;
  const canEdit = !info.isViewMode && (
    hasPermission('interference.interference.edit') ||
    (!infoId && hasPermission('interference.interference.add'))
  );
  const categoryOptions = mergeCategoryOptions(store.categoryOptions, info);

  useEffect(() => {
    let active = true;
    if (!visible) return undefined;
    store.fetchCategories().catch(() => {});
    const load = infoId && (!info.ground_detail && !info.air_detail)
      ? store.fetchEvent(infoId)
      : Promise.resolve(info);
    load.then(data => {
      if (active) {
        form.setFieldsValue(withCategoryDefaults(valuesFromEvent(data || info), infoId));
      }
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
    className={styles.eventModal}
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
    <Form form={form} layout="vertical" className={styles.form} disabled={!canEdit}>
      <div className={styles.section}>
        <div className={styles.sectionTitle}>基本信息</div>
        <Row gutter={[20, 0]}>
          <Col span={12} className={styles.halfField}><Form.Item name="datetime" label="发生时间" rules={[{required: true, message: '请选择发生时间'}]}><DatePicker showTime style={{width: '100%'}}/></Form.Item></Col>
          <Col span={12} className={styles.halfField}><Form.Item name="scene_code" label="发生场景" rules={[{required: true, message: '请选择发生场景'}]}><Select options={SCENE_OPTIONS}/></Form.Item></Col>
        </Row>
      </div>
      <div className={styles.section}>
        <div className={styles.sectionTitle}>干扰分类</div>
        <Row gutter={[20, 0]}>
          <Col span={8} className={styles.thirdField}><Form.Item name="interference_kind_code" label="具体干扰类型"><Select options={categoryOptions.interference_kind_code}/></Form.Item></Col>
          <Col span={8} className={styles.thirdField}><Form.Item name="affected_system_code" label="受影响系统"><Select options={categoryOptions.affected_system_code}/></Form.Item></Col>
          <Col span={8} className={styles.thirdField}><Form.Item name="source_type_code" label="疑似干扰源"><Select options={categoryOptions.source_type_code}/></Form.Item></Col>
        </Row>
      </div>
      <div className={styles.section}>
        <div className={styles.sectionTitle}>航空信息</div>
        <Row gutter={[20, 0]}>
          <Col span={8} className={styles.thirdField}><Form.Item name="flight_number" label="航班号"><Input/></Form.Item></Col>
          <Col span={8} className={styles.thirdField}><Form.Item name="aircraft_no" label="机号"><Input/></Form.Item></Col>
          <Col span={8} className={styles.thirdField}><Form.Item name="aircraft_type" label="机型"><Input/></Form.Item></Col>
        </Row>
      </div>
      <div className={styles.section}>
        <div className={styles.sectionTitle}>现象与判断</div>
        <Row gutter={[20, 0]}>
          <Col span={24}><Form.Item name="phenomenon" label="现象"><Input.TextArea rows={2}/></Form.Item></Col>
          <Col span={24}><Form.Item name="initial_assessment" label="初步判断"><Input.TextArea rows={1}/></Form.Item></Col>
          <Col span={24}><Form.Item name="remark" label="备注"><Input.TextArea rows={1}/></Form.Item></Col>
        </Row>
      </div>
      <Form.Item noStyle shouldUpdate={(previous, current) => previous.scene_code !== current.scene_code}>
        {({getFieldValue}) => <DetailFields scene={getFieldValue('scene_code')}/>}
      </Form.Item>
    </Form>
    {info.id && <>
      <div className={styles.sectionTitle}>附件</div>
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

export default observer(EventForm);

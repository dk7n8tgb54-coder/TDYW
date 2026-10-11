/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行与故障记录——统一进展工作区（2026-10-11 合并改造）。
 * 自 RecordDetail 拆出：内联新增进展（处理时间/处理人/处理内容/可选工时）
 * → 追加式时间线（进展附件随每条进展管理）→ 更正弹窗（原内容留痕）。
 * 约束：读取 store observable 的函数组件必须用 observer 包裹。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Spin, Button, Timeline, Tag, Modal, Form, Input, DatePicker,
  Select, InputNumber, Row, Col, Empty, message} from 'antd';
import moment from 'moment';
import {AuthButton, AttachmentManager} from 'components';
import {http} from 'libs';
import store from './store';
import {API_PREFIX, PERM} from '../constants';
import {sectionTitle} from './shared';

const {TextArea} = Input;

const ProgressTimeline = observer(function ProgressTimeline({editable}) {
  const d = store.detail;
  return (
    <div>
      <p style={{color: '#999', marginTop: 0}}>
        统一进展按时间追加记录的处理过程：现场检查、已采取措施、厂家送修/反馈、
        外委处理、测试验证、持续观察等均写入处理内容；原因结论请在基本信息
        "原因分析"中维护。
      </p>
      {editable && (
        <div style={{marginBottom: 12}}>
          <AddProgressForm/>
        </div>
      )}
      {sectionTitle('处理进展时间线')}
      <Spin spinning={store.isProgressFetching}>
        {store.progressRecords.length ? (
          <Timeline style={{marginTop: 8}}>
            {store.progressRecords.map(record => (
              <Timeline.Item key={record.id}>
                <div>
                  <b>{record.handled_at}</b>
                  <span style={{marginLeft: 8}}>处理人：{record.handler_name || '-'}</span>
                  {record.work_hours !== null && record.work_hours !== undefined && (
                    <Tag style={{marginLeft: 8}}>工时 {record.work_hours}h</Tag>
                  )}
                  {editable && <CorrectButton record={record}/>}
                </div>
                <div style={{marginTop: 4}}>{record.content}</div>
                <ProgressAttachments record={record} editable={editable}/>
                {(record.corrections || []).map((c, i) => (
                  <div key={i} style={{color: '#999', marginTop: 4, fontSize: 12}}>
                    更正记录：{c.at} 由 {c.by} 更正（原因：{c.reason}）
                  </div>
                ))}
              </Timeline.Item>
            ))}
          </Timeline>
        ) : (
          <Empty description="暂无处理进展" image={Empty.PRESENTED_IMAGE_SIMPLE}/>
        )}
      </Spin>
    </div>
  );
});

// 内联新增进展表单：处理时间缺省当前时间；处理人为手动输入姓名（回车确认
// 可多个）；工时选填；保存成功后清空表单，刷新由 store.addProgressRecord 完成
function AddProgressForm() {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const handleSubmit = () => {
    form.validateFields().then(values => {
      setSaving(true);
      store.addProgressRecord({
        handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
        handler_name: (values.handler_names || []).join('、'),
        content: values.content,
        work_hours: values.work_hours === undefined ? null : values.work_hours,
      }).then(() => {
        message.success('处理进展已追加');
        setSaving(false);
        form.resetFields();
        form.setFieldsValue({handled_at: moment()});
      }).catch(() => setSaving(false));
    }).catch(() => {});
  };
  return (
    <div style={{
      border: '1px solid #f0f0f0', borderRadius: 4,
      background: '#fafafa', padding: '12px 16px 0',
    }}>
      <Form form={form} layout="vertical">
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="handled_at"
              label="处理时间"
              initialValue={moment()}
              rules={[{required: true, message: '请选择处理时间'}]}
              style={{marginBottom: 12}}
            >
              <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm"
                style={{width: '100%'}}/>
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item
              name="handler_names"
              label="处理人"
              rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
              style={{marginBottom: 12}}
            >
              {/* open=false：仅手输姓名（回车/失焦添加）；必须内联不得包装转发：
                  Form.Item 以 cloneElement 注入 value/onChange */}
              <Select
                mode="tags"
                open={false}
                placeholder="输入姓名后回车确认（可多个）"
              />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name="work_hours"
              label="本次工时（小时，选填）"
              style={{marginBottom: 12}}
            >
              <InputNumber min={0} step={0.5} style={{width: '100%'}} placeholder="选填"/>
            </Form.Item>
          </Col>
        </Row>
        <Form.Item
          name="content"
          label="处理内容"
          rules={[{required: true, message: '请填写处理内容'}]}
          style={{marginBottom: 12}}
        >
          <TextArea rows={3} placeholder="如：现场检查情况、已采取的措施、厂家反馈、跟进结论等"/>
        </Form.Item>
        <Form.Item style={{textAlign: 'right', marginBottom: 12}}>
          <Button type="primary" loading={saving} onClick={handleSubmit}>
            追加进展
          </Button>
        </Form.Item>
      </Form>
    </div>
  );
}

function ProgressAttachments({record, editable}) {
  if (!record.id) return null;
  const base = `${API_PREFIX}/records/${store.detailId}/progress/${record.id}/attachments/`;
  return (
    <div style={{marginTop: 6}}>
      <AttachmentManager
        module="equipment_lifecycle"
        objectType="el_operation_progress"
        recordId={record.id}
        listUrl={base}
        uploadUrl={base}
        deleteRequest={att => http.delete(`${base}${att.id}/`)}
        downloadUrlPrefix={base}
        uploadPerm={PERM.OP_PROGRESS}
        deletePerm={PERM.OP_EDIT}
        downloadPerm={PERM.OP_VIEW}
        readOnly={!editable}
      />
    </div>
  );
}

function CorrectButton({record}) {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.OP_EDIT}
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => setVisible(true)}
      >
        更正
      </AuthButton>
      <ProgressModal
        visible={visible}
        record={record}
        onClose={() => setVisible(false)}
      />
    </span>
  );
}

// 更正处理进展弹窗（更正专用：新增走工作区内联表单）。原内容、修改内容与
// 更正原因一并留痕保存，不静默覆盖。
function ProgressModal({visible, record, onClose}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  // initialValues + destroyOnClose：每次打开重新挂载表单取最新值
  const initialValues = {
    handled_at: record.handled_at ? moment(record.handled_at, 'YYYY-MM-DD HH:mm') : null,
    handler_names: (record.handler_name || '').split('、').filter(Boolean),
    content: record.content,
    work_hours: record.work_hours === null || record.work_hours === undefined
      ? undefined : record.work_hours,
  };
  return (
    <Modal
      visible={visible}
      title="更正处理进展"
      destroyOnClose
      confirmLoading={loading}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          setLoading(true);
          store.correctProgressRecord(record.id, {
            handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
            handler_name: (values.handler_names || []).join('、'),
            content: values.content,
            work_hours: values.work_hours === undefined ? null : values.work_hours,
            correction_reason: values.correction_reason,
          }).then(() => {
            message.success('处理进展已更正');
            setLoading(false);
            onClose();
          }).catch(() => setLoading(false));
        }).catch(() => {});
      }}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}
        initialValues={initialValues}>
        <Form.Item
          name="handled_at"
          label="处理时间"
          rules={[{required: true, message: '请选择处理时间'}]}
        >
          <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item
          name="handler_names"
          label="处理人"
          rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
        >
          <Select
            mode="tags"
            open={false}
            placeholder="输入姓名后回车确认（可多个）"
          />
        </Form.Item>
        <Form.Item name="work_hours" label="本次工时（小时）">
          <InputNumber min={0} step={0.5} style={{width: '100%'}} placeholder="选填"/>
        </Form.Item>
        <Form.Item
          name="content"
          label="处理内容"
          rules={[{required: true, message: '请填写处理内容'}]}
        >
          <TextArea rows={3} placeholder="如：现场检查情况、已采取的措施、跟进结论等"/>
        </Form.Item>
        <Form.Item
          name="correction_reason"
          label="更正原因"
          rules={[{required: true, message: '更正必须填写原因，原内容将留痕保存'}]}
        >
          <TextArea rows={2} placeholder="原内容、修改内容与更正原因将一并保存"/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default ProgressTimeline;

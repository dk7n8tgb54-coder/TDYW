/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行处置记录——进展工作区（页签/条目名称随记录类型，见 shared.PROGRESS_TAB_TEXT）。
 * 自 RecordDetail 拆出：追加式时间线 → 更正弹窗（原内容留痕）。
 * 2026-10-14 新增进展入口迁至详情顶部动作按钮（弹窗承载，见
 * RecordDetailActions.AddProgressModal），本页签不再放内联表单。
 * 2026-10-13 本次工时退役：追加/更正表单与时间线展示一并移除（模型列与
 * 后端契约保留，历史数据不删仅不再展示，更正缺参时后端保旧值）。
 * 2026-10-13 进展级附件退役：时间线不再逐条挂附件入口，材料统一在详情
 * "附件"页签以记录级管理（el_operation_record）。
 * 约束：读取 store observable 的函数组件必须用 observer 包裹。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Spin, Button, Timeline, Modal, Form, Input, DatePicker,
  Select, Empty, message} from 'antd';
import moment from 'moment';
import {AuthButton} from 'components';
import store from './store';
import {PERM} from '../constants';
import {sectionTitle, PROGRESS_TAB_TEXT} from './shared';

const {TextArea} = Input;

const ProgressTimeline = observer(function ProgressTimeline({editable}) {
  const d = store.detail;
  // 类型未知（详情加载中）时回退通用名"处理进展"
  const typeLabel = PROGRESS_TAB_TEXT[d.record_type] || '处理进展';
  return (
    <div>
      <p style={{color: '#999', marginTop: 0}}>
        按时间追加记录的处理过程：现场检查、已采取措施、厂家送修/反馈、
        外委处理、测试验证、持续观察等均写入处理内容（通过详情顶部
        "添加{typeLabel}"按钮录入）
        {d.record_type === 'fault' ? '；原因结论请在基本信息"原因分析"中维护' : ''}。
      </p>
      {sectionTitle(`${typeLabel}时间线`)}
      <Spin spinning={store.isProgressFetching}>
        {store.progressRecords.length ? (
          <Timeline style={{marginTop: 8}}>
            {store.progressRecords.map(record => (
              <Timeline.Item key={record.id}>
                <div>
                  <b>{record.handled_at}</b>
                  <span style={{marginLeft: 8}}>处理人：{record.handler_name || '-'}</span>
                  {editable && <CorrectButton record={record}/>}
                </div>
                <div style={{marginTop: 4}}>{record.content}</div>
                {(record.corrections || []).map((c, i) => (
                  <div key={i} style={{color: '#999', marginTop: 4, fontSize: 12}}>
                    更正记录：{c.at} 由 {c.by} 更正（原因：{c.reason}）
                  </div>
                ))}
              </Timeline.Item>
            ))}
          </Timeline>
        ) : (
          <Empty description={`暂无${typeLabel}`} image={Empty.PRESENTED_IMAGE_SIMPLE}/>
        )}
      </Spin>
    </div>
  );
});

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
          // 不再提交 work_hours：后端更正对缺参保旧值，历史工时不被误清
          store.correctProgressRecord(record.id, {
            handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
            handler_name: (values.handler_names || []).join('、'),
            content: values.content,
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

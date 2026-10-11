/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行与故障记录——原因分析状态化单元格与专用弹窗（2026-10-11 合并改造）。
 * 自 RecordDetail 拆出：尚未分析/初步判断/最终原因/原因未明四态展示；
 * 保存走 reason-analysis 专用端点并静默刷新详情。
 */
import React, {useState, useEffect} from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Input, Checkbox, message} from 'antd';
import {AuthButton} from 'components';
import store from './store';
import {PERM} from '../constants';

const {TextArea} = Input;

const ReasonAnalysisCell = observer(function ReasonAnalysisCell({editable}) {
  const [modalVisible, setModalVisible] = useState(false);
  const d = store.detail;
  const unknown = !!d.reason_unknown;
  const content = d.reason_analysis || '';
  let display;
  if (unknown) {
    display = content ? `原因未明：${content}` : '原因未明';
  } else if (!content) {
    display = <span style={{color: 'rgba(0, 0, 0, 0.45)'}}>尚未分析</span>;
  } else if (d.status === 'closed') {
    display = `最终原因：${content}`;
  } else {
    display = `初步判断：${content}`;
  }
  return (
    <div>
      <div style={{whiteSpace: 'pre-wrap'}}>{display}</div>
      {editable && (
        <AuthButton
          auth={PERM.OP_EDIT}
          type="link"
          size="small"
          style={{padding: 0, marginTop: 4}}
          onClick={() => setModalVisible(true)}
        >
          {unknown || content ? '修改' : '补充原因分析'}
        </AuthButton>
      )}
      <ReasonAnalysisModal
        visible={modalVisible}
        onClose={() => setModalVisible(false)}
      />
    </div>
  );
});

// 原因分析专用弹窗：只处理原因分析，不要求重新提交系统/发生时间等无关字段；
// 未明勾选后切换为必填"未明说明"；保存走专用端点并静默刷新详情
function ReasonAnalysisModal({visible, onClose}) {
  const [form] = Form.useForm();
  const d = store.detail;
  useEffect(() => {
    if (visible) {
      form.resetFields();
      form.setFieldsValue({
        reason_analysis: d.reason_analysis || '',
        reason_unknown: !!d.reason_unknown,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);
  return (
    <Modal
      visible={visible}
      title={(d.reason_unknown || d.reason_analysis) ? '修改原因分析' : '补充原因分析'}
      confirmLoading={store.isActionSubmitting}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          store.saveReasonAnalysis({
            reason_analysis: (values.reason_analysis || '').trim(),
            reason_unknown: !!values.reason_unknown,
          }).then(() => {
            message.success('原因分析已保存');
            onClose();
          }).catch(() => {});
        }).catch(() => {});
      }}
    >
      <p style={{color: 'rgba(0, 0, 0, 0.45)', marginTop: 0}}>
        原因分析是当前阶段的原因结论；排查过程与依据请在"统一进展"中记录。
      </p>
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item name="reason_unknown" valuePropName="checked" label="原因未明">
          <Checkbox>确实无法确定原因（以未明说明代替原因结论）</Checkbox>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={
          (prev, cur) => prev.reason_unknown !== cur.reason_unknown
        }>
          {({getFieldValue}) => {
            const isUnknown = !!getFieldValue('reason_unknown');
            return (
              <Form.Item
                name="reason_analysis"
                label={isUnknown ? '未明说明' : '原因分析'}
                rules={isUnknown
                  ? [{required: true, message: '选择"原因未明"时请填写未明说明'}]
                  : []}
                extra={isUnknown
                  ? '说明目前排查情况与无法确定原因的依据，处置过程中可继续排查补充'
                  : undefined}
              >
                <TextArea
                  rows={4}
                  placeholder={isUnknown
                    ? '说明目前的排查情况与无法确定原因的依据'
                    : '已知时填写，暂时无法判断可留空，处置过程中可继续补充'}
                />
              </Form.Item>
            );
          }}
        </Form.Item>
      </Form>
    </Modal>
  );
}

// observer 必须包裹：时间线读取 progressRecords/isProgressFetching。
// 统一进展工作区（内联录入）：新增进展（处理时间/处理人/处理内容/可选工时）

export default ReasonAnalysisCell;

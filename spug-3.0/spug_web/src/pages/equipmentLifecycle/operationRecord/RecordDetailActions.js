/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行与故障记录——详情顶部动作按钮与动作弹窗（2026-10-11 合并改造）。
 * 自 RecordDetail 拆出（文件行数治理）：编辑/删除/完成跟进/认定正式故障/
 * 确认恢复并结案/撤销故障登记；动作成功后由 store 统一刷新真实数据，
 * 错误提示由 http 拦截器统一弹出。
 * 约束：读取 store observable 的函数组件必须用 observer 包裹。
 */
import React, {useState} from 'react';
import {observer} from 'mobx-react';
import {Modal, Form, Input, Select, DatePicker, Checkbox, message} from 'antd';
import moment from 'moment';
import {AuthButton} from 'components';
import store from './store';
import {PERM, FAULT_IMPACT_TEXT} from '../constants';

const {TextArea} = Input;

export function AuthEditButton() {
  return (
    <AuthButton
      auth={PERM.OP_EDIT}
      onClick={() => store.showForm(store.detail)}
    >
      编辑
    </AuthButton>
  );
}

// 删除记录（仅日常运行；后端独立校验记录类型）：确认后物理删除并联动清理附件
export function AuthDeleteButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.OP_DEL}
        type="danger"
        ghost
        onClick={() => setVisible(true)}
      >
        删除
      </AuthButton>
      <Modal
        visible={visible}
        title="删除运行记录"
        confirmLoading={store.isActionSubmitting}
        onCancel={() => setVisible(false)}
        onOk={() => {
          store.deleteRecord()
            .then(() => {
              message.success('运行记录已删除');
              setVisible(false);
            })
            .catch(() => {});
        }}
      >
        <p>确认删除该日常运行记录？删除后不可恢复。</p>
        <p style={{color: 'rgba(0, 0, 0, 0.45)', marginBottom: 0}}>
          记录附件将一并清理。
        </p>
      </Modal>
    </span>
  );
}

// 顶部主行动按钮（开始跟进/新增跟进记录/重新跟进）统一外壳
export function AuthPrimaryActionButton({auth, text, onClick}) {
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={auth} type="primary" onClick={onClick}>{text}</AuthButton>
    </span>
  );
}

// 完成跟进：跟进中 → 已完成（纯确认动作，完成后可重新跟进）
export function AuthCompleteButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.OP_COMPLETE} onClick={() => setVisible(true)}>
        完成跟进
      </AuthButton>
      <Modal
        visible={visible}
        title="完成跟进"
        confirmLoading={store.isActionSubmitting}
        onCancel={() => setVisible(false)}
        onOk={() => {
          store.completeFollowUp()
            .then(() => {
              message.success('已完成跟进');
              setVisible(false);
            }).catch(() => {});
        }}
      >
        <p>完成后记录进入"已完成"，可随时重新跟进，无需关闭。</p>
        <p style={{color: 'rgba(0, 0, 0, 0.45)', marginBottom: 0}}>
          如需留档最终说明，请先在统一进展中追加一条收尾进展。
        </p>
      </Modal>
    </span>
  );
}

// 认定正式故障（异常事件原记录原地变更）：补充故障所需字段，一次弹窗一次提交
export function AuthIdentifyFaultButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.OP_IDENTIFY_FAULT} type="primary" danger
        onClick={() => setVisible(true)}>
        认定正式故障
      </AuthButton>
      <IdentifyFaultModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

const IdentifyFaultModal = observer(function IdentifyFaultModal({visible, onClose}) {
  const [form] = Form.useForm();
  return (
    <Modal
      visible={visible}
      title="认定正式故障"
      confirmLoading={store.isActionSubmitting}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          store.identifyFault({
            affects_system_operation: !!values.affects_system_operation,
            impact_status: values.impact_status || '',
            reason_analysis: values.reason_analysis || '',
            fault_object_name: values.fault_object_name || '',
          }).then(() => {
            message.success('已认定为正式故障（同一条记录，进展与附件保留）');
            onClose();
          }).catch(() => {});
        }).catch(() => {});
      }}
    >
      <p style={{color: 'rgba(0, 0, 0, 0.45)', marginTop: 0}}>
        在本条记录上认定为正式故障：类型变更为"正式故障"、状态进入"处置中"，
        原描述、登记人、附件与全部进展原样保留，不会创建第二张故障单。
      </p>
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}
        initialValues={{affects_system_operation: false}}>
        <Form.Item
          name="affects_system_operation"
          label="影响系统运行"
          valuePropName="checked"
          extra="默认关闭：部件故障、离线维修不影响系统对外服务"
        >
          <Checkbox>影响系统运行（按影响程度参与系统健康状态计算）</Checkbox>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={
          (prev, cur) => prev.affects_system_operation !== cur.affects_system_operation
        }>
          {({getFieldValue}) => getFieldValue('affects_system_operation') ? (
            <Form.Item
              name="impact_status"
              label="系统影响程度"
              preserve={false}
              rules={[{required: true, message: '请选择系统影响程度'}]}
            >
              <Select placeholder="降级 / 故障 / 中断">
                {['degraded', 'fault', 'interrupted'].map(v => (
                  <Select.Option value={v} key={v}>
                    {FAULT_IMPACT_TEXT[v]}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
          ) : null}
        </Form.Item>
        <Form.Item name="fault_object_name" label="故障部位/设备">
          <Input placeholder="选填，如 信道机 / 天馈系统"/>
        </Form.Item>
        <Form.Item name="reason_analysis" label="初步原因分析">
          <TextArea rows={3} placeholder="已知时填写，暂时无法判断可留空"/>
        </Form.Item>
      </Form>
    </Modal>
  );
});

// 确认恢复并结案（正式故障）：恢复时间/恢复确认人/最终原因分析/结案说明
// 一次填写一次校验，提交后直接进入终态"已关闭"。
// 合并操作须同时具备 recover 与 close 两项权限（AuthButton 以 & 表达 AND，
// 后端独立校验，不因按钮合并放宽权限边界）。
export function AuthRecoverAndCloseButton({record}) {
  const [visible, setVisible] = useState(false);
  const [form] = Form.useForm();
  return (
    <span>
      <AuthButton
        auth={`${PERM.OP_RECOVER}&${PERM.OP_CLOSE}`}
        type="primary"
        onClick={() => setVisible(true)}
      >
        确认恢复并结案
      </AuthButton>
      <RecoverModal visible={visible} form={form} record={record}
        onClose={() => setVisible(false)}/>
    </span>
  );
}

const RecoverModal = observer(function RecoverModal({visible, form, record, onClose}) {
  const initialValues = {
    // 恢复时间默认当前时间（存量数据预填既有恢复时间），可修改
    recovered_at: record.recovered_at
      ? moment(record.recovered_at, 'YYYY-MM-DD HH:mm') : moment(),
    // 恢复确认人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），
    // 只表示实际确认恢复的人；必填、不预填登录账号
    recovered_by_names: record.recovered_by_name
      ? record.recovered_by_name.split('、').filter(Boolean) : [],
    recovery_close_note: record.recovery_close_note || '',
    // 最终原因分析：默认回填处置中的原因分析，结案前可修改
    reason_analysis: record.reason_analysis || '',
    reason_unknown: !!record.reason_unknown,
  };
  return (
    <Modal
      visible={visible}
      title="确认恢复并结案"
      destroyOnClose
      confirmLoading={store.isActionSubmitting}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          store.confirmRecoverAndClose({
            recovered_at: values.recovered_at.format('YYYY-MM-DD HH:mm'),
            // 标签数组以顿号拼接为恢复确认人姓名文本（多人）
            recovered_by_name: (values.recovered_by_names || []).join('、'),
            recovery_close_note: (values.recovery_close_note || '').trim(),
            reason_analysis: values.reason_analysis || '',
            reason_unknown: !!values.reason_unknown,
          }).then(() => {
            message.success('已确认恢复并结案');
            onClose();
          }).catch(() => {});
        }).catch(() => {});
      }}
    >
      <p style={{color: 'rgba(0, 0, 0, 0.45)', marginTop: 0}}>
        提交后故障直接进入"已关闭"终态，不可再编辑或追加进展。
      </p>
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}
        initialValues={initialValues}>
        <Form.Item
          name="recovered_at"
          label="恢复时间"
          rules={[{required: true, message: '请选择恢复时间'}]}
        >
          <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item
          name="recovered_by_names"
          label="恢复确认人"
          rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
        >
          {/* open=false：仅手输姓名（回车/失焦添加） */}
          <Select
            mode="tags"
            open={false}
            placeholder="输入姓名后回车确认（可多个）"
          />
        </Form.Item>
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
                label={isUnknown ? '未明说明' : '最终原因分析'}
                rules={isUnknown
                  ? [{required: true, message: '选择"原因未明"时请填写未明说明'}]
                  : []}
              >
                <TextArea
                  rows={3}
                  placeholder={isUnknown
                    ? '说明目前的排查情况与无法确定原因的依据'
                    : '默认回填处置过程中的原因分析，可修改后随结案保存'}
                />
              </Form.Item>
            );
          }}
        </Form.Item>
        <Form.Item
          name="recovery_close_note"
          label="结案说明"
          rules={[{required: true, whitespace: true, message: '请填写结案说明'}]}
        >
          <TextArea
            rows={3}
            placeholder="请说明采取的处理措施、恢复验证依据及最终结果"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
});

// 撤销故障登记（正式故障处置中）：错误/重复登记受控撤销，原因必填留痕
export const AuthCancelButton = observer(function AuthCancelButton({record}) {
  const [visible, setVisible] = useState(false);
  const [reason, setReason] = useState('');
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.OP_CANCEL} danger onClick={() => setVisible(true)}>
        撤销故障登记
      </AuthButton>
      <Modal
        visible={visible}
        title="撤销故障登记确认"
        confirmLoading={store.isActionSubmitting}
        onCancel={() => setVisible(false)}
        onOk={() => {
          if (!reason.trim()) {
            message.warning('请填写撤销原因');
            return;
          }
          store.cancelRecord({cancel_reason: reason.trim()})
            .then(() => {
              message.success('故障登记已撤销');
              setVisible(false);
            })
            .catch(() => {});
        }}
      >
        <p style={{marginTop: 0}}>
          确定撤销故障登记「{record.record_no}」吗？
        </p>
        <ul style={{color: 'rgba(0, 0, 0, 0.65)', paddingLeft: 18, margin: '8px 0'}}>
          <li>该操作用于撤销错误或重复的故障登记；</li>
          <li>撤销后不会删除历史记录，可随时通过"状态=已撤销"筛选查看；</li>
          <li>撤销后该记录不再参与有效故障统计和系统健康状态计算；</li>
          <li>撤销原因必须填写。</li>
        </ul>
        <Input.TextArea
          rows={3}
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="请填写撤销原因（必填），如：误报、重复登记、填写有误需重新登记"
        />
      </Modal>
    </span>
  );
});

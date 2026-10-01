/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障详情抽屉（步骤 3.1，单系统简化）。
 * 基本信息 / 处理进展时间线（追加式，支持更正留痕、工时）/ 恢复确认 / 关闭 / 作废。
 * 处理进展记录故障整体跟进（检查、本方处理、送厂、厂家反馈、返还、测试、持续观察
 * 等）并承接原工单处理记录的工时；关联工单/生成维修工单已随工单功能删除（2026-09-30）；
 * 人员展示口径：故障登记人/恢复确认人/进展记录人均为手动输入姓名（实际
 * 登记/确认/记录的人，不关联用户账号），均不代表负责整个故障；
 * 处置负责人/发现方式/级别/影响范围/故障位置字段已删除（2026-09）；
 * 不再提供"受影响系统"页签；所有动作成功后重新获取真实数据；
 * 错误提示由 http 拦截器统一弹出，不重复提示。
 * 约束：凡在 render 中读取 store observable 的函数组件必须用 observer 包裹
 * （MobX 只追踪 observer 组件自身的读取），否则对应区域不会随 store 更新。
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Drawer, Tabs, Descriptions, Tag, Spin, Button, Timeline, Modal, Form,
  Input, InputNumber, DatePicker, Select, Popconfirm, message, Empty } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import moment from 'moment';
import { AuthButton } from 'components';
import { history } from 'libs';
import store from './faultStore';
import { LEDGER_TYPE_PATH } from './ledger/constants';
import {
  PERM, FAULT_STATUS_TEXT, FAULT_STATUS_COLOR, FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR,
  FAULT_PROGRESS_TYPE_OPTIONS,
} from './constants';

const {TextArea} = Input;
const {TabPane} = Tabs;

// 本次工时（小时）：选填，非负（工单下线后由处理进展承接工时登记）
const WORK_HOURS_RULE = [{
  validator: (_, value) => (
    value === undefined || value === null || (typeof value === 'number' && value >= 0)
      ? Promise.resolve() : Promise.reject(new Error('工时不能为负数'))),
}];

@observer
class FaultDetail extends React.Component {
  // 详情与处理进展请求由 store.showDetail 统一发起，挂载时不再重复请求
  renderBasic() {
    const d = store.detail;
    return (
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="故障编号">{d.fault_no}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={FAULT_STATUS_COLOR[d.status]}>{FAULT_STATUS_TEXT[d.status]}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="故障系统">
          {d.system_name}
        </Descriptions.Item>
        <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="系统影响程度">
          {d.affects_system_operation ? (
            <Tag color={FAULT_IMPACT_COLOR[d.impact_status]}>
              {FAULT_IMPACT_TEXT[d.impact_status]}
            </Tag>
          ) : (
            // 部件故障/离线维修：不影响系统对外服务，独立于系统运行状态展示
            <Tag>不影响运行</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="发生时间">{d.occurred_at}</Descriptions.Item>
        {/* 删除字段后单格数为奇数：登记人独占一行，避免 Descriptions 列跨度告警 */}
        <Descriptions.Item label="故障登记人" span={2}>{d.registrar_name || '-'}</Descriptions.Item>
        {/* 展示顺序与新增/编辑表单一致：故障部位/设备位于故障现象之前；
            对象型号/序列号/组成项为精简前的存量快照，仅展示 */}
        <Descriptions.Item label="故障部位/设备" span={2}>
          {[d.fault_object_name, d.fault_object_model, d.fault_object_sn]
            .filter(Boolean).join(' / ') || '-'}
          {d.fault_component_name ? `（组成项：${d.fault_component_name}）` : ''}
        </Descriptions.Item>
        <Descriptions.Item label="故障现象" span={2}>{d.phenomenon}</Descriptions.Item>
        <Descriptions.Item label="原因分析" span={2}>{d.reason_analysis || '-'}</Descriptions.Item>
        <Descriptions.Item label="恢复时间">{d.recovered_at || '-'}</Descriptions.Item>
        <Descriptions.Item label="恢复确认人">
          {d.recovered_by_name ? `${d.recovered_by_name}（${d.recovered_confirmed_at || ''}）` : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="恢复确认信息" span={2}>{d.recover_confirm || '-'}</Descriptions.Item>
        <Descriptions.Item label="最终结果" span={2}>{d.final_result || '-'}</Descriptions.Item>
        {/* 步骤 3.3：来源台账追溯（台账异常转故障后可跳回来源台账明细）；
            旧巡检台账（历史）已删除：来源明细被删除的故障回落 legacy 快照，
            仅展示台账号文本，不做跳转 */}
        {d.source_type === 'ledger_item' && d.source_ledger && (
          <Descriptions.Item label="来源台账" span={2}>
            <Button
              type="link"
              size="small"
              style={{padding: 0}}
              onClick={() => {
                const path = LEDGER_TYPE_PATH[d.source_ledger_type];
                if (path) {
                  store.closeDetail();
                  history.push(`${path}?detail=${d.source_ledger}`);
                }
              }}
            >
              {d.source_ledger_no || '查看来源台账'}
            </Button>
          </Descriptions.Item>
        )}
        {d.source_type === 'ledger_item' && !d.source_ledger && d.source_ledger_no && (
          <Descriptions.Item label="来源台账" span={2}>
            {d.source_ledger_no}（旧巡检台账（历史）已删除，来源为历史台账明细）
          </Descriptions.Item>
        )}
        {/* 值班巡检改造：新巡检异常转故障跳转到来源巡检单（与旧台账来源互不影响） */}
        {d.source_type === 'inspection_record' && d.source_inspection_sheet && (
          <Descriptions.Item label="来源巡检单" span={2}>
            <Button
              type="link"
              size="small"
              style={{padding: 0}}
              onClick={() => {
                store.closeDetail();
                history.push(`/el/inspection-sheets?detail=${d.source_inspection_sheet}`);
              }}
            >
              {d.source_inspection_sheet_no || '查看来源巡检单'}
            </Button>
          </Descriptions.Item>
        )}
        <Descriptions.Item label="创建人">{d.created_by_name}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{d.created_at}</Descriptions.Item>
      </Descriptions>
    );
  }

  render() {
    const d = store.detail;
    const editable = d.status === 'pending' || d.status === 'handling' || d.status === 'recovered';
    return (
      <Drawer
        title={`故障详情 - ${d.fault_no || ''}`}
        visible={store.detailVisible}
        width={900}
        onClose={() => store.closeDetail()}
        destroyOnClose
      >
        <Spin spinning={store.isDetailFetching}>
          <div style={{marginBottom: 12}}>
            {d.status === 'pending' && (
              <AuthStartButton/>
            )}
            {d.status === 'handling' && (
              <AuthRecoverButton/>
            )}
            {d.status === 'recovered' && (
              <AuthCloseButton/>
            )}
            {editable && (
              <AuthCancelButton fault={d}/>
            )}
          </div>
          <Tabs defaultActiveKey="basic">
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            <TabPane tab="处理进展" key="handling">
              <HandlingTimeline editable={editable}/>
            </TabPane>
          </Tabs>
        </Spin>
      </Drawer>
    );
  }
}

const AuthStartButton = observer(function AuthStartButton() {
  return (
    <AuthButton
      auth={PERM.FAULT_HANDLE}
      type="primary"
      loading={store.isActionSubmitting}
      onClick={() => store.startHandling()
        .then(() => message.success('已开始处置'))
        .catch(() => {})}
    >
      开始处置
    </AuthButton>
  );
});

function AuthRecoverButton() {
  const [visible, setVisible] = useState(false);
  const [form] = Form.useForm();
  return (
    <span>
      <AuthButton auth={PERM.FAULT_RECOVER} type="primary" onClick={() => setVisible(true)}>
        确认恢复
      </AuthButton>
      <RecoverModal visible={visible} form={form} onClose={() => setVisible(false)}/>
    </span>
  );
}

function AuthCloseButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span>
      <AuthButton auth={PERM.FAULT_CLOSE} type="primary" onClick={() => setVisible(true)}>
        关闭故障
      </AuthButton>
      <CloseModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

const AuthCancelButton = observer(function AuthCancelButton({fault}) {
  const [visible, setVisible] = useState(false);
  const [reason, setReason] = useState('');
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.FAULT_DEL} danger onClick={() => setVisible(true)}>作废</AuthButton>
      <Modal
        visible={visible}
        title="作废确认"
        confirmLoading={store.isActionSubmitting}
        onCancel={() => setVisible(false)}
        onOk={() => {
          if (!reason.trim()) {
            message.warning('请填写作废原因');
            return;
          }
          store.cancelFault({cancel_reason: reason.trim()})
            .then(() => {
              message.success('故障已作废');
              setVisible(false);
            })
            .catch(() => {});
        }}
      >
        <p>作废后故障不参与系统健康状态计算，且不可恢复。确定作废故障「{fault.fault_no}」吗？</p>
        <Input.TextArea
          rows={3}
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="请填写作废原因（必填）"
        />
      </Modal>
    </span>
  );
});

const RecoverModal = observer(function RecoverModal({visible, form, onClose}) {
  return (
    <Modal
      visible={visible}
      title="恢复确认"
      confirmLoading={store.isActionSubmitting}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          store.confirmRecover({
            recovered_at: values.recovered_at.format('YYYY-MM-DD HH:mm'),
            // 标签数组以顿号拼接为恢复确认人姓名文本（多人）
            recovered_by_name: (values.recovered_by_names || []).join('、'),
            recover_confirm: values.recover_confirm,
            final_result: values.final_result || '',
          }).then(() => {
            message.success('已确认恢复');
            onClose();
          }).catch(() => {});
        }).catch(() => {});
      }}
    >
      {/* 恢复时间默认当前时间（与处理进展"进展时间"默认一致），可修改 */}
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}
        initialValues={{recovered_at: moment()}}>
        <Form.Item
          name="recovered_at"
          label="恢复时间"
          rules={[{required: true, message: '请选择恢复时间'}]}
        >
          <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
        </Form.Item>
        {/* 恢复确认人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），
            只表示实际确认恢复的人；必填、不预填，与登录账号审计字段独立 */}
        <Form.Item
          name="recovered_by_names"
          label="恢复确认人"
          rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
        >
          {/* open=false：仅手输姓名（回车/失焦添加），与故障登记人输入一致 */}
          <Select
            mode="tags"
            open={false}
            placeholder="输入姓名后回车确认（可多个）"
          />
        </Form.Item>
        <Form.Item
          name="recover_confirm"
          label="恢复确认信息"
          rules={[{required: true, message: '请填写恢复确认信息'}]}
        >
          <TextArea rows={3} placeholder="确认系统已恢复的依据，如业务验证结果"/>
        </Form.Item>
        <Form.Item name="final_result" label="最终结果">
          <TextArea rows={2} placeholder="（可选，关闭故障前必须填写）"/>
        </Form.Item>
      </Form>
    </Modal>
  );
});

const CloseModal = observer(function CloseModal({visible, onClose}) {
  const [result, setResult] = useState('');
  const d = store.detail;
  return (
    <Modal
      visible={visible}
      title="关闭确认"
      confirmLoading={store.isActionSubmitting}
      onCancel={() => {
        onClose();
        setResult('');
      }}
      onOk={() => {
        if (!result.trim() && !d.final_result) {
          message.warning('未填写最终结果，不能关闭');
          return;
        }
        store.closeFault({final_result: result.trim()})
          .then(() => {
            message.success('故障已关闭');
            onClose();
            setResult('');
          })
          .catch(() => {});
      }}
    >
      <p>
        关闭前必须已填写恢复时间、恢复确认人与最终结果。
        关闭后故障不可再编辑（更正需另行审批处理）。
      </p>
      {d.final_result ? (
        <p>已填最终结果：{d.final_result}</p>
      ) : (
        <Input.TextArea
          rows={3}
          value={result}
          onChange={e => setResult(e.target.value)}
          placeholder="请填写最终结果（必填）"
        />
      )}
    </Modal>
  );
});

// observer 必须包裹：时间线读取 handlingRecords/isHandlingFetching，
// 未包裹时这两项变化不触发重渲染——添加进展后新记录不显示、Spin 状态冻结
const HandlingTimeline = observer(function HandlingTimeline({editable}) {
  return (
    <div>
      <p style={{color: '#999', marginTop: 0}}>
        处理进展记录故障的整体跟进（检查、临时措施、本方处理、送厂、厂家反馈、返还、
        测试、持续观察等），并支持逐条登记工时；无需再另行生成维修工单。
      </p>
      {editable && (
        <div style={{marginBottom: 12}}>
          <AddHandlingButton/>
        </div>
      )}
      <Spin spinning={store.isHandlingFetching}>
        {store.handlingRecords.length ? (
          <Timeline style={{marginTop: 8}}>
            {store.handlingRecords.map(record => (
              <Timeline.Item key={record.id}>
                <div>
                  <b>{record.handled_at}</b>
                  {/* 进展记录人优先手动姓名；历史记录无姓名时回落操作账号用户名 */}
                  <span style={{marginLeft: 8}}>
                    进展记录人：{record.recorder_name || record.handler_name || '-'}
                  </span>
                  {record.progress_type_text && (
                    <Tag style={{marginLeft: 8}}>{record.progress_type_text}</Tag>
                  )}
                  {record.result && <Tag style={{marginLeft: 8}}>{record.result}</Tag>}
                  {record.work_hours !== null && record.work_hours !== undefined && (
                    <Tag style={{marginLeft: 8}}>工时 {record.work_hours}h</Tag>
                  )}
                  {editable && (
                    <CorrectButton record={record}/>
                  )}
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
          <Empty description="暂无处理进展" image={Empty.PRESENTED_IMAGE_SIMPLE}/>
        )}
      </Spin>
    </div>
  );
});

function AddHandlingButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span>
      <AuthButton
        auth={PERM.FAULT_HANDLE}
        type="primary"
        icon={<PlusOutlined/>}
        onClick={() => setVisible(true)}
      >
        添加处理进展
      </AuthButton>
      <HandlingModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

function CorrectButton({record}) {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.FAULT_EDIT}
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => setVisible(true)}
      >
        更正
      </AuthButton>
      <HandlingModal
        visible={visible}
        record={record}
        onClose={() => setVisible(false)}
      />
    </span>
  );
}

function HandlingModal({visible, record, onClose}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const isCorrect = !!record;
  useEffect(() => {
    if (visible) {
      form.resetFields();
      if (isCorrect) {
        // 更正时回显原进展记录人（历史记录无姓名回落操作账号用户名）
        const prevRecorder = record.recorder_name || record.handler_name || '';
        form.setFieldsValue({
          handled_at: record.handled_at ? moment(record.handled_at, 'YYYY-MM-DD HH:mm') : null,
          recorder_names: prevRecorder ? prevRecorder.split('、').filter(Boolean) : [],
          progress_type: record.progress_type || undefined,
          content: record.content,
          result: record.result,
          work_hours: record.work_hours ?? undefined,
        });
      } else {
        // 新增进展：时间默认当前时间；进展记录人为手动输入姓名（回车确认，
        // 可多个），不预填默认姓名；进展类型/处理结果选填
        form.setFieldsValue({
          handled_at: moment(),
          recorder_names: [],
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);
  return (
    <Modal
      visible={visible}
      title={isCorrect ? '更正处理进展' : '添加处理进展'}
      confirmLoading={loading}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          setLoading(true);
          const payload = {
            handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
            // 标签数组以顿号拼接为记录人姓名文本（多人）
            recorder_name: (values.recorder_names || []).join('、'),
            progress_type: values.progress_type || '',
            content: values.content,
            result: values.result || '',
            work_hours: values.work_hours ?? null,
          };
          const request = isCorrect
            ? store.correctHandlingRecord(record.id, {...payload,
                correction_reason: values.correction_reason})
            : store.addHandlingRecord(payload);
          request.then(() => {
            message.success(isCorrect ? '处理进展已更正' : '处理进展已添加');
            setLoading(false);
            onClose();
          }).catch(() => setLoading(false));
        }).catch(() => {});
      }}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
        <Form.Item
          name="handled_at"
          label="进展时间"
          rules={[{required: true, message: '请选择进展时间'}]}
        >
          <DatePicker showTime={{format: 'HH:mm'}} format="YYYY-MM-DD HH:mm" style={{width: '100%'}}/>
        </Form.Item>
        {/* 进展记录人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），
            只表示实际添加本条进展的人，不代表负责整个故障；必填、不预填 */}
        <Form.Item
          name="recorder_names"
          label="进展记录人"
          rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
        >
          {/* open=false：仅手输姓名（回车/失焦添加），与今日巡检值班人员输入一致 */}
          <Select
            mode="tags"
            open={false}
            placeholder="输入姓名后回车确认（可多个）"
          />
        </Form.Item>
        <Form.Item name="progress_type" label="进展类型">
          <Select
            allowClear
            placeholder="选填：检查 / 本方处理 / 送厂 / 厂家反馈 / 返还 / 测试 / 持续观察 / 其他"
          >
            {FAULT_PROGRESS_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item
          name="content"
          label="进展内容"
          rules={[{required: true, message: '请填写进展内容'}]}
        >
          <TextArea rows={3} placeholder="如：现场检查情况、已采取的临时措施、送厂安排、厂家反馈、返还及复测、持续观察结论等"/>
        </Form.Item>
        <Form.Item name="result" label="处理结果">
          <Input placeholder="选填，如：已临时保障 / 待厂家维修中 / 复测通过"/>
        </Form.Item>
        <Form.Item name="work_hours" label="本次工时" rules={WORK_HOURS_RULE}>
          <InputNumber min={0} step={0.5} style={{width: 160}} placeholder="选填，小时"/>
        </Form.Item>
        {isCorrect && (
          <Form.Item
            name="correction_reason"
            label="更正原因"
            rules={[{required: true, message: '更正必须填写原因，原内容将留痕保存'}]}
          >
            <TextArea rows={2} placeholder="原内容、修改内容与更正原因将一并保存"/>
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

export default FaultDetail;

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录详情抽屉（2026-10 第一版 + 第二版闭环）。
 * 基本信息 / 处理进展时间线（追加式、更正留痕）/ 重复问题（相似关联）/
 * 附件（AttachmentManager）。
 * 动作：编辑、提交研判（待研判）、研判（TriageModal）、标记需要跟进（可填
 * 跟进人/计划处理时间）、标记已处理、标记重要（必填原因）、转为故障、关闭；
 * - converted_fault/closed 为终态：正式处置以关联故障为准，详情提供故障入口；
 * - 标记重要只在普通 → 重要升级时由后端生成履历，重复标记后端拒绝；
 * - 所有动作成功后重新获取真实数据；错误提示由 http 拦截器统一弹出，
 *   业务代码不重复提示。
 * 约束：凡在 render 中读取 store observable 的函数组件必须用 observer 包裹。
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Drawer, Tabs, Descriptions, Tag, Spin, Button, Timeline, Modal, Form,
  Input, InputNumber, DatePicker, Select, Popconfirm, message, Empty } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import moment from 'moment';
import { AuthButton, AttachmentManager } from 'components';
import { http } from 'libs';
import { history } from 'libs';
import store from './store';
import TriageModal from './TriageModal';
import DuplicatePanel from './DuplicatePanel';
import { API_PREFIX, PERM, RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR,
  RUNTIME_IMPACT_TEXT, RUNTIME_IMPACT_COLOR, RUNTIME_CATEGORY_TEXT } from '../constants';

const {TextArea} = Input;
const {TabPane} = Tabs;

const EDITABLE_STATUSES = ['recorded', 'following_up', 'resolved'];
const WORK_HOURS_RULE = [{
  validator: (_, value) => (
    value === undefined || value === null || (typeof value === 'number' && value >= 0)
      ? Promise.resolve() : Promise.reject(new Error('工时不能为负数'))),
}];

@observer
class RecordDetail extends React.Component {
  renderBasic() {
    const d = store.detail;
    return (
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="运行记录编号">{d.record_no}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={RUNTIME_STATUS_COLOR[d.status]}>{RUNTIME_STATUS_TEXT[d.status]}</Tag>
          {d.needs_follow_up && <Tag color="blue">需要跟进</Tag>}
        </Descriptions.Item>
        <Descriptions.Item label="所属系统">{d.system_name}</Descriptions.Item>
        <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="发生时间">{d.occurred_at}</Descriptions.Item>
        <Descriptions.Item label="重要程度">
          <Tag color={d.importance === 'important' ? 'red' : 'default'}>
            {d.importance === 'important' ? '重要' : '普通'}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="标题" span={2}>{d.title}</Descriptions.Item>
        <Descriptions.Item label="情况描述" span={2}>{d.description}</Descriptions.Item>
        <Descriptions.Item label="系统影响程度">
          {d.affects_system_operation ? (
            <Tag color={RUNTIME_IMPACT_COLOR[d.impact_status]}>
              {RUNTIME_IMPACT_TEXT[d.impact_status] || d.impact_status}
            </Tag>
          ) : (
            <Tag>不影响运行</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="重要原因">{d.importance_reason || '-'}</Descriptions.Item>
        <Descriptions.Item label="异常类别">
          {d.category ? (RUNTIME_CATEGORY_TEXT[d.category] || d.category) : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="具体对象/型号">
          {[d.object_name, d.object_model].filter(Boolean).join(' / ') || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="初步原因" span={2}>{d.initial_reason || '-'}</Descriptions.Item>
        <Descriptions.Item label="影响范围" span={2}>{d.impact_scope || '-'}</Descriptions.Item>
        <Descriptions.Item label="已采取措施" span={2}>{d.measures_taken || '-'}</Descriptions.Item>
        <Descriptions.Item label="处理结果" span={2}>{d.handling_result || '-'}</Descriptions.Item>
        <Descriptions.Item label="关联故障" span={2}>
          {d.converted_fault ? (
            <Button
              type="link"
              size="small"
              style={{padding: 0}}
              onClick={() => {
                store.closeDetail();
                history.push(`/el/faults?detail=${d.converted_fault}`);
              }}
            >
              {d.converted_fault_no || '查看关联故障'}（后续处理以故障为准）
            </Button>
          ) : (d.status === 'converted_fault' ? '关联故障已作废' : '-')}
        </Descriptions.Item>
        <Descriptions.Item label="创建人">{d.created_by_name}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{d.created_at}</Descriptions.Item>
        {d.importance_marked_at && (
          <Descriptions.Item label="标记重要" span={2}>
            {d.importance_marked_by_name
              ? `${d.importance_marked_by_name}（${d.importance_marked_at}）`
              : d.importance_marked_at}
          </Descriptions.Item>
        )}
        {d.triaged_at && (
          <Descriptions.Item label="研判" span={2}>
            {d.triaged_by_name ? `${d.triaged_by_name}（${d.triaged_at}）` : d.triaged_at}
            {d.triage_note ? `：${d.triage_note}` : ''}
          </Descriptions.Item>
        )}
        {(d.follow_up_name || d.planned_handle_at) && (
          <Descriptions.Item label="跟进安排" span={2}>
            {d.follow_up_name ? `跟进人：${d.follow_up_name}` : ''}
            {d.planned_handle_at
              ? `${d.follow_up_name ? '，' : ''}计划处理：${d.planned_handle_at}` : ''}
          </Descriptions.Item>
        )}
      </Descriptions>
    );
  }

  render() {
    const d = store.detail;
    const editable = EDITABLE_STATUSES.includes(d.status);
    const triageable = d.status === 'recorded' || d.status === 'pending_triage';
    return (
      <Drawer
        title={`运行记录详情 - ${d.record_no || ''}`}
        visible={store.detailVisible}
        width={900}
        onClose={() => store.closeDetail()}
        destroyOnClose
      >
        <Spin spinning={store.isDetailFetching}>
          <div style={{marginBottom: 12}}>
            <AuthEditButton editable={editable}/>
            {d.status === 'recorded' && <AuthPendingTriageButton/>}
            {triageable && <AuthTriageButton/>}
            {editable && <AuthFollowUpButton/>}
            {editable && <AuthResolveButton/>}
            {editable && <AuthImportantButton important={d.importance === 'important'}/>}
            {editable && <AuthConvertButton/>}
            {editable && <AuthCloseButton/>}
          </div>
          <Tabs defaultActiveKey="basic">
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            <TabPane tab="处理进展" key="progress">
              <ProgressTimeline editable={editable}/>
            </TabPane>
            <TabPane tab="重复问题" key="duplicates">
              <DuplicatePanel editable={editable}/>
            </TabPane>
            <TabPane tab="附件" key="attachments">
              <AttachmentTab editable={editable}/>
            </TabPane>
          </Tabs>
          <TriageModal
            visible={store.triageVisible}
            onClose={() => store.triageVisible = false}
          />
        </Spin>
      </Drawer>
    );
  }
}

function AuthEditButton({editable}) {
  if (!editable) return null;
  return (
    <AuthButton
      auth={PERM.RUNTIME_EDIT}
      onClick={() => store.showForm(store.detail)}
    >
      编辑
    </AuthButton>
  );
}

// 提交研判：已记录 → 待研判（结论由研判动作落地）
const AuthPendingTriageButton = observer(function AuthPendingTriageButton() {
  return (
    <span style={{marginLeft: 8}}>
      <Popconfirm
        title="确定提交研判（待研判）吗？"
        onConfirm={() => store.submitPendingTriage()
          .then(() => message.success('已提交研判'))
          .catch(() => {})}
      >
        <AuthButton
          auth={PERM.RUNTIME_TRIAGE}
          loading={store.isActionSubmitting}
        >
          提交研判
        </AuthButton>
      </Popconfirm>
    </span>
  );
});

// 研判：一次动作完成 跟进结论 / 影响判定 / 重要标记 / 转正式故障
const AuthTriageButton = observer(function AuthTriageButton() {
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.RUNTIME_TRIAGE}
        type="primary"
        onClick={() => store.triageVisible = true}
      >
        研判
      </AuthButton>
    </span>
  );
});

const AuthFollowUpButton = observer(function AuthFollowUpButton() {
  const [visible, setVisible] = useState(false);
  const following = store.detail.status === 'following_up';
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.RUNTIME_EDIT}
        loading={store.isActionSubmitting}
        onClick={() => setVisible(true)}
      >
        {following ? '跟进安排' : '标记需要跟进'}
      </AuthButton>
      <FollowUpModal
        visible={visible}
        following={following}
        onClose={() => setVisible(false)}
      />
    </span>
  );
});

// 标记需要跟进 / 更新跟进安排：跟进人与计划处理时间选填（待办视图按此展示筛选）
const FollowUpModal = observer(function FollowUpModal({visible, following, onClose}) {
  const [followUpName, setFollowUpName] = useState('');
  const [plannedAt, setPlannedAt] = useState(null);
  return (
    <Modal
      visible={visible}
      title={following ? '更新跟进安排' : '标记需要跟进（跟进中）'}
      confirmLoading={store.isActionSubmitting}
      onCancel={() => {
        onClose();
        setFollowUpName('');
        setPlannedAt(null);
      }}
      onOk={() => {
        store.markFollowUp({
          follow_up_name: followUpName.trim(),
          planned_handle_at: plannedAt ? plannedAt.format('YYYY-MM-DD HH:mm') : '',
        }).then(() => {
          message.success(following ? '跟进安排已更新' : '已标记为跟进中');
          onClose();
          setFollowUpName('');
          setPlannedAt(null);
        }).catch(() => {});
      }}
    >
      <p>
        {following
          ? '更新跟进人/计划处理时间；记录保持跟进中状态。'
          : '标记为跟进中后进入待办视图，可持续记录处理进展。'}
      </p>
      <Form layout="vertical">
        <Form.Item label="跟进人" style={{marginBottom: 12}}>
          <Input
            value={followUpName}
            onChange={e => setFollowUpName(e.target.value)}
            placeholder="跟进人姓名（选填，可多人顿号分隔）"
          />
        </Form.Item>
        <Form.Item label="计划处理时间" style={{marginBottom: 0}}>
          <DatePicker
            showTime={{format: 'HH:mm'}}
            format="YYYY-MM-DD HH:mm"
            style={{width: '100%'}}
            value={plannedAt}
            onChange={v => setPlannedAt(v)}
            placeholder="选填，超过该时间在待办中标记为超期"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
});

function AuthResolveButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.RUNTIME_RESOLVE} onClick={() => setVisible(true)}>
        标记已处理
      </AuthButton>
      <ResultModal
        visible={visible}
        title="标记已处理"
        action="resolve"
        onClose={() => setVisible(false)}
      />
    </span>
  );
}

// 标记重要：必须填写原因；仅普通 → 重要升级时后端生成履历
function AuthImportantButton({important}) {
  const [visible, setVisible] = useState(false);
  if (important) return null;
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.RUNTIME_IMPORTANT} onClick={() => setVisible(true)}>
        标记重要
      </AuthButton>
      <ImportantModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

function AuthConvertButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.RUNTIME_CONVERT_FAULT}
        type="primary"
        ghost
        onClick={() => setVisible(true)}
      >
        转为故障
      </AuthButton>
      <ConvertModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

function AuthCloseButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.RUNTIME_CLOSE} danger onClick={() => setVisible(true)}>
        关闭
      </AuthButton>
      <ResultModal
        visible={visible}
        title="关闭运行记录"
        action="close"
        onClose={() => setVisible(false)}
      />
    </span>
  );
}

// 标记已处理 / 关闭共用：可选补填处理结果
const ResultModal = observer(function ResultModal({visible, title, action, onClose}) {
  const [result, setResult] = useState('');
  const d = store.detail;
  return (
    <Modal
      visible={visible}
      title={title}
      confirmLoading={store.isActionSubmitting}
      onCancel={() => {
        onClose();
        setResult('');
      }}
      onOk={() => {
        const request = action === 'resolve'
          ? store.resolveRecord({handling_result: result.trim()})
          : store.closeRecord({handling_result: result.trim()});
        request.then(() => {
          message.success(action === 'resolve' ? '已标记为已处理' : '运行记录已关闭');
          onClose();
          setResult('');
        }).catch(() => {});
      }}
    >
      <p>
        {action === 'resolve'
          ? '标记为已处理后仍可继续关闭或重新跟进。'
          : `关闭后运行记录进入终态，不可再编辑或追加进展。当前处理结果：${d.handling_result || '（空）'}`}
      </p>
      <Input.TextArea
        rows={3}
        value={result}
        onChange={e => setResult(e.target.value)}
        placeholder="补填处理结果（选填）"
      />
    </Modal>
  );
});

const ImportantModal = observer(function ImportantModal({visible, onClose}) {
  const [reason, setReason] = useState('');
  return (
    <Modal
      visible={visible}
      title="标记重要"
      confirmLoading={store.isActionSubmitting}
      onCancel={() => {
        onClose();
        setReason('');
      }}
      onOk={() => {
        if (!reason.trim()) {
          message.warning('标记重要时必须填写原因');
          return;
        }
        store.markImportant({importance_reason: reason.trim()})
          .then(() => {
            message.success('已标记为重要');
            onClose();
            setReason('');
          })
          .catch(() => {});
      }}
    >
      <p>重要运行记录会进入系统履历；从普通升级为重要时，履历从标记时刻开始记录。</p>
      <Input.TextArea
        rows={3}
        value={reason}
        onChange={e => setReason(e.target.value)}
        placeholder="请填写标记为重要的原因（必填）"
      />
    </Modal>
  );
});

// 转为故障：带入系统/发生时间/标题/描述等初始信息，事务中创建正式故障单；
// 同一运行记录重复转换由后端拒绝（已转故障或目标故障仍有效时）
const ConvertModal = observer(function ConvertModal({visible, onClose}) {
  const d = store.detail;
  return (
    <Modal
      visible={visible}
      title="转为正式故障"
      confirmLoading={store.isActionSubmitting}
      onCancel={onClose}
      onOk={() => {
        store.convertToFault({})
          .then(() => {
            message.success('已转为正式故障，后续处理请在故障处置中进行');
            onClose();
          })
          .catch(() => {});
      }}
    >
      <p>
        将依据运行记录「{d.record_no}」创建正式故障单：带入所属系统、发生时间、
        标题与情况描述、影响程度等初始信息。
      </p>
      <p>
        转换后本记录状态变为"已转故障"，后续处置、恢复确认与关闭以故障单为准，
        本记录不再重复维护处理状态。
      </p>
    </Modal>
  );
});

// observer 必须包裹：时间线读取 progressRecords/isProgressFetching
const ProgressTimeline = observer(function ProgressTimeline({editable}) {
  return (
    <div>
      <p style={{color: '#999', marginTop: 0}}>
        处理进展按时间追加记录；更正不会覆盖原内容（原内容、修改内容与更正原因一并留痕）。
        已关闭或已转故障的记录不再追加普通处理进展。
      </p>
      {editable && (
        <div style={{marginBottom: 12}}>
          <AddProgressButton/>
        </div>
      )}
      <Spin spinning={store.isProgressFetching}>
        {store.progressRecords.length ? (
          <Timeline style={{marginTop: 8}}>
            {store.progressRecords.map(record => (
              <Timeline.Item key={record.id}>
                <div>
                  <b>{record.handled_at}</b>
                  <span style={{marginLeft: 8}}>处理人：{record.handler_name || '-'}</span>
                  {record.result && <Tag style={{marginLeft: 8}}>{record.result}</Tag>}
                  {record.work_hours !== null && record.work_hours !== undefined && (
                    <Tag style={{marginLeft: 8}}>工时 {record.work_hours}h</Tag>
                  )}
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
          <Empty description="暂无处理进展" image={Empty.PRESENTED_IMAGE_SIMPLE}/>
        )}
      </Spin>
    </div>
  );
});

function AddProgressButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span>
      <AuthButton
        auth={PERM.RUNTIME_EDIT}
        type="primary"
        icon={<PlusOutlined/>}
        onClick={() => setVisible(true)}
      >
        追加处理进展
      </AuthButton>
      <ProgressModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

function CorrectButton({record}) {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.RUNTIME_EDIT}
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

function ProgressModal({visible, record, onClose}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const isCorrect = !!record;
  useEffect(() => {
    if (visible) {
      form.resetFields();
      if (isCorrect) {
        form.setFieldsValue({
          handled_at: record.handled_at ? moment(record.handled_at, 'YYYY-MM-DD HH:mm') : null,
          handler_names: (record.handler_name || '').split('、').filter(Boolean),
          content: record.content,
          result: record.result,
          work_hours: record.work_hours ?? undefined,
        });
      } else {
        // 新增进展：时间默认当前时间；处理人为手动输入姓名（回车确认，可多个），
        // 不预填默认姓名
        form.setFieldsValue({handled_at: moment(), handler_names: []});
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);
  return (
    <Modal
      visible={visible}
      title={isCorrect ? '更正处理进展' : '追加处理进展'}
      confirmLoading={loading}
      onCancel={onClose}
      onOk={() => {
        form.validateFields().then(values => {
          setLoading(true);
          const payload = {
            handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
            // 标签数组以顿号拼接为处理人姓名文本（多人）
            handler_name: (values.handler_names || []).join('、'),
            content: values.content,
            result: values.result || '',
            work_hours: values.work_hours ?? null,
          };
          const request = isCorrect
            ? store.correctProgressRecord(record.id, {...payload,
                correction_reason: values.correction_reason})
            : store.addProgressRecord(payload);
          request.then(() => {
            message.success(isCorrect ? '处理进展已更正' : '处理进展已追加');
            setLoading(false);
            onClose();
          }).catch(() => setLoading(false));
        }).catch(() => {});
      }}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}>
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
          {/* open=false：仅手输姓名（回车/失焦添加），与故障登记人输入一致 */}
          <SelectTagsPlaceholder/>
        </Form.Item>
        <Form.Item
          name="content"
          label="处理内容"
          rules={[{required: true, message: '请填写处理内容'}]}
        >
          <TextArea rows={3} placeholder="如：现场检查情况、已采取的措施、跟进结论等"/>
        </Form.Item>
        <Form.Item name="result" label="处理结果">
          <Input placeholder="选填，如：已恢复 / 继续观察"/>
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

// mode="tags" open=false 的手输姓名输入（与故障登记人输入一致）
function SelectTagsPlaceholder() {
  return (
    <Select
      mode="tags"
      open={false}
      placeholder="输入姓名后回车确认（可多个）"
    />
  );
}

// 附件区：复用公共 AttachmentManager（evidence 附件体系）；
// 删除走运行记录自己的 DELETE 路由（deleteRequest），下载前缀拼接记录级路由；
// 终态记录 readOnly（不可上传/删除，仍可下载）
function AttachmentTab({editable}) {
  const d = store.detail;
  if (!d.id) return null;
  const base = `${API_PREFIX}/runtime-records/${d.id}/attachments/`;
  return (
    <AttachmentManager
      module="equipment_lifecycle"
      objectType="el_runtime_record"
      recordId={d.id}
      listUrl={base}
      uploadUrl={base}
      deleteRequest={att => http.delete(`${base}${att.id}/`)}
      downloadUrlPrefix={base}
      uploadPerm={PERM.RUNTIME_EDIT}
      deletePerm={PERM.RUNTIME_EDIT}
      downloadPerm={PERM.RUNTIME_VIEW}
      readOnly={!editable}
    />
  );
}

export default RecordDetail;

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录详情窗口（2026-10-02 由侧边抽屉改为居中窗口，
 * 与系统档案详情一致）。标题区只保留摘要（2026-10-04 对齐故障详情）：
 * 记录编号 / 当前状态 / 系统影响程度 / 重要程度，需要跟进标识仅在记录
 * 确实需要跟进且状态标签无法表达（非跟进中）时展示；所属系统/安装地点/
 * 发生时间/登记人等完整字段一律放入基本信息区块，不在标题区重复。
 * 基本信息 / 处理进展时间线（追加式、更正留痕）/ 重复问题（相似关联）/
 * 附件（AttachmentManager）。
 * 基本信息分四区块（2026-10-04，区块小标题 + Descriptions，样式对齐故障
 * 详情）：运行概况（只放发生事实：系统/地点/时间/类别/对象/标题/描述）/
 * 研判与处置（初步原因/影响范围/已采取措施/处理结果/研判说明/研判人及
 * 研判时间/跟进安排/重要原因；研判历史只读保留，已处理/已关闭/已转故障
 * 仍展示；尚未研判与已转故障以区块提示行说明实际状态，不渲染成排空"-"；
 * 跟进安排/重要原因/研判人及时间仅在存在数据时展示，重要程度本身只在
 * 标题区展示）/ 关联与登记（关联故障链接或"关联故障登记已撤销"提示 +
 * 登记人/登记时间 + 处理时间/标记重要等生命周期信息；统一"登记人/
 * 登记时间"业务口径，不再重复展示创建人）/ 处理概览（只读紧凑信息条：
 * 条数取进展列表接口 total——store 打开详情时已统一请求该列表，不额外
 * 发请求、不逐条拼装；最近更新与最后记录仅在前端已取得完整进展列表时
 * 展示；"查看全部进展"切换到处理进展页签，完整时间线不复制到本区块）。
 * 顶部动作按状态收敛（2026-10-04，与后端状态机一致，防止绕过研判入口）：
 * - recorded（已记录，合法稳定状态，可长期保留，不作为待办）：编辑、
 *   研判（可选动作；登记与研判同一操作主体，一次提交完成结论，无
 *   "提交研判"中转）、关闭（留痕记录可直接关闭，不要求先研判）；
 * - pending_triage（待研判，历史数据兼容状态）：研判；
 * - following_up（跟进中）：编辑、跟进安排、标记已处理、关闭；
 * - resolved（已处理）：编辑、重新跟进（复用跟进弹窗，转回跟进中）、关闭；
 * - no_follow_up（无需跟进）：重新研判（纠正结论，复用 TriageModal）；
 * - converted_fault / closed：终态无业务按钮（已转故障保留关联故障入口）。
 * - 标记重要 / 转为正式故障只在 TriageModal 研判结论中完成，顶部不再提供
 *   独立入口（旧 store 方法与后端接口暂时保留）；
 * - 所有动作成功后重新获取真实数据；错误提示由 http 拦截器统一弹出，
 *   业务代码不重复提示。
 * 约束：凡在 render 中读取 store observable 的函数组件必须用 observer 包裹。
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Tabs, Descriptions, Tag, Spin, Button, Timeline, Modal, Form,
  Input, InputNumber, DatePicker, Select, message, Empty } from 'antd';
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
  // 页签受控于本地 state（组件随详情开关重新挂载，无需入 store）；
  // 处理概览"查看全部进展"经此直达处理进展页签
  state = {activeTab: 'basic'};

  handleTabChange = (activeTab) => this.setState({activeTab});

  // 区块标题：四区块与处理概览共用（与故障详情同款内联样式）
  renderSectionTitle(text, style) {
    return <div style={{fontWeight: 600, marginBottom: 8, ...style}}>{text}</div>;
  }

  // 基本信息（2026-10-04 重组为四区块）：运行概况 / 研判与处置 /
  // 关联与登记 / 处理概览。编号、状态、影响程度、重要程度只在标题区
  // 展示一次，区块内不再重复。
  renderBasic() {
    return (
      <div>
        {this.renderSectionTitle('运行概况')}
        {this.renderOverviewSection()}
        {this.renderTriageSection()}
        {this.renderRegistrySection()}
        {this.renderHandlingOverview()}
      </div>
    );
  }

  // 一、运行概况：只展示记录发生时的事实（按发生顺序），不放研判结论、
  // 跟进安排或处理结果；标题保持"标题"字样，不与故障模块"故障现象"混用
  renderOverviewSection() {
    const d = store.detail;
    return (
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="所属系统">{d.system_name}</Descriptions.Item>
        <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="发生时间">{d.occurred_at}</Descriptions.Item>
        <Descriptions.Item label="异常类别">
          {d.category ? (RUNTIME_CATEGORY_TEXT[d.category] || d.category) : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="具体对象/型号" span={2}>
          {[d.object_name, d.object_model].filter(Boolean).join(' / ') || '-'}
        </Descriptions.Item>
        <Descriptions.Item label="标题" span={2}>{d.title}</Descriptions.Item>
        <Descriptions.Item label="情况描述" span={2}>{d.description}</Descriptions.Item>
      </Descriptions>
    );
  }

  // 二、研判与处置：集中展示研判与处理字段；研判数据保留历史只读展示
  // （已处理/已关闭/已转故障仍可见）。尚未研判（已记录/待研判且无研判
  // 数据）与已转故障以提示行说明实际状态（对齐故障详情"尚未完成恢复
  // 确认"的提示方式）；跟进安排/重要原因/研判人及时间仅在存在数据时
  // 渲染，不为空值创建整行"-"。
  renderTriageSection() {
    const d = store.detail;
    const hasTriage = Boolean(d.triaged_at || d.triaged_by_name || d.triage_note);
    const notTriaged = !hasTriage &&
      (d.status === 'recorded' || d.status === 'pending_triage');
    const hasFollowUp = Boolean(d.follow_up_name || d.planned_handle_at);
    const showImportanceReason = d.importance === 'important' || !!d.importance_reason;
    let hint = null;
    if (notTriaged) {
      hint = '尚未完成研判';
    } else if (d.status === 'converted_fault') {
      hint = '该记录已转正式故障，后续处置以关联故障为准';
    }
    return (
      <React.Fragment>
        {this.renderSectionTitle('研判与处置', {marginTop: 16})}
        {hint && (
          <div style={{color: 'rgba(0, 0, 0, 0.45)', marginBottom: 8}}>{hint}</div>
        )}
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="初步原因" span={2}>{d.initial_reason || '-'}</Descriptions.Item>
          <Descriptions.Item label="影响范围" span={2}>{d.impact_scope || '-'}</Descriptions.Item>
          <Descriptions.Item label="已采取措施" span={2}>{d.measures_taken || '-'}</Descriptions.Item>
          <Descriptions.Item label="处理结果" span={2}>{d.handling_result || '-'}</Descriptions.Item>
          {hasTriage && (
            <React.Fragment>
              <Descriptions.Item label="研判说明" span={2}>{d.triage_note || '-'}</Descriptions.Item>
              <Descriptions.Item label="研判人及研判时间" span={2}>
                {d.triaged_by_name
                  ? `${d.triaged_by_name}（${d.triaged_at || ''}）`
                  : (d.triaged_at || '-')}
              </Descriptions.Item>
            </React.Fragment>
          )}
          {hasFollowUp && (
            <Descriptions.Item label="跟进安排" span={2}>
              {d.follow_up_name ? `跟进人：${d.follow_up_name}` : ''}
              {d.planned_handle_at
                ? `${d.follow_up_name ? '，' : ''}计划处理：${d.planned_handle_at}` : ''}
            </Descriptions.Item>
          )}
          {showImportanceReason && (
            <Descriptions.Item label="重要原因" span={2}>
              {d.importance_reason || '-'}
            </Descriptions.Item>
          )}
        </Descriptions>
      </React.Fragment>
    );
  }

  // 三、关联与登记：记录来源与生命周期追溯。统一"登记人/登记时间"业务
  // 口径（登记时间即创建时间，创建人不再重复展示）；已转故障显示可点击
  // 关联故障（沿用现有跳转），关联故障已撤销时明确提示，无关联显示"-"、
  // 不渲染空按钮；处理时间/标记重要属于生命周期状态变更信息，仅在存在
  // 数据时展示。
  renderRegistrySection() {
    const d = store.detail;
    return (
      <React.Fragment>
        {this.renderSectionTitle('关联与登记', {marginTop: 16})}
        <Descriptions bordered size="small" column={2}>
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
                {d.converted_fault_no || '查看关联故障'}
              </Button>
            ) : (d.status === 'converted_fault' ? '关联故障登记已撤销' : '-')}
          </Descriptions.Item>
          <Descriptions.Item label="登记人">{d.registrar_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="登记时间">{d.created_at}</Descriptions.Item>
          {d.resolved_at && (
            <Descriptions.Item label="处理时间">{d.resolved_at}</Descriptions.Item>
          )}
          {d.importance_marked_at && (
            <Descriptions.Item label="标记重要">
              {d.importance_marked_by_name
                ? `${d.importance_marked_by_name}（${d.importance_marked_at}）`
                : d.importance_marked_at}
            </Descriptions.Item>
          )}
        </Descriptions>
      </React.Fragment>
    );
  }

  // 四、处理概览（2026-10-04）：基本信息底部只读紧凑信息条（非边框表格，
  // 与故障详情一致）。条数取进展列表接口 total（store.showDetail 打开详情
  // 时已统一请求进展列表，不额外发请求）；进展按处理时间正序返回，前端
  // 已取得完整列表（条数 ≤ 单页容量）时展示最近更新与最后记录摘要，超出
  // 单页容量时不展示，避免以早期记录冒充最新；完整时间线仍在处理进展页签。
  renderHandlingOverview() {
    const count = store.progressTotal ?? store.progressRecords.length;
    const complete = count > 0 && store.progressRecords.length >= count;
    const latest = complete
      ? store.progressRecords[store.progressRecords.length - 1] : null;
    const goToProgress = () => this.setState({activeTab: 'progress'});
    return (
      <div style={{marginTop: 16}}>
        {this.renderSectionTitle('处理概览')}
        {count > 0 ? (
          <div style={{fontSize: 13}}>
            <a onClick={goToProgress}>处理进展 {count} 条</a>
            {latest && (
              <React.Fragment>
                <span style={{marginLeft: 16}}>最近更新：{latest.handled_at}</span>
                <span style={{marginLeft: 16}}>最后记录：{latest.content}</span>
              </React.Fragment>
            )}
            <Button type="link" style={{padding: 0, marginLeft: 16}} onClick={goToProgress}>
              查看全部进展
            </Button>
          </div>
        ) : (
          <div style={{color: 'rgba(0, 0, 0, 0.45)'}}>
            {store.isProgressFetching ? '处理进展加载中…' : '暂无处理进展'}
          </div>
        )}
      </div>
    );
  }

  renderTitle() {
    const d = store.detail;
    // 标题区只保留摘要（2026-10-04 对齐故障详情）：编号/当前状态/系统影响
    // 程度/重要程度；"需要跟进"仅在记录确实需要跟进且状态标签无法表达时
    // 展示（跟进中状态本身已表达该含义，不重复标）。
    return (
      <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap'}}>
        <span
          title={d.record_no}
          style={{
            fontSize: 16, fontWeight: 600, marginRight: 8, maxWidth: 420,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {d.record_no || '运行记录详情'}
        </span>
        <Tag color={RUNTIME_STATUS_COLOR[d.status]}>{RUNTIME_STATUS_TEXT[d.status]}</Tag>
        {d.needs_follow_up && d.status !== 'following_up' && (
          <Tag color="blue">需要跟进</Tag>
        )}
        {d.affects_system_operation ? (
          <Tag color={RUNTIME_IMPACT_COLOR[d.impact_status]}>
            {RUNTIME_IMPACT_TEXT[d.impact_status] || d.impact_status}
          </Tag>
        ) : (
          <Tag>不影响运行</Tag>
        )}
        <Tag color={d.importance === 'important' ? 'red' : 'default'}>
          {d.importance === 'important' ? '重要' : '普通'}
        </Tag>
      </div>
    );
  }

  render() {
    const d = store.detail;
    const editable = EDITABLE_STATUSES.includes(d.status);
    const status = d.status;
    return (
      <Modal
        title={this.renderTitle()}
        visible={store.detailVisible}
        width={1100}
        centered
        destroyOnClose
        onCancel={() => store.closeDetail()}
        bodyStyle={{
          height: 'calc(100vh - 180px)',
          minHeight: 460,
          overflow: 'auto',
          paddingTop: 12,
        }}
        footer={<Button onClick={() => store.closeDetail()}>关 闭</Button>}
      >
        <Spin spinning={store.isDetailFetching}>
          <div style={{marginBottom: 12}}>
            {editable && <AuthEditButton/>}
            {(status === 'recorded' || status === 'pending_triage') &&
              <AuthTriageButton/>}
            {(status === 'following_up' || status === 'resolved') &&
              <AuthFollowUpButton/>}
            {status === 'following_up' && <AuthResolveButton/>}
            {/* 已记录可直接关闭（不要求先研判），与后端状态机一致 */}
            {(status === 'recorded' || status === 'following_up' ||
              status === 'resolved') &&
              <AuthCloseButton/>}
            {status === 'no_follow_up' && <AuthRetriageButton/>}
          </div>
          {/* 页签受控（本地 state）：处理概览"查看全部进展"可直达处理进展
              页签；组件随详情开关重新挂载，每次打开回到基本信息页签 */}
          <Tabs activeKey={this.state.activeTab} onChange={this.handleTabChange}>
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
      </Modal>
    );
  }
}

function AuthEditButton() {
  return (
    <AuthButton
      auth={PERM.RUNTIME_EDIT}
      onClick={() => store.showForm(store.detail)}
    >
      编辑
    </AuthButton>
  );
}

// 研判：一次动作完成 跟进结论 / 影响判定 / 重要标记 / 转正式故障
// （已记录/待研判为同一操作主体的主动作，无需"提交研判"中转）
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

// 重新研判：无需跟进结论纠偏（复用研判弹窗，可改判跟进中/转正式故障/维持结论）
const AuthRetriageButton = observer(function AuthRetriageButton() {
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.RUNTIME_TRIAGE}
        onClick={() => store.triageVisible = true}
      >
        重新研判
      </AuthButton>
    </span>
  );
});

// 跟进中 → 跟进安排（更新跟进人/计划时间）；已处理 → 重新跟进（转回跟进中）
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
        {following ? '跟进安排' : '重新跟进'}
      </AuthButton>
      <FollowUpModal
        visible={visible}
        following={following}
        onClose={() => setVisible(false)}
      />
    </span>
  );
});

// 跟进安排 / 重新跟进：跟进人与计划处理时间选填（待办视图按此展示筛选）
const FollowUpModal = observer(function FollowUpModal({visible, following, onClose}) {
  const [followUpName, setFollowUpName] = useState('');
  const [plannedAt, setPlannedAt] = useState(null);
  return (
    <Modal
      visible={visible}
      title={following ? '更新跟进安排' : '重新跟进'}
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
          message.success(following ? '跟进安排已更新' : '已重新进入跟进中');
          onClose();
          setFollowUpName('');
          setPlannedAt(null);
        }).catch(() => {});
      }}
    >
      <p>
        {following
          ? '更新跟进人/计划处理时间；记录保持跟进中状态。'
          : '重新进入跟进中后进入待办视图，可持续记录处理进展。'}
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

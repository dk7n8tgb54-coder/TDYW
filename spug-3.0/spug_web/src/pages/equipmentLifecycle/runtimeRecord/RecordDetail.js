/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行异常记录详情窗口（2026-10-02 由侧边抽屉改为居中窗口，
 * 与系统档案详情一致）。标题区只保留摘要（2026-10-04 对齐故障详情）：
 * 记录编号 / 当前状态，需要跟进标识仅在记录确实需要跟进且状态标签无法表达
 * （非跟进中）时展示；系统影响程度/重要程度标签已随字段删除移除
 * （2026-10-06）；所属系统/安装地点/发生时间/登记人等完整字段一律放入
 * 基本信息区块，不在标题区重复。
 * 基本信息 / 处理进展时间线（追加式、更正留痕）/ 附件（AttachmentManager）。
 * 重复问题（相似关联）页签已于 2026-10-05 下线：相似记录查询/双向关联/
 * 取消关联/重复发生标记入口整体移除（"相似"无内容相似度依据、时间窗口
 * 规则无业务依据，且核心流程不依赖重复分析）；后端旧接口、模型字段与
 * is_repeated 已随 2026-10-06 重复功能退役（迁移 0008）整体删除。
 * 基本信息四区块（2026-10-04 信息分层收敛，区块小标题 + Descriptions，样式
 * 对齐故障详情）：运行概况（只放发生事实：系统/地点/时间/类别/标题/描述）/
 * 研判结论（历史数据只读展示：研判说明/研判人及研判时间；第四版
 * （2026-10-05）起研判不再是必经步骤，新记录不产生研判数据，本区块仅在
 * 存在历史研判数据时渲染；重要原因展示已随标记重要删除移除 2026-10-06）/
 * 关联与登记（关联故障链接或"关联故障登记已撤销"提示 + 登记人/登记时间 +
 * 处理时间等生命周期信息；统一"登记人/登记时间"业务口径，不再重复展示
 * 创建人）/ 处理概览（只读紧凑信息条：条数取进展列表接口 total——store 打开
 * 详情时已统一请求该列表，不额外发请求、不逐条拼装；最近更新与最后记录仅在
 * 前端已取得完整进展列表时展示；"查看全部进展"切换到处理进展页签，
 * 完整时间线不复制到本区块）。
 * 已采取措施/处理结果等历史字段已从录入与研判中退役：新数据不再写入，
 * 详情页不再展示（2026-10-06 "历史记录"只读区块随本次清理移除；后端
 * 字段与数据库列保留，历史值不删）。
 * 顶部动作按状态收敛（2026-10-05 第四版：研判不再是必经步骤，TriageModal
 * 整体删除，研判转为故障/跟进结论/影响判定/重要标记不再作为统一弹窗入口）。
 * 用户可见状态只有 已记录/跟进中/已完成/已转故障（历史旧状态已由后端
 * 迁移 0007 归一，前端不再保留别名）：
 * - recorded（已记录，登记完成的合法稳定状态，可长期保留，不作为待办）：
 *   编辑、开始跟进（打开处理进展录入界面，保存首条跟进记录后进入跟进中）、
 *   转为正式故障（独立动作，不依赖研判）；
 * - following_up（跟进中）：新增跟进记录（打开处理进展录入界面）、修改
 *   跟进计划（只更新跟进人/计划处理时间，不产生处理进展）、完成跟进、
 *   转为正式故障；
 * - completed（已完成）：重新跟进；
 * - converted_fault（已转故障）：查看关联故障（后续处置以故障模块为准），
 *   终态无其他业务按钮。
 * - 已删除入口：提交研判/研判/重新研判/无需跟进/关闭运行异常记录/研判中的
 *   跟进安排/影响判定/重要标记/转故障入口/标记重要（2026-10-06 字段删除）；
 * - 处理进展页签 = 统一处理工作区：当前跟进计划（仅跟进中可改）→ 新增
 *   处理进展 → 历史处理进展时间线（追加式）；完成跟进为纯确认动作，不再
 *   补填处理结果（最终说明应作为最后一条处理进展保存，不写入全局结果字段）；
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
import { API_PREFIX, PERM, RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR,
  RUNTIME_CATEGORY_TEXT } from '../constants';

const {TextArea} = Input;
const {TabPane} = Tabs;

// 页签内可编辑（追加进展/更正/附件上传）的状态：已完成仍可补录；
// 已转故障为终态。
const EDITABLE_STATUSES = ['recorded', 'following_up', 'completed'];
// 已记录：新建成功即已记录（可长期保留，不作为待办），享有同一组顶部动作
const RECORDED_LIKE_STATUSES = ['recorded'];
const WORK_HOURS_RULE = [{
  validator: (_, value) => (
    value === undefined || value === null || (typeof value === 'number' && value >= 0)
      ? Promise.resolve() : Promise.reject(new Error('工时不能为负数'))),
}];

// 区块标题（基本信息四区块与处理进展工作区共用，与故障详情同款内联样式）
function sectionTitle(text, style) {
  return <div style={{fontWeight: 600, marginBottom: 8, ...style}}>{text}</div>;
}

@observer
class RecordDetail extends React.Component {
  // 页签受控于本地 state（组件随详情开关重新挂载，无需入 store）；
  // 处理概览"查看全部进展"经此直达处理进展页签
  state = {activeTab: 'basic'};

  handleTabChange = (activeTab) => this.setState({activeTab});

  // 区块标题：四区块与处理概览共用（与故障详情同款内联样式）
  renderSectionTitle(text, style) {
    return sectionTitle(text, style);
  }

  // 基本信息（2026-10-04 信息分层收敛）：运行概况 / 研判结论 /
  // 关联与登记 / 处理概览。编号、状态只在标题区展示一次，区块内不再重复。
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
  // 跟进安排或处理结果；标题保持"标题"字样，不与故障模块"故障现象"混用；
  // 具体对象/型号行已随字段删除移除（2026-10-06）
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
        <Descriptions.Item label="标题" span={2}>{d.title}</Descriptions.Item>
        <Descriptions.Item label="情况描述" span={2}>{d.description}</Descriptions.Item>
      </Descriptions>
    );
  }

  // 二、研判结论（2026-10-05 第四版起仅作历史数据只读展示）：研判不再是
  // 必经步骤，新记录不产生研判数据，本区块仅在存在历史研判数据时渲染；
  // 说明只记录判断依据与结论，处理过程一律在处理进展时间线；
  // 已转故障以提示行说明实际状态（对齐故障详情的提示方式），不为空值
  // 创建整行"-"。
  renderTriageSection() {
    const d = store.detail;
    const hasTriage = Boolean(d.triaged_at || d.triaged_by_name || d.triage_note);
    const converted = d.status === 'converted_fault';
    if (!hasTriage && !converted) {
      return null;
    }
    let hint = null;
    if (converted) {
      hint = '该记录已转正式故障，后续处置以关联故障为准';
    }
    return (
      <React.Fragment>
        {this.renderSectionTitle('研判结论', {marginTop: 16})}
        {hint && (
          <div style={{color: 'rgba(0, 0, 0, 0.45)', marginBottom: 8}}>{hint}</div>
        )}
        {hasTriage && (
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="研判说明" span={2}>{d.triage_note || '-'}</Descriptions.Item>
            <Descriptions.Item label="研判人及研判时间" span={2}>
              {d.triaged_by_name
                ? `${d.triaged_by_name}（${d.triaged_at || ''}）`
                : (d.triaged_at || '-')}
            </Descriptions.Item>
          </Descriptions>
        )}
      </React.Fragment>
    );
  }

  // 三、关联与登记：记录来源与生命周期追溯。统一"登记人/登记时间"业务
  // 口径（登记时间即创建时间，创建人不再重复展示）；已转故障显示可点击
  // 关联故障（沿用现有跳转），关联故障已撤销时明确提示，无关联显示"-"、
  // 不渲染空按钮；处理时间属于生命周期状态变更信息，仅在存在数据时展示
  // （标记重要行已随字段删除移除，2026-10-06）。
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
    // 标题区只保留摘要（2026-10-04 对齐故障详情）：编号/当前状态；
    // "需要跟进"仅在记录确实需要跟进且状态标签无法表达时展示（跟进中状态
    // 本身已表达该含义，不重复标）；系统影响程度/重要程度标签已随字段
    // 删除移除（2026-10-06）。
    return (
      <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap'}}>
        <span
          title={d.record_no}
          style={{
            fontSize: 16, fontWeight: 600, marginRight: 8, maxWidth: 420,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {d.record_no || '运行异常记录详情'}
        </span>
        <Tag color={RUNTIME_STATUS_COLOR[d.status]}>{RUNTIME_STATUS_TEXT[d.status]}</Tag>
        {d.needs_follow_up && d.status !== 'following_up' && (
          <Tag color="blue">需要跟进</Tag>
        )}
      </div>
    );
  }

  render() {
    const d = store.detail;
    const editable = EDITABLE_STATUSES.includes(d.status);
    const status = d.status;
    const recordedLike = RECORDED_LIKE_STATUSES.includes(status);
    const following = status === 'following_up';
    const doneLike = status === 'completed';
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
        /* 底部按钮只关闭详情窗口，不改业务状态；业务动作（完成跟进/转故障）
           是顶部按钮，两者语义不同 */
        footer={<Button onClick={() => store.closeDetail()}>关 闭</Button>}
      >
        <Spin spinning={store.isDetailFetching}>
          <div style={{marginBottom: 12}}>
            {recordedLike && <AuthEditButton/>}
            {recordedLike && (
              <AuthPrimaryActionButton
                auth={PERM.RUNTIME_EDIT}
                text="开始跟进"
                onClick={() => this.setState({activeTab: 'progress', addProgressVisible: true})}
              />
            )}
            {following && (
              <AuthPrimaryActionButton
                auth={PERM.RUNTIME_EDIT}
                text="新增跟进记录"
                onClick={() => this.setState({activeTab: 'progress', addProgressVisible: true})}
              />
            )}
            {following && <AuthEditPlanButton/>}
            {following && <AuthCompleteButton/>}
            {(recordedLike || following) && <AuthConvertButton/>}
            {doneLike && <AuthFollowUpButton/>}
            {status === 'converted_fault' && d.converted_fault && <AuthViewFaultButton/>}
          </div>
          {/* 页签受控（本地 state）：处理概览"查看全部进展"可直达处理进展
              页签；组件随详情开关重新挂载，每次打开回到基本信息页签 */}
          <Tabs activeKey={this.state.activeTab} onChange={this.handleTabChange}>
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            <TabPane tab="处理进展" key="progress">
              <ProgressTimeline
                editable={editable}
                onAdd={() => this.setState({addProgressVisible: true})}/>
            </TabPane>
            <TabPane tab="附件" key="attachments">
              <AttachmentTab editable={editable}/>
            </TabPane>
          </Tabs>
          {/* 新增处理进展录入弹窗（现有处理进展界面）提升到详情层：
              顶部"开始跟进/新增跟进记录"与处理进展页签共用同一入口；
              已记录保存首条跟进记录后由后端流转为跟进中 */}
          <ProgressModal
            visible={this.state.addProgressVisible}
            onClose={() => this.setState({addProgressVisible: false})}/>
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

// 顶部主行动按钮（开始跟进/新增跟进记录等）统一外壳
function AuthPrimaryActionButton({auth, text, onClick}) {
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={auth} type="primary" onClick={onClick}>{text}</AuthButton>
    </span>
  );
}

// 修改当前跟进计划（仅跟进中顶部入口）：复用跟进计划弹窗，回填当前值，
// 只修改 跟进人/计划处理时间 两个计划字段，不写处理结果、不产生处理进展
function AuthEditPlanButton() {
  const [visible, setVisible] = useState(false);
  const d = store.detail;
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.RUNTIME_EDIT} onClick={() => setVisible(true)}>
        修改跟进计划
      </AuthButton>
      <FollowUpModal
        visible={visible}
        initial={{
          follow_up_name: d.follow_up_name || '',
          planned_handle_at: d.planned_handle_at || null,
        }}
        onClose={() => setVisible(false)}
      />
    </span>
  );
}

// 已完成（含历史已处理）→ 重新跟进（转回跟进中，进入待办视图）
const AuthFollowUpButton = observer(function AuthFollowUpButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.RUNTIME_EDIT}
        loading={store.isActionSubmitting}
        onClick={() => setVisible(true)}
      >
        重新跟进
      </AuthButton>
      <FollowUpModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
});

// 重新跟进 / 修改当前跟进计划：只修改 跟进人/计划处理时间 两个当前计划
// 字段，不写处理结果、不产生处理进展；修改计划时以 initial 回填当前值
const FollowUpModal = observer(function FollowUpModal({visible, initial, onClose}) {
  const [followUpName, setFollowUpName] = useState('');
  const [plannedAt, setPlannedAt] = useState(null);
  const editing = !!initial;
  useEffect(() => {
    if (visible) {
      setFollowUpName((initial && initial.follow_up_name) || '');
      setPlannedAt(initial && initial.planned_handle_at
        ? moment(initial.planned_handle_at, 'YYYY-MM-DD HH:mm') : null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);
  return (
    <Modal
      visible={visible}
      title={editing ? '修改跟进计划' : '重新跟进'}
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
          message.success(editing ? '跟进计划已更新' : '已重新进入跟进中');
          onClose();
          setFollowUpName('');
          setPlannedAt(null);
        }).catch(() => {});
      }}
    >
      <p>
        {editing
          ? '更新当前跟进人/计划处理时间；记录保持跟进中，修改计划不产生处理进展。'
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

// 完成跟进：跟进中 → 已完成（纯确认动作，完成后可直接重新跟进，不要求
// 再次关闭）
function AuthCompleteButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.RUNTIME_RESOLVE} onClick={() => setVisible(true)}>
        完成跟进
      </AuthButton>
      <CompleteModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

// 完成跟进确认：不再补填处理结果——处理过程/最终说明的唯一入口是处理
// 进展时间线（最终说明应作为最后一条处理进展保存，不写入全局结果字段）
const CompleteModal = observer(function CompleteModal({visible, onClose}) {
  return (
    <Modal
      visible={visible}
      title="完成跟进"
      confirmLoading={store.isActionSubmitting}
      onCancel={onClose}
      onOk={() => {
        store.completeFollowUp()
          .then(() => {
            message.success('已完成跟进');
            onClose();
          }).catch(() => {});
      }}
    >
      <p>完成后记录进入"已完成"，可随时重新跟进，无需关闭。</p>
      <p style={{color: 'rgba(0, 0, 0, 0.45)', marginBottom: 0}}>
        如需留档最终说明，请先在处理进展中追加一条收尾进展。
      </p>
    </Modal>
  );
});

// 转为正式故障（跟进中顶部入口）：创建并关联正式故障，后续处置以故障模块为准
function AuthConvertButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.RUNTIME_CONVERT_FAULT} onClick={() => setVisible(true)}>
        转为正式故障
      </AuthButton>
      <ConvertFaultModal visible={visible} onClose={() => setVisible(false)}/>
    </span>
  );
}

// 转正式故障确认：现象缺省由后端带入运行异常记录标题与描述；仅当该记录曾转
// 故障后被撤销时才需要填写重新处置原因
const ConvertFaultModal = observer(function ConvertFaultModal({visible, onClose}) {
  const [phenomenon, setPhenomenon] = useState('');
  const [reDisposeReason, setReDisposeReason] = useState('');
  return (
    <Modal
      visible={visible}
      title="转为正式故障"
      confirmLoading={store.isActionSubmitting}
      onCancel={() => {
        onClose();
        setPhenomenon('');
        setReDisposeReason('');
      }}
      onOk={() => {
        store.convertToFault({
          phenomenon: phenomenon.trim(),
          re_dispose_reason: reDisposeReason.trim(),
        }).then(() => {
          message.success('已转为正式故障，后续处置以故障模块为准');
          onClose();
          setPhenomenon('');
          setReDisposeReason('');
        }).catch(() => {});
      }}
    >
      <p>
        将创建一条正式故障并关联本运行异常记录，记录进入"已转故障"；
        后续处理/恢复确认/关闭全部在故障模块完成。
      </p>
      <Form layout="vertical">
        <Form.Item label="故障现象" style={{marginBottom: 12}}>
          <TextArea
            rows={3}
            value={phenomenon}
            onChange={e => setPhenomenon(e.target.value)}
            placeholder="选填，缺省带入运行异常记录标题与情况描述"
          />
        </Form.Item>
        <Form.Item label="重新处置原因" style={{marginBottom: 0}}>
          <Input
            value={reDisposeReason}
            onChange={e => setReDisposeReason(e.target.value)}
            placeholder="仅当本记录曾转故障后又被撤销时必填"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
});

// 查看关联故障（已转故障唯一入口）：跳转故障详情，后续处置以故障模块为准
const AuthViewFaultButton = observer(function AuthViewFaultButton() {
  const d = store.detail;
  return (
    <AuthButton
      auth={PERM.RUNTIME_VIEW}
      type="primary"
      onClick={() => {
        store.closeDetail();
        history.push(`/el/faults?detail=${d.converted_fault}`);
      }}
    >
      查看关联故障
    </AuthButton>
  );
});

// observer 必须包裹：时间线读取 progressRecords/isProgressFetching。
// 统一处理工作区（2026-10-04 信息分层收敛）：当前跟进计划（仅跟进中，
// 计划修改走顶部"修改跟进计划"）→ 新增处理进展（追加式，处理过程的唯一
// 记录入口，已记录保存首条跟进记录后进入跟进中）→ 历史处理进展时间线；
// 终态（已转故障/已关闭）只读查看时间线。
const ProgressTimeline = observer(function ProgressTimeline({editable, onAdd}) {
  const d = store.detail;
  const following = d.status === 'following_up';
  const doneLike = d.status === 'completed';
  const hasPlan = Boolean(d.follow_up_name || d.planned_handle_at);
  return (
    <div>
      {editable && (
        <React.Fragment>
          {sectionTitle('当前跟进计划')}
          <div style={{marginBottom: 12}}>
            {following ? (
              hasPlan ? (
                <span>
                  跟进人：{d.follow_up_name || '-'}
                  <span style={{marginLeft: 16}}>计划处理：{d.planned_handle_at || '-'}</span>
                </span>
              ) : '暂无跟进计划（可在顶部"修改跟进计划"中填写）'
            ) : (
              <span style={{color: 'rgba(0, 0, 0, 0.45)'}}>
                {doneLike
                  ? '跟进已完成；如需继续处理，请使用顶部"重新跟进"。'
                  : '尚未开始跟进；点击顶部"开始跟进"并保存第一条跟进记录后进入跟进中。'}
              </span>
            )}
          </div>
          {sectionTitle('新增处理进展')}
          <div style={{marginBottom: 12}}>
            <AddProgressButton onAdd={onAdd}/>
          </div>
        </React.Fragment>
      )}
      {sectionTitle('历史处理进展时间线')}
      <p style={{color: '#999', marginTop: 0}}>
        处理进展是实际处理过程的唯一记录入口，按时间追加；更正不会覆盖原内容（原内容、修改内容与更正原因一并留痕）。
        已关闭或已转故障的记录不再追加普通处理进展。
      </p>
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

function AddProgressButton({label, onAdd}) {
  return (
    <AuthButton
      auth={PERM.RUNTIME_EDIT}
      type="primary"
      icon={<PlusOutlined/>}
      onClick={onAdd}
    >
      {label || '追加处理进展'}
    </AuthButton>
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
  // initialValues + destroyOnClose（与故障确认恢复弹窗同一模式）：每次打开
  // 重新挂载表单取最新值，避免 Modal 惰性挂载下 setFieldsValue 与字段注册
  // 时序错位导致受控失效
  const initialValues = isCorrect ? {
    handled_at: record.handled_at ? moment(record.handled_at, 'YYYY-MM-DD HH:mm') : null,
    handler_names: (record.handler_name || '').split('、').filter(Boolean),
    content: record.content,
    result: record.result,
    work_hours: record.work_hours ?? undefined,
  } : {
    // 新增进展：时间默认当前时间；处理人为手动输入姓名（回车确认，可多个），
    // 不预填默认姓名
    handled_at: moment(),
    handler_names: [],
  };
  return (
    <Modal
      visible={visible}
      title={isCorrect ? '更正处理进展' : '追加处理进展'}
      destroyOnClose
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
          {/* open=false：仅手输姓名（回车/失焦添加），与故障登记人输入一致。
              必须内联（不得包装转发）：Form.Item 以 cloneElement 注入
              value/onChange，包装组件若不透传会使表单收不到变更 */}
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

// 附件区：复用公共 AttachmentManager（evidence 附件体系）；
// 删除走运行异常记录自己的 DELETE 路由（deleteRequest），下载前缀拼接记录级路由；
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

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行记录详情窗口（2026-10-02 由侧边抽屉改为居中窗口，
 * 与系统档案详情一致；2026-10-07 模块更名"运行记录"并扩展 record_type）。
 * 标题区只保留摘要（2026-10-04 对齐故障详情）：记录编号 / 记录类型 /
 * 当前状态，需要跟进标识仅在记录确实需要跟进且状态标签无法表达
 * （非跟进中）时展示；系统影响程度/重要程度标签已随字段删除移除
 * （2026-10-06）；所属系统/安装地点/发生时间/登记人等完整字段一律放入
 * 基本信息区块，不在标题区重复。
 * 基本信息 / 处理进展时间线（追加式、更正留痕）/ 附件（AttachmentManager）。
 * 重复问题（相似关联）页签已于 2026-10-05 下线：相似记录查询/双向关联/
 * 取消关联/重复发生标记入口整体移除（"相似"无内容相似度依据、时间窗口
 * 规则无业务依据，且核心流程不依赖重复分析）；后端旧接口、模型字段与
 * is_repeated 已随 2026-10-06 重复功能退役（迁移 0008）整体删除。
 * 基本信息三区块（2026-10-04 信息分层收敛，区块小标题 + Descriptions，样式
 * 对齐故障详情）：运行概况（只放发生事实：系统/地点/时间/类别/标题/描述）/
 * 关联与登记（已转故障处置去向提示 + 关联故障链接或"关联故障登记已撤销"
 * 提示 + 登记人/登记时间 + 处理时间等生命周期信息；
 * 统一"登记人/登记时间"业务口径，不再重复展示创建人；"记录关联日常运行"
 * 功能已于 2026-10-07 按用户决策整体移除）/ 处理概览（只读
 * 紧凑信息条：条数取进展列表接口 total——store 打开详情时已统一请求该
 * 列表，不额外发请求、不逐条拼装；最近更新与最后记录仅在前端已取得完整
 * 进展列表时展示；"查看全部进展"切换到处理进展页签，完整时间线不复制到
 * 本区块）。
 * 记录类型差异（2026-10-07 record_type）：
 * - routine 日常运行：页面状态恒为"已记录"，只保留 查看/编辑/上传和管理
 *   附件/删除，不显示也不提供 研判/跟进/完成跟进/转正式故障 等异常操作
 *   （后端对异常专属接口独立拒绝）；作业是否完成以"作业内容/操作结果或
 *   检查结果"表达，无处理进展与处理概览；关联与登记展示关联的异常事件
 *   记录列表（可跳转）；
 * - abnormal 异常事件：沿用原有异常字段与全部流程（下述历史演进不变）。
 * 研判结论区块与研判快照字段（研判说明/研判人及研判时间）已彻底删除
 * （2026-10-07 迁移 0010：研判不再是必经步骤，新记录不产生研判数据，
 * 存量历史值随列删除不再保留）；重要原因展示已随标记重要删除移除 2026-10-06。
 * 已采取措施/处理结果等历史字段已从录入与研判中退役：异常事件新数据不再
 * 写入，详情页不再展示（该两字段现由日常运行记录承载作业内容/操作结果，
 * 2026-10-07；后端字段与数据库列保留，异常事件历史值不删）。
 * 异常事件顶部动作按状态收敛（2026-10-05 第四版：研判不再是必经步骤，
 * TriageModal 整体删除，研判转为故障/跟进结论/影响判定/重要标记不再作为
 * 统一弹窗入口）。用户可见状态只有 已记录/跟进中/已完成/已转故障（历史
 * 旧状态已由后端迁移 0007 归一，前端不再保留别名）：
 * - recorded（已记录，登记完成的合法稳定状态，可长期保留，不作为待办）：
 *   编辑、开始跟进（跳到处理进展工作区，保存首条跟进记录后进入跟进中）、
 *   转为正式故障（独立动作，不依赖研判）；
 * - following_up（跟进中）：新增跟进记录（跳到处理进展工作区）、完成跟进、
 *   转为正式故障；
 * - completed（已完成）：重新跟进（跳到处理进展工作区，追加一条处理进展
 *   即重新进入跟进中）；
 * - converted_fault（已转故障）：查看关联故障（后续处置以故障模块为准），
 *   终态无其他业务按钮。
 * - 已删除入口：提交研判/研判/重新研判/无需跟进/关闭运行记录/研判中的
 *   跟进安排/影响判定/重要标记/转故障入口/标记重要（2026-10-06 字段删除）/
 *   修改跟进计划/跟进计划弹窗（2026-10-06 跟进计划删除，follow-up 端点
 *   一并移除，重新跟进由追加处理进展触发）；
 * - 处理进展页签 = 统一处理工作区（2026-10-06 优化：内联录入，去弹窗）：
 *   新增处理进展（处理时间/处理人/处理内容内联表单，追加式，处理过程的唯一
 *   记录入口）→ 处理进展时间线；处理结果/本次工时字段已删除，结果性描述
 *   写入处理内容；完成跟进为纯确认动作；更正仍走弹窗（原内容留痕）；
 * - 所有动作成功后重新获取真实数据；错误提示由 http 拦截器统一弹出，
 *   业务代码不重复提示。
 * 约束：凡在 render 中读取 store observable 的函数组件必须用 observer 包裹。
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Tabs, Descriptions, Tag, Spin, Button, Timeline, Modal, Form,
  Input, DatePicker, Select, Row, Col, message, Empty } from 'antd';
import moment from 'moment';
import { AuthButton, AttachmentManager } from 'components';
import { http } from 'libs';
import { history } from 'libs';
import store from './store';
import { API_PREFIX, PERM, RUNTIME_STATUS_TEXT, RUNTIME_STATUS_COLOR,
  RUNTIME_CATEGORY_TEXT, RUNTIME_RECORD_TYPE_TEXT, RUNTIME_RECORD_TYPE_COLOR } from '../constants';

const {TextArea} = Input;
const {TabPane} = Tabs;

// 页签内可编辑（追加进展/更正/附件上传）的状态：已完成仍可补录；
// 已转故障为终态。
const EDITABLE_STATUSES = ['recorded', 'following_up', 'completed'];
// 已记录：新建成功即已记录（可长期保留，不作为待办），享有同一组顶部动作
const RECORDED_LIKE_STATUSES = ['recorded'];

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

  // 基本信息（2026-10-04 信息分层收敛）：运行概况 / 关联与登记 / 处理概览
  // 三区块。编号、状态只在标题区展示一次，区块内不再重复；研判结论区块
  // 已随研判快照字段删除移除（2026-10-07）。
  renderBasic() {
    return (
      <div>
        {this.renderSectionTitle('运行概况')}
        {this.renderOverviewSection()}
        {this.renderRegistrySection()}
        {this.renderHandlingOverview()}
      </div>
    );
  }

  // 一、运行概况：只展示记录发生时的事实（按发生顺序），不放研判结论、
  // 跟进安排或处理结果；标题保持"标题"字样，不与故障模块"故障现象"混用；
  // 具体对象/型号行已随字段删除移除（2026-10-06）。
  // 日常运行记录（2026-10-07）：类别行展示"记录类别"，并展示类型专属的
  // 作业内容/操作结果或检查结果（复用后端 measures_taken/handling_result
  // 字段承载）；异常事件保持"异常类别"与原有展示。
  renderOverviewSection() {
    const d = store.detail;
    const isRoutine = d.record_type === 'routine';
    return (
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="所属系统">{d.system_name}</Descriptions.Item>
        <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="发生时间">{d.occurred_at}</Descriptions.Item>
        <Descriptions.Item label={isRoutine ? '记录类别' : '异常类别'}>
          {d.category ? (RUNTIME_CATEGORY_TEXT[d.category] || d.category) : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="标题" span={2}>{d.title}</Descriptions.Item>
        <Descriptions.Item label="情况描述" span={2}>{d.description}</Descriptions.Item>
        {isRoutine && (
          <Descriptions.Item label="作业内容" span={2}>
            {d.measures_taken || '-'}
          </Descriptions.Item>
        )}
        {isRoutine && (
          <Descriptions.Item label="操作结果/检查结果" span={2}>
            {d.handling_result || '-'}
          </Descriptions.Item>
        )}
      </Descriptions>
    );
  }

  // 二、关联与登记：记录来源与生命周期追溯。统一"登记人/登记时间"业务
  // 口径（登记时间即创建时间，创建人不再重复展示）；已转故障显示可点击
  // 关联故障（沿用现有跳转），关联故障已撤销时明确提示，无关联显示"-"、
  // 不渲染空按钮；已转故障的处置去向提示移入本区块（原研判结论区块
  // 已随研判快照字段删除移除 2026-10-07）；处理时间属于生命周期状态变更
  // 信息，仅在存在数据时展示（标记重要行已随字段删除移除，2026-10-06；
  // "记录关联日常运行"功能已于 2026-10-07 按用户决策整体移除）。
  renderRegistrySection() {
    const d = store.detail;
    const converted = d.status === 'converted_fault';
    return (
      <React.Fragment>
        {this.renderSectionTitle('关联与登记', {marginTop: 16})}
        {converted && (
          <div style={{color: 'rgba(0, 0, 0, 0.45)', marginBottom: 8}}>
            该记录已转正式故障，后续处置以关联故障为准
          </div>
        )}
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
    // 日常运行记录无处理进展流程（作业是否完成以"操作结果/检查结果"表达）
    if (store.detail.record_type === 'routine') return null;
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
    // 标题区只保留摘要（2026-10-04 对齐故障详情）：编号/记录类型/当前状态；
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
          {d.record_no || '运行记录详情'}
        </span>
        {d.record_type && (
          <Tag color={RUNTIME_RECORD_TYPE_COLOR[d.record_type]}>
            {RUNTIME_RECORD_TYPE_TEXT[d.record_type] || d.record_type}
          </Tag>
        )}
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
    const isRoutine = d.record_type === 'routine';
    const recordedLike = RECORDED_LIKE_STATUSES.includes(status);
    const following = status === 'following_up';
    const doneLike = status === 'completed';
    // 开始跟进/新增跟进记录/重新跟进都只是跳到处理进展工作区：
    // 追加处理进展是唯一的跟进动作（保存后由后端流转状态）
    const goToProgress = () => this.setState({activeTab: 'progress'});
    // 日常运行记录（2026-10-07）：只保留 查看/编辑/上传和管理附件/删除，
    // 不显示也不提供 研判/跟进/完成跟进/关闭异常记录/转正式故障 等异常
    // 操作（后端对异常专属接口独立拒绝）；页面状态恒为"已记录"
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
            {isRoutine && <AuthEditButton/>}
            {isRoutine && <AuthDeleteButton/>}
            {!isRoutine && recordedLike && <AuthEditButton/>}
            {!isRoutine && recordedLike && (
              <AuthPrimaryActionButton
                auth={PERM.RUNTIME_EDIT}
                text="开始跟进"
                onClick={goToProgress}
              />
            )}
            {!isRoutine && following && (
              <AuthPrimaryActionButton
                auth={PERM.RUNTIME_EDIT}
                text="新增跟进记录"
                onClick={goToProgress}
              />
            )}
            {!isRoutine && following && <AuthCompleteButton/>}
            {!isRoutine && (recordedLike || following) && <AuthConvertButton/>}
            {!isRoutine && doneLike && (
              <AuthPrimaryActionButton
                auth={PERM.RUNTIME_EDIT}
                text="重新跟进"
                onClick={goToProgress}
              />
            )}
            {!isRoutine && status === 'converted_fault' && d.converted_fault && <AuthViewFaultButton/>}
          </div>
          {/* 页签受控（本地 state）：处理概览"查看全部进展"与顶部跟进动作
              可直达处理进展页签；组件随详情开关重新挂载，每次打开回到基本
              信息页签。日常运行记录无处理进展页签（无跟进流程） */}
          <Tabs activeKey={this.state.activeTab} onChange={this.handleTabChange}>
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            {!isRoutine && (
              <TabPane tab="处理进展" key="progress">
                <ProgressTimeline editable={editable}/>
              </TabPane>
            )}
            <TabPane tab="附件" key="attachments">
              <AttachmentTab editable={editable}/>
            </TabPane>
          </Tabs>
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

// 删除运行记录（2026-10-07，仅日常运行记录；后端独立校验记录类型）：
// 确认后物理删除并联动清理附件，异常事件记录不提供删除
function AuthDeleteButton() {
  const [visible, setVisible] = useState(false);
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton
        auth={PERM.RUNTIME_DEL}
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
function AuthPrimaryActionButton({auth, text, onClick}) {
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={auth} type="primary" onClick={onClick}>{text}</AuthButton>
    </span>
  );
}

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

// 转正式故障确认：现象缺省由后端带入运行记录标题与描述；仅当该记录曾转
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
        将创建一条正式故障并关联本运行记录，记录进入"已转故障"；
        后续处理/恢复确认/关闭全部在故障模块完成。
      </p>
      <Form layout="vertical">
        <Form.Item label="故障现象" style={{marginBottom: 12}}>
          <TextArea
            rows={3}
            value={phenomenon}
            onChange={e => setPhenomenon(e.target.value)}
            placeholder="选填，缺省带入运行记录标题与情况描述"
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
// 统一处理工作区（2026-10-06 优化：内联录入，去弹窗）：新增处理进展
// （处理时间/处理人/处理内容内联表单，追加式，处理过程的唯一记录入口，
// 已记录保存首条进展后进入跟进中、已完成追加进展即重新跟进）→ 处理进展
// 时间线；终态（已转故障）只读查看时间线。处理结果/本次工时字段已删除，
// 结果性描述直接写入处理内容。
const ProgressTimeline = observer(function ProgressTimeline({editable}) {
  const d = store.detail;
  const recordedLike = d.status === 'recorded';
  const doneLike = d.status === 'completed';
  return (
    <div>
      {editable && (
        <React.Fragment>
          {sectionTitle('新增处理进展')}
          {recordedLike && (
            <p style={{color: 'rgba(0, 0, 0, 0.45)', margin: '0 0 8px'}}>
              尚未开始跟进：保存第一条处理进展后进入跟进中。
            </p>
          )}
          {doneLike && (
            <p style={{color: 'rgba(0, 0, 0, 0.45)', margin: '0 0 8px'}}>
              跟进已完成：追加新的处理进展将重新进入跟进中。
            </p>
          )}
          <div style={{marginBottom: 16}}>
            <AddProgressForm/>
          </div>
        </React.Fragment>
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

// 内联新增处理进展表单（2026-10-06 优化：原"按钮 → 弹窗"两步合并为页签内
// 直接填写；处理时间缺省当前时间；处理人为手动输入姓名，回车确认可多个；
// 处理结果/本次工时字段已删除，结果性描述写入处理内容）。保存成功后清空
// 表单（处理时间回到当前时间），刷新由 store.addProgressRecord 统一完成。
function AddProgressForm() {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const handleSubmit = () => {
    form.validateFields().then(values => {
      setSaving(true);
      store.addProgressRecord({
        handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
        // 标签数组以顿号拼接为处理人姓名文本（多人）
        handler_name: (values.handler_names || []).join('、'),
        content: values.content,
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
          <Col span={16}>
            <Form.Item
              name="handler_names"
              label="处理人"
              rules={[{required: true, type: 'array', message: '请输入姓名后回车确认'}]}
              style={{marginBottom: 12}}
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
          </Col>
        </Row>
        <Form.Item
          name="content"
          label="处理内容"
          rules={[{required: true, message: '请填写处理内容'}]}
          style={{marginBottom: 12}}
        >
          <TextArea rows={3} placeholder="如：现场检查情况、已采取的措施、跟进结论等"/>
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

// 更正处理进展弹窗（更正专用：新增走工作区内联表单）。原内容、修改内容与
// 更正原因一并留痕保存，不静默覆盖。
function ProgressModal({visible, record, onClose}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  // initialValues + destroyOnClose（与故障确认恢复弹窗同一模式）：每次打开
  // 重新挂载表单取最新值，避免 Modal 惰性挂载下 setFieldsValue 与字段注册
  // 时序错位导致受控失效
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
          store.correctProgressRecord(record.id, {
            handled_at: values.handled_at.format('YYYY-MM-DD HH:mm'),
            // 标签数组以顿号拼接为处理人姓名文本（多人）
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
          {/* open=false：仅手输姓名（回车/失焦添加），与故障登记人输入一致 */}
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

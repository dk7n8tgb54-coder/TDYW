/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行处置记录详情窗口（2026-10-11 合并改造）。
 * 合并原 FaultDetail 与 runtimeRecord/RecordDetail 为统一详情：
 * 一个详情页展示 基本信息 / 进展 / 附件 三个页签，进展页签标题随记录类型
 * （一般记录=补充记录、异常事件=跟进记录、设备故障=处置记录），顶部动作
 * 按钮与基本信息区块按记录类型与状态匹配：
 * - 一般记录（routine，恒为已记录）：添加补充记录（不改状态）/ 编辑 / 删除 /
 *   附件；
 * - 异常事件（abnormal）：添加跟进记录（首条即开始跟进、已完成追加即重新
 *   跟进，后端驱动）/ 编辑 / 完成跟进 / 认定设备故障（原记录原地变更，
 *   不创建第二张单）；
 * - 设备故障（fault）：添加处置记录 / 确认恢复并结案（recover+close 双权限）/
 *   撤销登记；已关闭/已撤销封闭（已撤销仅供历史追溯）。
 * 基本信息三区块：运行概况（事实，含持续时间=最新进展时间-发生时间，/
 * 2026-10-14 起由列表移至详情展示）/ 处置结果（仅设备故障：原因分析状态化
 * + 恢复信息 + 结案说明）/ 来源与登记（台账来源追溯 + 登记人/登记时间）。
 * 处置中且无恢复数据时以"尚未完成恢复确认"提示代替成排"-"；
 * 原因分析状态化：尚未分析 / 初步判断 / 最终原因 / 原因未明。
 * 2026-10-14 体验二轮：详情顶部按类型与状态给出"下一步"操作指引（当前
 * 最重要动作突出，编辑/删除/撤销等低频操作降低视觉权重，见
 * RecordDetailActions）；"持续时间"更名"发生至最近进展"并附口径说明
 * （不暗示故障恢复耗时），已关闭故障在处置结果中展示真实"恢复耗时"
 * （恢复时间-发生时间）；Descriptions 与弹窗宽度适配窄屏。
 * 2026-10-18 顶部按钮样式统一：主操作=蓝色实心、常规操作=普通描边、删除/
 * 撤销=红色描边，间距由顶部动作区 flex 容器统一管理（见 ACTION_BAR_STYLE），
 * 危险操作与常规操作分组；异常事件已完成的主按钮呈现"重新跟进"（复用
 * 添加跟进记录弹窗，提交后由后端驱动重新进入"跟进中"）。
 * 2026-10-18 页签改单页分区：移除"基本信息/进展/附件"三页签，详情为单一
 * 滚动内容区，依次展示 基本信息各区块 → 进展时间线（标题随记录类型并携带
 * 总数）→ 附件；原"进展概览"摘要区退役（同一份进展内容不再重复展示）。
 * 原进展页签定位入口（进展数列等）改为区块锚点滚动定位，在详情内容加载
 * 完成后执行并复位（见 detailSections.js/componentDidUpdate）。
 * 2026-10-18 附件可见性改善：顶部动作区尾部新增"附件（N）"快捷入口（与
 * 附件区块标题共用 store 附件状态，打开详情即可见数量，点击展开并定位）；
 * 附件区块改为可折叠并上移到进展时间线之前（避免被大量进展推到页尾），
 * 默认收起、点击标题展开/收起，面板常驻挂载仅切换显示（折叠不中断上传）；
 * 附件数量=全部有效附件（列表请求收敛为 AttachmentManager 的 listRequest
 * 适配器走 store，单请求；上传/删除真实成功后经 onCountChange 回写总数，
 * 失败不显示为 0 而呈现"附件加载失败"并可重试）。
 * 进展页签 = 追加式时间线（更正走弹窗，原内容留痕）；2026-10-14 起
 * "添加跟进记录/补充记录/处置记录"入口在顶部动作区（弹窗录入，按记录类型
 * 命名），页签不再放内联表单。材料统一在"附件"页签以记录级管理。
 * 错误提示由 http 拦截器统一弹出，业务代码不重复提示。
 * 详情加载失败（2026-10-15）：显式失败态 + 重试入口（重试保持当前记录与
 * 目标页签，成功后恢复正常显示）；失败时不渲染依赖完整详情的状态操作与
 * 页签，不把列表行旧数据冒充完整详情。
 * 约束：凡在 render 中读取 store observable 的函数组件必须用 observer 包裹。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Descriptions, Tag, Spin, Button, Modal, Alert, Tooltip, Result} from 'antd';
import {CaretRightOutlined, PaperClipOutlined, QuestionCircleOutlined} from '@ant-design/icons';
import {AttachmentManager} from 'components';
import {http, history} from 'libs';
import store from './store';
import {
  API_PREFIX, PERM, RECORD_STATUS_TEXT, RECORD_STATUS_COLOR,
  RECORD_TYPE_TEXT, RECORD_TYPE_COLOR, RECORD_CATEGORY_TEXT,
  FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR,
} from '../constants';
import {
  AuthEditButton, AuthDeleteButton, AuthAddProgressButton, AuthCompleteButton,
  AuthIdentifyFaultButton, AuthRecoverAndCloseButton, AuthCancelButton,
} from './RecordDetailActions';
import ReasonAnalysisCell from './ReasonAnalysisModal';
import ProgressTimeline from './ProgressTimeline';
import {LEDGER_TYPE_PATH} from '../ledger/constants';
import {
  PROGRESS_SECTION_ID, ATTACHMENT_SECTION_ID, ATTACHMENT_PANEL_ID,
  scrollToSection,
} from './detailSections';
import {sectionTitle, PROGRESS_TAB_TEXT, formatDuration, nextStepHint,
  recoveryDurationSeconds} from './shared';

// 记录可编辑（追加进展/更正/记录附件上传）的状态集合（由后端 editable_statuses 对应）：
// routine 恒 recorded；abnormal 无终态；fault 仅处置中
const EDITABLE_STATUSES = ['recorded', 'following_up', 'completed', 'handling'];

// Descriptions 响应式列数：宽屏两列、窄屏单列（避免窄屏下标签与内容挤压）
const DESCRIPTION_COLUMN = {xxl: 2, xl: 2, lg: 2, md: 1, sm: 1, xs: 1};

// 顶部动作区布局（2026-10-18 样式统一）：flex + gap 统一各按钮的横向间距与
// 换行后的纵向间距，各按钮不再携带零散 marginLeft / padding:0；危险操作
// （删除/撤销故障登记）通过 DANGER_GROUP_STYLE 与常规操作分组（叠加 gap
// 约 16px），样式经 AuthButton 透传到真实按钮——无权限时按钮返回 null，
// 不留空白或多余间距
const ACTION_BAR_STYLE = {
  display: 'flex',
  flexWrap: 'wrap',
  alignItems: 'center',
  gap: 8,
  marginBottom: 12,
};
const DANGER_GROUP_STYLE = {marginLeft: 8};

// Loading and failure must not be presented as an empty attachment list.
function attachmentTitleText() {
  if (store.attachmentsError) return '附件加载失败，重试';
  if (store.isAttachmentsFetching || !store.detail.id) return '附件加载中';
  return `附件（${store.attachmentsTotal}）`;
}

// 附件区块折叠标题样式：与 sectionTitle 同观感的可聚焦按钮（键盘可达，
// aria-expanded 关联折叠面板）
const ATTACHMENT_HEADER_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  padding: 0,
  border: 'none',
  background: 'none',
  fontSize: 14,
  fontWeight: 600,
  color: 'inherit',
  cursor: 'pointer',
  marginBottom: 8,
};

// 顶部附件数量快捷入口（2026-10-18）：打开详情即可见附件数量（与附件
// 区块标题共用 attachmentTitleText 单一口径），点击展开附件区块并在弹窗内
// 定位；失败态点击即重试（附件表格重挂载重发列表请求）
const AttachmentQuickEntry = observer(function AttachmentQuickEntry() {
  const loading = store.isAttachmentsFetching || !store.detail.id;
  return (
    <Button
      type="link"
      icon={<PaperClipOutlined/>}
      disabled={loading}
      aria-label={`查看附件：${attachmentTitleText()}`}
      onClick={() => {
        store.setAttachmentsExpanded(true);
        if (store.attachmentsError) store.retryAttachments();
        scrollToSection(ATTACHMENT_SECTION_ID);
      }}
    >
      {attachmentTitleText()}
    </Button>
  );
});

@observer
class RecordDetail extends React.Component {
  // 详情与进展请求由 store.showDetail 统一发起，挂载时不再重复请求

  renderSectionTitle(text, style) {
    return sectionTitle(text, style);
  }

  // 一、运行概况：只展示记录发生时的事实；设备故障展示故障部位/设备。
  // "发生至最近进展"（2026-10-14 由"持续时间"更名）：口径为最近一条进展
  // 的处理时间 - 发生时间，不暗示故障恢复耗时（真实恢复耗时见"处置结果"
  // 的"恢复耗时"），附 Tooltip 说明避免误读
  renderOverviewSection() {
    const d = store.detail;
    const isFault = d.record_type === 'fault';
    const faultObject = [
      d.fault_object_name, d.fault_object_model, d.fault_object_sn,
    ].filter(Boolean).join(' / ');
    return (
      <Descriptions bordered size="small" column={DESCRIPTION_COLUMN}>
        <Descriptions.Item label={isFault ? '故障系统' : '所属系统'}>
          {d.system_name}
        </Descriptions.Item>
        <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="发生时间">{d.occurred_at}</Descriptions.Item>
        <Descriptions.Item label={(
          <span>
            发生至最近进展
            <Tooltip title={'口径：最近一条进展的处理时间 - 发生时间；该数值不是故障恢复耗时，设备故障的真实恢复耗时见下方「处置结果」中的「恢复耗时」。'}>
              <QuestionCircleOutlined style={{marginLeft: 4, color: 'rgba(0, 0, 0, 0.45)'}}/>
            </Tooltip>
          </span>
        )}>
          {formatDuration(d.duration_seconds)}
        </Descriptions.Item>
        {isFault && (
          <Descriptions.Item label="故障部位/设备" span={2}>
            {faultObject || '-'}
          </Descriptions.Item>
        )}
        {!isFault && (
          <Descriptions.Item label={d.record_type === 'routine' ? '记录类别' : '异常类别'}>
            {d.category ? (RECORD_CATEGORY_TEXT[d.category] || d.category) : '-'}
          </Descriptions.Item>
        )}
        <Descriptions.Item label="标题" span={2}>{d.title}</Descriptions.Item>
        <Descriptions.Item label="情况描述" span={2}>{d.description}</Descriptions.Item>
      </Descriptions>
    );
  }

  // 二、处置结果（仅设备故障）：原因分析状态化 + 恢复结果 + 结案说明。
  // 处置中且无任何恢复数据时以简洁提示代替成排"-"字段；已撤销记录没有
  // 恢复语义，恢复结果行不展示，由"撤销登记"区块承载撤销信息。
  // "恢复耗时"（2026-10-14 新增展示）= 恢复时间 - 发生时间，是设备故障
  // 真实的恢复耗时口径，与概况区"发生至最近进展"明确区分
  renderResultSection(editable) {
    const d = store.detail;
    const hasRecoveryData = Boolean(
      d.recovered_at || d.recovered_by_name || d.recovery_close_note);
    const awaitingRecovery = !hasRecoveryData && d.status === 'handling';
    const recoverySeconds = recoveryDurationSeconds(d);
    return (
      <React.Fragment>
        {this.renderSectionTitle('处置结果', {marginTop: 16})}
        <Descriptions bordered size="small" column={DESCRIPTION_COLUMN}>
          {/* 原因分析状态化：尚未分析/初步判断/最终原因/原因未明；
              处置中可补充或修改（专用端点），已关闭只读展示最终原因 */}
          <Descriptions.Item label="原因分析" span={2}>
            <ReasonAnalysisCell editable={editable}/>
          </Descriptions.Item>
          {awaitingRecovery ? (
            <Descriptions.Item label="恢复结果" span={2}>
              <span style={{color: 'rgba(0, 0, 0, 0.45)'}}>尚未完成恢复确认</span>
            </Descriptions.Item>
          ) : d.status === 'cancelled' ? null : (
            <React.Fragment>
              <Descriptions.Item label="恢复时间">{d.recovered_at || '-'}</Descriptions.Item>
              <Descriptions.Item label="恢复确认人">
                {d.recovered_by_name
                  ? `${d.recovered_by_name}（${d.recovered_confirmed_at || ''}）` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="恢复耗时">
                {formatDuration(recoverySeconds)}
              </Descriptions.Item>
              <Descriptions.Item label="结案说明" span={2}>
                {d.recovery_close_note || '-'}
              </Descriptions.Item>
            </React.Fragment>
          )}
        </Descriptions>
      </React.Fragment>
    );
  }

  // 三、来源与登记：台账来源追溯 + 登记人/登记时间 + 生命周期信息
  renderRegistrySection() {
    const d = store.detail;
    return (
      <React.Fragment>
        {this.renderSectionTitle('来源与登记', {marginTop: 16})}
        <Descriptions bordered size="small" column={DESCRIPTION_COLUMN}>
          {/* 台账异常转故障来源追溯（来源明细仍存在时可跳回来源台账） */}
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
              {d.source_ledger_no}（来源台账明细已删除，仅展示追溯信息）
            </Descriptions.Item>
          )}
          <Descriptions.Item label="登记人">{d.registrar_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="登记时间">{d.created_at}</Descriptions.Item>
          {d.resolved_at && (
            <Descriptions.Item label="首次完成跟进时间">{d.resolved_at}</Descriptions.Item>
          )}
          <Descriptions.Item label="登记账号（审计）">
            {d.created_by_name || '-'}
          </Descriptions.Item>
        </Descriptions>
      </React.Fragment>
    );
  }

  // 撤销登记区块：已撤销记录回显撤销原因/时间/人，仅供历史追溯
  renderCancelSection() {
    const d = store.detail;
    return (
      <div>
        {this.renderSectionTitle('撤销登记', {marginTop: 16})}
        <Descriptions bordered size="small" column={DESCRIPTION_COLUMN}>
          <Descriptions.Item label="撤销原因" span={2}>{d.cancel_reason || '-'}</Descriptions.Item>
          <Descriptions.Item label="撤销时间">{d.cancelled_at || '-'}</Descriptions.Item>
          <Descriptions.Item label="撤销人">{d.cancelled_by_name || '-'}</Descriptions.Item>
        </Descriptions>
      </div>
    );
  }

  // 进展区块（2026-10-18 单页分区，原"进展概览"摘要与进展页签合并）：
  // 摘要区退役——同一份进展内容不再重复展示，总数并入区块标题
  // "跟进记录（N）"（加载中不带数量，与原页签标题口径一致）；
  // 时间线完整内容直接在此展示，区块锚点承接原进展页签定位入口
  renderProgressSection(editable) {
    const d = store.detail;
    const typeLabel = PROGRESS_TAB_TEXT[d.record_type] || '处理进展';
    const title = store.isProgressFetching
      ? typeLabel : `${typeLabel}（${store.progressTotal}）`;
    return (
      <div id={PROGRESS_SECTION_ID} style={{marginTop: 16}}>
        {this.renderSectionTitle(title)}
        <ProgressTimeline editable={editable}/>
      </div>
    );
  }

  // 附件区块（2026-10-18 可折叠，置于进展时间线之前）：标题始终展示数量
  // 或加载/失败状态，点击展开/收起（失败态点击=重试）；面板常驻挂载仅
  // 切换显示——折叠不中断正在进行的上传、不丢失操作状态。展开/收起状态
  // 在 store（attachmentsExpanded），切换记录时随 showDetail 重置为收起
  renderAttachmentSection(editable) {
    const expanded = store.attachmentsExpanded;
    return (
      <div id={ATTACHMENT_SECTION_ID} style={{marginTop: 16}}>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={ATTACHMENT_PANEL_ID}
          onClick={() => {
            if (store.attachmentsError) {
              // 失败态点击标题=重试（并展开便于确认恢复结果）
              store.retryAttachments();
              store.setAttachmentsExpanded(true);
              return;
            }
            store.toggleAttachmentsExpanded();
          }}
          style={ATTACHMENT_HEADER_STYLE}
        >
          <CaretRightOutlined rotate={expanded ? 90 : 0}/>
          {attachmentTitleText()}
        </button>
        <div
          id={ATTACHMENT_PANEL_ID}
          style={{display: expanded ? 'block' : 'none'}}
        >
          <AttachmentTab editable={editable}/>
        </div>
      </div>
    );
  }

  renderBasic() {
    const d = store.detail;
    const isFault = d.record_type === 'fault';
    // 处置中是故障唯一进行态：原因分析补充/修改入口仅此时展示
    const editable = isFault && d.status === 'handling';
    return (
      <div>
        {this.renderSectionTitle(isFault ? '故障概况' : '运行概况')}
        {this.renderOverviewSection()}
        {isFault && this.renderResultSection(editable)}
        {d.status === 'cancelled' && this.renderCancelSection()}
        {this.renderRegistrySection()}
      </div>
    );
  }

  // 定位到目标区块（2026-10-18 页签改分区）：原 progress/attachments 定位
  // 入口（进展数列等）在详情内容加载完成后滚动定位并复位目标。加载中/
  // 失败态不消费目标——失败保留目标，重试成功后仍按原目标定位；定位执行
  // 一次后复位，后续动作刷新等重渲染不再重复滚动
  componentDidUpdate() {
    const target = store.pendingSection;
    if (target === 'basic' || !store.detailVisible
        || store.isDetailFetching || store.detailError) return;
    if (target === 'progress') {
      scrollToSection(PROGRESS_SECTION_ID);
    } else if (target === 'attachments') {
      // 原"查看附件"类定位入口：自动展开附件区块并定位（内容就绪后执行）
      store.setAttachmentsExpanded(true);
      scrollToSection(ATTACHMENT_SECTION_ID);
    }
    store.pendingSection = 'basic';
  }

  renderTitle() {
    const d = store.detail;
    // 失败态标题只标识目标记录，不渲染来自列表行的类型/状态标签（可能过期）
    if (store.detailError) {
      return (
        <span style={{fontSize: 16, fontWeight: 600}}>
          {d.record_no || '记录详情'}
          <span style={{
            marginLeft: 8, fontSize: 13, fontWeight: 400,
            color: 'rgba(0, 0, 0, 0.45)',
          }}>
            加载失败
          </span>
        </span>
      );
    }
    // 标题区只保留摘要：编号/记录类型/当前状态；设备故障附加影响程度标签
    // （不影响运行展示中性标签）；已撤销使用虚线灰样式明显区别
    return (
      <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap'}}>
        <span
          title={d.record_no}
          style={{
            fontSize: 16, fontWeight: 600, marginRight: 8, maxWidth: 420,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {d.record_no || '记录详情'}
        </span>
        {d.record_type && (
          <Tag color={RECORD_TYPE_COLOR[d.record_type]}>
            {RECORD_TYPE_TEXT[d.record_type] || d.record_type}
          </Tag>
        )}
        {d.status === 'cancelled' ? (
          <Tag
            color="default"
            style={{borderStyle: 'dashed', color: 'rgba(0, 0, 0, 0.45)'}}
          >
            {RECORD_STATUS_TEXT[d.status] || d.status}
          </Tag>
        ) : (
          <Tag color={RECORD_STATUS_COLOR[d.status]}>
            {RECORD_STATUS_TEXT[d.status] || d.status}
          </Tag>
        )}
        {d.record_type === 'fault' && (d.affects_system_operation ? (
          <Tag color={FAULT_IMPACT_COLOR[d.impact_status]}>
            {FAULT_IMPACT_TEXT[d.impact_status] || d.impact_status}
          </Tag>
        ) : (
          <Tag>不影响运行</Tag>
        ))}
      </div>
    );
  }

  // 详情加载失败态（2026-10-15）：显式失败提示 + 重试入口（重试保持当前
  // 记录与目标页签，成功后恢复正常显示）。失败时不渲染依赖完整详情的
  // 状态操作与页签，避免基于列表行旧数据误操作；错误 toast 已由 http
  // 拦截器弹出，此处不重复提示
  renderErrorState() {
    const d = store.detail;
    return (
      <div style={{padding: '40px 0'}}>
        <Result
          status="warning"
          title="详情加载失败"
          subTitle={d.record_no
            ? `记录「${d.record_no}」的详情未能加载，请重试；若持续失败请联系管理员。`
            : '详情未能加载，请重试；若持续失败请联系管理员。'}
          extra={(
            <Button
              type="primary"
              loading={store.isDetailFetching}
              onClick={() => store.retryDetailLoad()}
            >
              重试
            </Button>
          )}
        />
      </div>
    );
  }

  render() {
    const d = store.detail;
    const editable = EDITABLE_STATUSES.includes(d.status);
    const status = d.status;
    const isFault = d.record_type === 'fault';
    const isRoutine = d.record_type === 'routine';
    const isAbnormal = d.record_type === 'abnormal';
    const handling = status === 'handling';
    return (
      <Modal
        title={this.renderTitle()}
        visible={store.detailVisible}
        width={1100}
        style={{maxWidth: 'calc(100vw - 24px)'}}
        centered
        destroyOnClose
        onCancel={() => store.closeDetail()}
        bodyStyle={{
          height: 'calc(100vh - 180px)',
          minHeight: 320,
          overflow: 'auto',
          paddingTop: 12,
        }}
        /* 底部按钮只关闭详情窗口，不改业务状态；业务动作是顶部按钮 */
        footer={<Button onClick={() => store.closeDetail()}>关 闭</Button>}
      >
        <Spin spinning={store.isDetailFetching}>
          {/* 加载失败显式呈现（含重试入口），不渲染依赖完整详情的正文与动作 */}
          {store.detailError ? this.renderErrorState() : (
            <React.Fragment>
              {/* 已撤销登记：顶部明确提示只读仅供历史追溯（后端同样拒绝一切写操作） */}
              {d.status === 'cancelled' && (
                <Alert
                  type="warning"
                  showIcon
                  message="该登记已撤销，仅供历史追溯"
                  description="这条故障登记已撤销，不再作为有效故障参与统计与健康状态计算；历史记录保留，可查看但无法继续处理。"
                  style={{marginBottom: 12}}
                />
              )}
              {/* 当前状态下最重要的"下一步"指引（与可用动作一致；已撤销由上方
                  横幅承载，nextStepHint 不再重复提示） */}
              {nextStepHint(d) && (
                <Alert type="info" showIcon message={nextStepHint(d)} style={{marginBottom: 12}}/>
              )}
              {/* 顶部动作区（2026-10-18 样式统一）：各阶段可用组合——
                  一般记录已记录 = 添加补充记录〔主按钮〕/ 编辑〔描边〕/
                  删除〔红色描边〕；异常事件已记录 = 添加跟进记录/编辑/
                  认定设备故障，跟进中追加完成跟进，已完成 = 重新跟进/编辑
                  （重新跟进复用添加跟进记录弹窗，提交后由后端驱动重新进入
                  "跟进中"）；设备故障处置中 = 添加处置记录/确认恢复并结案/
                  撤销故障登记，已关闭与已撤销保持只读。添加跟进/补充/处置
                  记录自 2026-10-14 起弹窗录入，异常事件第一条跟进记录即开始
                  跟进、已完成追加即重新跟进（后端驱动状态变化） */}
              <div style={ACTION_BAR_STYLE}>
                {EDITABLE_STATUSES.includes(status) && <AuthAddProgressButton/>}
                {isRoutine && <AuthEditButton/>}
                {isRoutine && <AuthDeleteButton style={DANGER_GROUP_STYLE}/>}
                {isAbnormal && (status === 'recorded' || status === 'following_up'
                  || status === 'completed') && <AuthEditButton/>}
                {isAbnormal && status === 'following_up' && <AuthCompleteButton/>}
                {isAbnormal && (status === 'recorded' || status === 'following_up') && (
                  <AuthIdentifyFaultButton/>
                )}
                {isFault && handling && <AuthRecoverAndCloseButton record={d}/>}
                {isFault && handling && (
                  <AuthCancelButton record={d} style={DANGER_GROUP_STYLE}/>
                )}
                {/* 附件数量快捷入口（2026-10-18）：与附件区块标题共用状态，
                    打开详情即可见数量，点击展开并定位到附件区块 */}
                <AttachmentQuickEntry/>
              </div>
              {/* 单页分区（2026-10-18 页签改分区；2026-10-18 附件上移）：
                  基本信息各区块 → 可折叠附件区（避免被大量进展推到页尾）→
                  进展时间线（标题随类型并携带总数），同一滚动内容区依次
                  展示；滚动由弹窗内容区统一承载（bodyStyle overflow auto） */}
              {this.renderBasic()}
              {this.renderAttachmentSection(editable)}
              {this.renderProgressSection(editable)}
            </React.Fragment>
          )}
        </Spin>
      </Modal>
    );
  }
}

// 附件区块内容（2026-10-18 可折叠面板，常驻挂载仅切换显示）：沿用公共
// AttachmentManager 的记录级附件管理（上传/预览/下载/删除与权限控制不变），
// 非可编辑状态（已关闭/已撤销）只读展示。列表请求走 store 的 listRequest
// 适配器（单请求同时供数量统计），上传/删除真实成功后经 onCountChange
// 回写 store 总数；key 绑定重试序号——重试时重挂载并重发列表请求
function AttachmentTab({editable}) {
  const d = store.detail;
  if (!d.id) return null;
  const base = `${API_PREFIX}/records/${d.id}/attachments/`;
  return (
    <AttachmentManager
      key={`${d.id}-${store.attachmentRetrySeq}`}
      module="equipment_lifecycle"
      objectType="el_operation_record"
      recordId={d.id}
      listRequest={store.fetchAttachmentList}
      onCountChange={count => store.syncAttachmentCount(count, d.id)}
      uploadUrl={base}
      deleteRequest={att => http.delete(`${base}${att.id}/`)}
      downloadUrlPrefix={base}
      uploadPerm={PERM.OP_EDIT}
      deletePerm={PERM.OP_EDIT}
      downloadPerm={PERM.OP_VIEW}
      readOnly={!editable}
    />
  );
}

export default RecordDetail;

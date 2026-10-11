/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——运行与故障记录详情窗口（2026-10-11 合并改造）。
 * 合并原 FaultDetail 与 runtimeRecord/RecordDetail 为统一详情：
 * 一个详情页展示 基本信息 / 统一进展 / 附件 三个页签，顶部动作按钮与
 * 基本信息区块按记录类型与状态匹配：
 * - 日常运行（routine，恒为已记录）：编辑 / 删除 / 补充进展（不改状态）/ 附件；
 * - 异常事件（abnormal）：编辑 / 开始跟进（跳进展工作区）/ 完成跟进 /
 *   重新跟进 / 认定正式故障（原记录原地变更，不创建第二张单）；
 * - 正式故障（fault）：编辑 / 确认恢复并结案（recover+close 双权限）/
 *   撤销登记 / 补充原因分析；已关闭/已撤销封闭（已撤销仅供历史追溯）。
 * 基本信息三区块：运行概况（事实）/ 处置结果（仅正式故障：原因分析状态化
 * + 恢复信息 + 结案说明）/ 来源与登记（台账来源追溯 + 登记人/登记时间）。
 * 处置中且无恢复数据时以"尚未完成恢复确认"提示代替成排"-"；
 * 原因分析状态化：尚未分析 / 初步判断 / 最终原因 / 原因未明。
 * 统一进展页签 = 统一处理工作区（内联录入）：处理时间/处理人/处理内容/
 * 可选工时；更正走弹窗（原内容留痕）；进展附件随每条进展管理。
 * 错误提示由 http 拦截器统一弹出，业务代码不重复提示。
 * 约束：凡在 render 中读取 store observable 的函数组件必须用 observer 包裹。
 */
import React, {useState, useEffect} from 'react';
import {observer} from 'mobx-react';
import {Tabs, Descriptions, Tag, Spin, Button, Timeline, Modal, Form,
  Input, DatePicker, Select, Checkbox, InputNumber, Row, Col, message,
  Empty, Alert} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import moment from 'moment';
import {AttachmentManager} from 'components';
import {http, history} from 'libs';
import store from './store';
import {
  API_PREFIX, PERM, RECORD_STATUS_TEXT, RECORD_STATUS_COLOR,
  RECORD_TYPE_TEXT, RECORD_TYPE_COLOR, RECORD_CATEGORY_TEXT,
  FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR,
} from '../constants';
import {
  AuthEditButton, AuthDeleteButton, AuthPrimaryActionButton, AuthCompleteButton,
  AuthIdentifyFaultButton, AuthRecoverAndCloseButton, AuthCancelButton,
} from './RecordDetailActions';
import ReasonAnalysisCell from './ReasonAnalysisModal';
import ProgressTimeline from './ProgressTimeline';
import {LEDGER_TYPE_PATH} from '../ledger/constants';
import {sectionTitle} from './shared';

const {TextArea} = Input;
const {TabPane} = Tabs;

// 页签内可编辑（追加进展/更正/附件上传）的状态集合（由后端 editable_statuses 对应）：
// routine 恒 recorded；abnormal 无终态；fault 仅处置中
const EDITABLE_STATUSES = ['recorded', 'following_up', 'completed', 'handling'];

@observer
class RecordDetail extends React.Component {
  // 详情与进展请求由 store.showDetail 统一发起，挂载时不再重复请求

  renderSectionTitle(text, style) {
    return sectionTitle(text, style);
  }

  // 一、运行概况：只展示记录发生时的事实；正式故障展示故障部位/设备
  renderOverviewSection() {
    const d = store.detail;
    const isFault = d.record_type === 'fault';
    const faultObject = [
      d.fault_object_name, d.fault_object_model, d.fault_object_sn,
    ].filter(Boolean).join(' / ');
    return (
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label={isFault ? '故障系统' : '所属系统'}>
          {d.system_name}
        </Descriptions.Item>
        <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
        <Descriptions.Item label="发生时间" span={2}>{d.occurred_at}</Descriptions.Item>
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

  // 二、处置结果（仅正式故障）：原因分析状态化 + 恢复结果 + 结案说明。
  // 处置中且无任何恢复数据时以简洁提示代替成排"-"字段；已撤销记录没有
  // 恢复语义，恢复结果行不展示，由"撤销登记"区块承载撤销信息。
  renderResultSection(editable) {
    const d = store.detail;
    const hasRecoveryData = Boolean(
      d.recovered_at || d.recovered_by_name || d.recovery_close_note);
    const awaitingRecovery = !hasRecoveryData && d.status === 'handling';
    return (
      <React.Fragment>
        {this.renderSectionTitle('处置结果', {marginTop: 16})}
        <Descriptions bordered size="small" column={2}>
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
        <Descriptions bordered size="small" column={2}>
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
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="撤销原因" span={2}>{d.cancel_reason || '-'}</Descriptions.Item>
          <Descriptions.Item label="撤销时间">{d.cancelled_at || '-'}</Descriptions.Item>
          <Descriptions.Item label="撤销人">{d.cancelled_by_name || '-'}</Descriptions.Item>
        </Descriptions>
      </div>
    );
  }

  // 进展概览：基本信息底部只读紧凑信息条（后端聚合的条数/最近进展时间/内容）
  renderProgressOverview() {
    const d = store.detail;
    const count = d.progress_count ?? store.progressTotal ?? 0;
    const goToProgress = () => store.setActiveTab('progress');
    return (
      <div style={{marginTop: 16}}>
        {this.renderSectionTitle('进展概览')}
        {count > 0 ? (
          <div style={{fontSize: 13}}>
            <a onClick={goToProgress}>处理进展 {count} 条</a>
            <span style={{marginLeft: 16}}>最近进展时间：{d.latest_progress_at || '-'}</span>
            <span style={{marginLeft: 16}}>最近进展：{d.latest_progress_content || '-'}</span>
            <Button type="link" style={{padding: 0, marginLeft: 16}} onClick={goToProgress}>
              查看全部进展
            </Button>
          </div>
        ) : (
          <div style={{color: 'rgba(0, 0, 0, 0.45)'}}>暂无处理进展</div>
        )}
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
        {this.renderProgressOverview()}
      </div>
    );
  }

  renderTitle() {
    const d = store.detail;
    // 标题区只保留摘要：编号/记录类型/当前状态；正式故障附加影响程度标签
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

  render() {
    const d = store.detail;
    const editable = EDITABLE_STATUSES.includes(d.status);
    const status = d.status;
    const isFault = d.record_type === 'fault';
    const isRoutine = d.record_type === 'routine';
    const isAbnormal = d.record_type === 'abnormal';
    const handling = status === 'handling';
    const progressTab = store.isProgressFetching
      ? '统一进展' : `统一进展（${store.progressTotal}）`;
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
        /* 底部按钮只关闭详情窗口，不改业务状态；业务动作是顶部按钮 */
        footer={<Button onClick={() => store.closeDetail()}>关 闭</Button>}
      >
        <Spin spinning={store.isDetailFetching}>
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
          <div style={{marginBottom: 12}}>
            {isRoutine && <AuthEditButton/>}
            {isRoutine && <AuthDeleteButton/>}
            {isAbnormal && (status === 'recorded' || status === 'following_up'
              || status === 'completed') && <AuthEditButton/>}
            {isAbnormal && status === 'recorded' && (
              <AuthPrimaryActionButton
                auth={PERM.OP_EDIT}
                text="开始跟进"
                onClick={() => store.setActiveTab('progress')}
              />
            )}
            {isAbnormal && status === 'following_up' && (
              <AuthPrimaryActionButton
                auth={PERM.OP_EDIT}
                text="新增跟进记录"
                onClick={() => store.setActiveTab('progress')}
              />
            )}
            {isAbnormal && status === 'following_up' && <AuthCompleteButton/>}
            {isAbnormal && (status === 'recorded' || status === 'following_up') && (
              <AuthIdentifyFaultButton/>
            )}
            {isAbnormal && status === 'completed' && (
              <AuthPrimaryActionButton
                auth={PERM.OP_EDIT}
                text="重新跟进"
                onClick={() => store.setActiveTab('progress')}
              />
            )}
            {isFault && handling && <AuthRecoverAndCloseButton record={d}/>}
            {isFault && handling && <AuthCancelButton record={d}/>}
          </div>
          {/* 页签受控（store.activeTab）：进展概览与顶部跟进动作可直达进展页签 */}
          <Tabs activeKey={store.activeTab} onChange={(key) => store.setActiveTab(key)}>
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            <TabPane tab={progressTab} key="progress">
              <ProgressTimeline editable={editable}/>
            </TabPane>
            <TabPane tab="附件" key="attachments">
              <AttachmentTab editable={editable}/>
            </TabPane>
          </Tabs>
        </Spin>
      </Modal>
    );
  }
}

function AttachmentTab({editable}) {
  const d = store.detail;
  if (!d.id) return null;
  const base = `${API_PREFIX}/records/${d.id}/attachments/`;
  return (
    <AttachmentManager
      module="equipment_lifecycle"
      objectType="el_operation_record"
      recordId={d.id}
      listUrl={base}
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

// AttachmentTab 引用共享工具（sectionTitle 由各子模块自行引入）

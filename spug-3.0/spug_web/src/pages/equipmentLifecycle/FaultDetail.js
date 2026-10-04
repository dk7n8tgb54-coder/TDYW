/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——故障详情窗口（2026-10-02 由侧边抽屉改为居中窗口，
 * 与系统档案详情一致）。标题区直接呈现故障编号、状态与系统影响程度，
 * 基本信息 / 处理进展时间线（追加式，支持更正留痕）/ 确认恢复并结案 / 撤销登记。
 * 2026-10 流程简化：无"开始处置"独立步骤（新建故障即处置中）；
 * 原"确认恢复"与"关闭故障"合并为一次"确认恢复并结案"操作（恢复时间/
 * 恢复确认人/结案说明一次弹窗一次校验，成功后故障直接
 * 进入终态"已关闭"，健康状态随之重算且仍尊重其他未恢复故障的影响）；
 * 结案说明字段合并（2026-10-04）：原"恢复确认信息"与"最终结果"语义重复，
 * 合并为唯一字段"结案说明"（recovery_close_note），一次性说明
 * 处理措施、恢复验证依据与最终结果，详情/弹窗/导出/履历/审计同源；
 * 最终原因分析（reason_analysis）保持独立语义（根因或原因未明依据）；
 * 旧 pending/recovered 过渡态已整体删除（模块未上线）：状态只有
 * 处置中/已关闭/已撤销；存量恢复数据打开合并弹窗仍预填既有结案说明
 * 供重新确认。
 * 撤销登记改版（2026-10-03）：原"作废"按钮改称"撤销故障登记"，用于撤销
 * 错误或重复的故障登记——撤销后不删除历史记录，该记录退出有效故障统计与
 * 健康状态计算（后端 cancelled 状态值不变，历史数据兼容）；已撤销详情
 * 只读仅供历史追溯（顶部横幅提示 + 撤销登记区块展示撤销原因/时间/人），
 * 编辑/追加进展/恢复结案/重复撤销均不提供入口（后端同样拒绝）。
 * 处理进展记录故障整体跟进（检查、本方处理、送厂、厂家反馈、返还、测试、
 * 持续观察等）；"本次工时"录入已删除（2026-10），存量记录的工时仅在时间线
 * 只读展示、不再可填可改；关联工单/生成维修工单已随工单功能删除（2026-09-30）；
 * 人员展示口径：故障登记人/恢复确认人/进展记录人均为手动输入姓名（实际
 * 登记/确认/记录的人，不关联用户账号），均不代表负责整个故障；
 * 处置负责人/发现方式/级别/影响范围/故障位置字段已删除（2026-09）；
 * 不再提供"受影响系统"页签；所有动作成功后重新获取真实数据；
 * 基本信息分三区块（2026-10）：故障概况 / 处置结果 / 来源与登记——编号、
 * 当前状态与系统影响程度只在标题区展示一次，区块内不重复；处置中且无
 * 任何恢复数据时，处置结果区块以"尚未完成恢复确认"一条提示代替成排
 * 空的"-"字段（已恢复/已关闭或已有部分恢复数据时完整展示）；
 * 处理进展页签实时显示条数（取列表接口 total）：停在基本信息页签也能
 * 看出进展是否已登记；基本信息页签底部有只读"处理概览"紧凑信息条
 * （后端统计的条数/最近更新/最后记录 + 查看全部进展，非边框表格），
 * 完整时间线仍在处理进展页签；
 * 原因分析状态化（2026-10）：原因分析是单一字段，处置结果区块按状态展示——
 * 未填写显示"尚未分析"、处置中显示"初步判断：{内容}"、已关闭显示
 * "最终原因：{内容}"、原因未明显示"原因未明：{未明说明}"（reason_unknown
 * 标记，说明仍存于 reason_analysis，不强迫用户填写虚假原因）；处置中且具备
 * fault.edit 权限时提供"补充原因分析/修改"按钮，打开只处理原因分析的专用
 * 弹窗（回填当前值、可勾选原因未明，保存后静默刷新详情）；结案弹窗提供
 * "最终原因分析"（默认回填）与"原因未明"勾选，随结案保存；处理进展新增
 * "故障定位"类型记录原因判断的依据与过程（结论在原因分析，过程在进展）；
 * 页签受控，列表"处理进展"列点击可直达处理进展页签；
 * 错误提示由 http 拦截器统一弹出，不重复提示。
 * 约束：凡在 render 中读取 store observable 的函数组件必须用 observer 包裹
 * （MobX 只追踪 observer 组件自身的读取），否则对应区域不会随 store 更新。
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Tabs, Descriptions, Tag, Spin, Button, Timeline, Modal, Form,
  Input, DatePicker, Select, Popconfirm, Checkbox, message, Empty, Alert } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import moment from 'moment';
import { AuthButton } from 'components';
import { history } from 'libs';
import store from './faultStore';
import FaultStatusTag from './FaultStatusTag';
import { LEDGER_TYPE_PATH } from './ledger/constants';
import {
  PERM, FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR,
  FAULT_PROGRESS_TYPE_OPTIONS,
} from './constants';

const {TextArea} = Input;
const {TabPane} = Tabs;

@observer
class FaultDetail extends React.Component {
  // 详情与处理进展请求由 store.showDetail 统一发起，挂载时不再重复请求

  // 区块标题：三区块与处理概览共用（沿用页面内联样式，不新增全局样式）
  renderSectionTitle(text, style) {
    return <div style={{fontWeight: 600, marginBottom: 8, ...style}}>{text}</div>;
  }

  // 处置结果区块（2026-10 字段合并）：沿用原布局——原因分析第一行，
  // 恢复结果（恢复时间/恢复确认人/结案说明）在其后——已关闭时原因分析
  // 即展示"最终原因"，不另设"最终原因分析"重复行；恢复确认信息与最终
  // 结果两字段已合并为结案说明（recovery_close_note），详情不再展示两个
  // 旧字段。处置中未结案时以简洁提示代替成排"-"字段；已撤销记录没有
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
          {/* 原因分析状态化（2026-10）：按数据状态展示尚未分析/初步判断/
              最终原因/原因未明，处置中可直接补充或修改（不再只显示"-"）；
              已关闭展示"最终原因：…"，即最终原因分析，不重复另设一行 */}
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
                {d.recovered_by_name ? `${d.recovered_by_name}（${d.recovered_confirmed_at || ''}）` : '-'}
              </Descriptions.Item>
              {/* 结案说明（2026-10 字段合并）：与结案弹窗提交内容一致
                  （recovery_close_note 同源） */}
              <Descriptions.Item label="结案说明" span={2}>
                {d.recovery_close_note || '-'}
              </Descriptions.Item>
            </React.Fragment>
          )}
        </Descriptions>
      </React.Fragment>
    );
  }

  // 基本信息（2026-10 重组为三区块）：故障概况 / 处置结果 / 来源与登记。
  // 故障编号、当前状态、系统影响程度只在标题区展示一次，区块内不再重复。
  renderBasic() {
    const d = store.detail;
    // 处置中是唯一进行态：原因分析补充/修改入口仅此时展示（与状态按钮同口径）
    const editable = d.status === 'handling';
    return (
      <div>
        {this.renderSectionTitle('故障概况')}
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="故障系统">{d.system_name}</Descriptions.Item>
          <Descriptions.Item label="安装地点">{d.system_location || '-'}</Descriptions.Item>
          {/* 展示顺序与新增/编辑表单一致：故障部位/设备位于故障现象之前；
              对象型号/序列号/组成项为精简前的存量快照，仅展示 */}
          <Descriptions.Item label="发生时间" span={2}>{d.occurred_at}</Descriptions.Item>
          <Descriptions.Item label="故障部位/设备" span={2}>
            {[d.fault_object_name, d.fault_object_model, d.fault_object_sn]
              .filter(Boolean).join(' / ') || '-'}
            {d.fault_component_name ? `（组成项：${d.fault_component_name}）` : ''}
          </Descriptions.Item>
          <Descriptions.Item label="故障现象" span={2}>{d.phenomenon}</Descriptions.Item>
        </Descriptions>
        {this.renderResultSection(editable)}
        {/* 已撤销记录：撤销原因/撤销时间/撤销人（后端详情接口返回，
            历史撤销数据由迁移回填），仅供历史追溯 */}
        {d.status === 'cancelled' && this.renderCancelSection()}
        {this.renderSectionTitle('来源与登记', {marginTop: 16})}
        <Descriptions bordered size="small" column={2}>
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
          {/* 运行记录转故障（2026-10）：正式外键双向追溯，跳回运行记录详情 */}
          {d.source_type === 'runtime_record' && d.source_runtime_record && (
            <Descriptions.Item label="来源运行记录" span={2}>
              <Button
                type="link"
                size="small"
                style={{padding: 0}}
                onClick={() => {
                  store.closeDetail();
                  history.push(`/el/runtime-records?detail=${d.source_runtime_record}`);
                }}
              >
                {d.source_runtime_record_no || '查看来源运行记录'}
              </Button>
            </Descriptions.Item>
          )}
          {/* 创建人字段已从前端删除；登记时间即记录创建时间（后端字段保留，
              仅展示口径改为"登记"） */}
          <Descriptions.Item label="故障登记人">{d.registrar_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="登记时间">{d.created_at}</Descriptions.Item>
        </Descriptions>
        {this.renderHandlingOverview()}
      </div>
    );
  }

  // 撤销登记区块（2026-10-03）：已撤销记录回显撤销原因/时间/人，
  // 说明这条登记本身不再作为有效故障，历史记录保留可追溯。
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

  // 处理概览（2026-10）：基本信息页签底部的只读紧凑信息条（非边框表格）。
  // 条数/最近更新/最后记录取后端详情接口聚合统计的
  // handling_record_count / latest_handled_at / latest_handling_content，
  // 不在前端逐条请求处理进展，也不提供可编辑的"节点数"字段；
  // 完整时间线仍在"处理进展"页签，条数与"查看全部进展"只切换页签。
  renderHandlingOverview() {
    const d = store.detail;
    const count = d.handling_record_count ?? 0;
    const goToHandling = () => store.setActiveTab('handling');
    return (
      <div style={{marginTop: 16}}>
        {this.renderSectionTitle('处理概览')}
        {count > 0 ? (
          <div style={{fontSize: 13}}>
            <a onClick={goToHandling}>处理进展 {count} 条</a>
            <span style={{marginLeft: 16}}>最近更新：{d.latest_handled_at || '-'}</span>
            <span style={{marginLeft: 16}}>最后记录：{d.latest_handling_content || '-'}</span>
            <Button type="link" style={{padding: 0, marginLeft: 16}} onClick={goToHandling}>
              查看全部进展
            </Button>
          </div>
        ) : (
          <div style={{color: 'rgba(0, 0, 0, 0.45)'}}>暂无处理进展</div>
        )}
      </div>
    );
  }

  renderTitle() {
    const d = store.detail;
    // 标题区只保留故障编号、当前状态与系统影响程度（2026-10）：故障系统/
    // 安装地点/发生时间/登记人只在基本信息对应区块展示，不再重复；
    // 已撤销状态使用虚线灰标签（FaultStatusTag），明显区别于其他状态。
    return (
      <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap'}}>
        <span
          title={d.fault_no}
          style={{
            fontSize: 16, fontWeight: 600, marginRight: 8, maxWidth: 420,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}
        >
          {d.fault_no || '故障详情'}
        </span>
        <FaultStatusTag status={d.status}/>
        {d.affects_system_operation ? (
          <Tag color={FAULT_IMPACT_COLOR[d.impact_status]}>
            {FAULT_IMPACT_TEXT[d.impact_status]}
          </Tag>
        ) : (
          // 部件故障/离线维修：不影响系统对外服务，独立于系统运行状态展示
          <Tag>不影响运行</Tag>
        )}
      </div>
    );
  }

  render() {
    const d = store.detail;
    // 处置中是唯一进行态：编辑/进展/撤销登记/确认恢复并结案仅此时可用
    // （closed 终态、cancelled 已撤销均封闭；旧 pending/recovered 已删除）
    const editable = d.status === 'handling';
    // 页签实时显示处理进展条数（store.showDetail 打开详情时即统一拉取进展列表）；
    // 列表加载中不显示数字，避免闪现误导性的（0）
    const handlingTab = store.isHandlingFetching
      ? '处理进展'
      : `处理进展（${store.handlingTotal}）`;
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
            {/* 2026-10 流程简化：无"开始处置"步骤（新建即处置中）；
                确认恢复与关闭故障合并为一次"确认恢复并结案"操作 */}
            {editable && (
              <AuthRecoverAndCloseButton fault={d}/>
            )}
            {editable && (
              <AuthCancelButton fault={d}/>
            )}
          </div>
          {/* 页签受控（store.activeTab）：列表"处理进展"列点击 /
              基本信息"查看全部进展"均可直达处理进展页签，不重复开新窗口 */}
          <Tabs activeKey={store.activeTab} onChange={(key) => store.setActiveTab(key)}>
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            <TabPane tab={handlingTab} key="handling">
              <HandlingTimeline editable={editable}/>
            </TabPane>
          </Tabs>
        </Spin>
      </Modal>
    );
  }
}

// 确认恢复并结案（2026-10 流程合并）：原"确认恢复"与"关闭故障"两步合并。
// 合并操作须同时具备恢复确认与结案两项权限（AuthButton 以 & 表达 AND，
// 后端独立校验，不因按钮合并放宽权限边界）。
function AuthRecoverAndCloseButton({fault}) {
  const [visible, setVisible] = useState(false);
  const [form] = Form.useForm();
  return (
    <span>
      <AuthButton
        auth={`${PERM.FAULT_RECOVER}&${PERM.FAULT_CLOSE}`}
        type="primary"
        onClick={() => setVisible(true)}
      >
        确认恢复并结案
      </AuthButton>
      <RecoverModal visible={visible} form={form} fault={fault}
        onClose={() => setVisible(false)}/>
    </span>
  );
}

// 撤销故障登记（2026-10-03 由"作废"改称）：用于撤销错误或重复的故障登记。
// 二次确认弹窗明确说明操作后果（不删除历史记录、退出有效统计与健康计算、
// 原因必填），展示故障编号防误操作；撤销原因多行输入；成功提示等待后端
// 真实成功结果（业务错误由 http 拦截器统一弹出，不乐观更新）。
const AuthCancelButton = observer(function AuthCancelButton({fault}) {
  const [visible, setVisible] = useState(false);
  const [reason, setReason] = useState('');
  return (
    <span style={{marginLeft: 8}}>
      <AuthButton auth={PERM.FAULT_DEL} danger onClick={() => setVisible(true)}>
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
          store.cancelFault({cancel_reason: reason.trim()})
            .then(() => {
              message.success('故障登记已撤销');
              setVisible(false);
            })
            .catch(() => {});
        }}
      >
        <p style={{marginTop: 0}}>
          确定撤销故障登记「{fault.fault_no}」吗？
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
          placeholder="请填写撤销原因（必填），如：误报、重复登记、系统/现象填写有误需重新登记"
        />
      </Modal>
    </span>
  );
});

// 原因分析单元格（2026-10 状态化）：不再只在为空时显示"-"，按数据状态
// 明确告知当前状态——未填写显示"尚未分析"；已填写且处置中显示
// "初步判断：{内容}"；已关闭显示"最终原因：{内容}"（终态只读）；
// 原因未明显示"原因未明：{未明说明}"。处置中且具备 fault.edit 权限时提供
// "补充原因分析/修改"按钮，打开只处理原因分析的专用弹窗（不经列表编辑）。
// 历史故障无原因分析时同样显示"尚未分析"，不报错、不提供编辑入口（终态）。
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
          auth={PERM.FAULT_EDIT}
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

// 原因分析专用弹窗（2026-10）：只处理原因分析，不要求再次填写系统、发生
// 时间、故障现象等无关字段。打开时回填当前值；"确实无法确定原因"勾选后
// 切换为必填"未明说明"（不强迫用户填写虚假原因，也不接受无说明的未明）；
// 保存走专用端点并静默刷新详情，成功提示等待真实成功结果（业务错误由
// http 拦截器统一弹出，此处不重复提示）。
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
        原因分析是当前阶段的原因结论；排查过程与依据请通过"处理进展-故障定位"记录。
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

// 确认恢复并结案弹窗：恢复时间/恢复确认人/最终原因分析（或未明说明）/
// 结案说明一次填写一次校验，提交后故障直接进入终态"已关闭"。
// 结案说明（recovery_close_note）为唯一结案说明字段（2026-10 字段合并）：
// 一次性说明采取的处理措施、恢复验证依据与最终处理结果，位于最终原因
// 分析之下；原"恢复确认信息"/"最终结果"两个输入框已删除；最终原因分析
// 保持独立语义（说明根因或原因未明依据），不与结案说明合并。
// 存量恢复数据（历史合并迁移回填或旧流程遗留）打开时预填既有说明，
// 重新确认后结案；destroyOnClose 保证每次打开取最新详情。
const RecoverModal = observer(function RecoverModal({visible, form, fault, onClose}) {
  const initialValues = {
    // 恢复时间默认当前时间（存量数据预填既有恢复时间），可修改
    recovered_at: fault.recovered_at
      ? moment(fault.recovered_at, 'YYYY-MM-DD HH:mm') : moment(),
    // 恢复确认人：手动输入姓名（输入后回车确认，可多个，顿号分隔提交），
    // 只表示实际确认恢复的人；必填、不预填登录账号，与登录账号审计字段独立
    recovered_by_names: fault.recovered_by_name
      ? fault.recovered_by_name.split('、').filter(Boolean) : [],
    recovery_close_note: fault.recovery_close_note || '',
    // 最终原因分析（2026-10）：默认回填详情中的原因分析，结案前可修改；
    // 原因未明勾选同步回填（存量未明数据结案时保持未明口径）
    reason_analysis: fault.reason_analysis || '',
    reason_unknown: !!fault.reason_unknown,
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
            // 最终原因分析随结案提交保存（后端独立校验未明必填说明）
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
        提交后故障直接进入"已关闭"终态，不可再编辑或追加处理进展。
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
          {/* open=false：仅手输姓名（回车/失焦添加），与故障登记人输入一致 */}
          <Select
            mode="tags"
            open={false}
            placeholder="输入姓名后回车确认（可多个）"
          />
        </Form.Item>
        {/* 最终原因分析（2026-10）：默认回填处置中的原因分析，结案前可修改；
            勾选"原因未明"时切换为必填未明说明，不强迫填写虚假原因；
            提交后保存为最终原因，已关闭后原因分析只读 */}
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
        {/* 结案说明（2026-10 字段合并）：置于最终原因分析之下，必填且不能
            只填空格（whitespace 校验 + 提交 trim），替代原恢复确认信息/
            最终结果两框；与最终原因分析语义独立（说明怎么处理/如何验证/
            结果如何，不写根因） */}
        <Form.Item
          name="recovery_close_note"
          label="结案说明"
          rules={[{required: true, whitespace: true, message: '请填写结案说明'}]}
        >
          <TextArea
            rows={3}
            placeholder="请说明采取的处理措施、恢复验证依据及最终结果，如：更换电源模块后设备重启，连续观察30分钟无异常，业务访问正常，故障已恢复"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
});

// observer 必须包裹：时间线读取 handlingRecords/isHandlingFetching，
// 未包裹时这两项变化不触发重渲染——添加进展后新记录不显示、Spin 状态冻结
const HandlingTimeline = observer(function HandlingTimeline({editable}) {
  return (
    <div>
      <p style={{color: '#999', marginTop: 0}}>
        处理进展记录故障的整体跟进（检查、故障定位、本方处理、送厂、厂家反馈、
        返还、测试、持续观察等）；"故障定位"记录原因判断的依据与过程，
        原因结论请在基本信息"原因分析"中维护；无需再另行生成维修工单。
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
                  {/* 本次工时录入已删除（2026-10）：仅存量记录仍只读展示工时，
                      新增/更正不再携带该字段（后端 PUT 未提交时保留原值） */}
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
            placeholder="选填：检查 / 故障定位 / 本方处理 / 送厂 / 厂家反馈 / 返还 / 测试 / 持续观察 / 其他"
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

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 生成本期应填台账弹窗（2026-10-14 重构原"一键新增"弹窗）。
 *
 * - 打开即拉取后端预览：逐模板展示 模板路线/模板名称/适用系统/生成周期/
 *   具体期次/将使用的版本，并汇总 将新建/已存在跳过/缺少可用版本/需人工
 *   处理 的数量与原因；每周模板期次显示完整起止日期（周一~周日，跨月周
 *   归入周一所在月份）；
 * - 2026-10-21 数字表单路线并入生成：预览条目含 template_kind（excel/
 *   form），行键为 kind+id 组合（两条路线模板主键分属不同表可能撞号），
 *   确认时提交 template_ids + template_kinds 平行数组；
 * - 确认后按预览口径重新计算并创建缺项，结果如实展示实际新增/跳过/
 *   未处理（不以预览数量冒充实际结果），成功后刷新当前填写列表；
 * - 已作废台账不在一键生成中重建（预览标记需人工处理，行内提供"补建"
 *   明确补建操作，2026-10-16）；未配置适用系统/生成周期的模板标记
 *   待配置（在对应模板管理页配置）；
 * - antd 4.21.5：Modal 用 visible；错误提示由 http 拦截器统一弹出。
 * - 2026-10-27 修复：预览区抽出组件必须 observer（Table 的 loading 直读
 *   store.isGenerateFetching，非 observer 时预览到达后无人再追踪该值，
 *   转圈永久残留）；判定表定宽列合计超出弹窗内容区，加 scroll.x + fixed
 *   布局并给"模板名称"定宽，否则该列被自动布局压缩成 0 宽整列消失。
 */
import React, {useEffect, useRef, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Checkbox, Modal, Table, Tag} from 'antd';
import {AuthButton} from 'components';
import {LEDGER_TYPE_TEXT, PERM_L} from './constants';
import {TEMPLATE_KIND_TEXT} from './form/constants';

/** 预览行键：路线+模板主键（两条路线模板主键分属不同表，可能撞号）。 */
export function entryKeyOf(entry) {
  return `${entry.template_kind || 'excel'}-${entry.template_id}`;
}

const GENERATE_STATUS = {
  create: {text: '将新建', color: 'processing'},
  exists: {text: '已存在跳过', color: 'default'},
  no_version: {text: '缺少可用版本', color: 'warning'},
  manual_needed: {text: '需人工处理', color: 'error'},
};

function SummaryCounts({summary}) {
  if (!summary) return null;
  const items = [
    ['create', '将新建'],
    ['exists', '已存在跳过'],
    ['no_version', '缺少可用版本'],
    ['manual_needed', '需人工处理'],
  ];
  return (
    <div style={{display: 'flex', gap: 24, marginBottom: 12}}>
      {items.map(([key, label]) => (
        <span key={key}>
          <span style={{fontSize: 20, fontWeight: 600,
                        color: summary[key] ? '#1890ff' : '#999'}}>{summary[key] || 0}</span>
          <span style={{marginLeft: 4, color: '#666'}}>{label}</span>
        </span>
      ))}
    </div>
  );
}

/** 生成结果区（实际新增/跳过/未处理如实展示；自弹窗函数体抽出）。 */
function ResultSection({result}) {
  return (
    <React.Fragment>
      <Alert
        type={result.created.length ? 'success' : 'info'}
        showIcon
        style={{marginBottom: 12}}
        message={`实际新增 ${result.created.length} 张，已存在跳过 ${result.skipped.length} 张，未处理 ${result.failed.length} 项`}
        description={result.failed.length
          ? result.failed.map(item => `${item.template_name}：${item.reason}`).join('；')
          : undefined}/>
      {result.created.length > 0 && (
        <div style={{color: '#666', marginBottom: 8}}>
          新增台账：{result.created.map(item => item.ledger_no).join('、')}
          （已回到填写列表，点击详情即可填写）
        </div>
      )}
    </React.Fragment>
  );
}

/** 预览判定表总宽：勾选列 + 各定宽列之和（与 buildPreviewColumns 保持一致）。 */
const PERIOD_PREVIEW_SCROLL_X = 32 + 90 + 160 + 150 + 80 + 190 + 80 + 300;

/** 预览区（路线提示 + 判定表；自弹窗函数体抽出）。
 *
 * 必须保持 observer：Table 的 loading 直读 store.isGenerateFetching，而父组件
 * 的 `{!preview && store.isGenerateFetching && ...}` 在预览到达后短路、不再
 * 追踪该 observable——非 observer 时预览渲染发生在 spinner 复位之前，此后
 * 无任何 observer 追踪它，转圈将永久残留（2026-10-27 修复）。
 * 判定表定宽列合计超出弹窗内容区，须 scroll.x + fixed 布局兜底，否则唯一
 * 无宽度的"模板名称"列会被自动布局压缩成 0 宽整列消失（同日修复）；
 * "判定"列 fixed:right，横向滚动时判定与原因始终可见。 */
const PreviewSection = observer(function PreviewSection({preview, rowSelection, columns, store}) {
  return (
    <React.Fragment>
      <Alert
        type="info"
        showIcon
        style={{marginBottom: 12}}
        message="将按各模板配置的适用系统与生成周期，生成本期（当前周/月/航季）应填台账"
        description="Excel 模板生成 Excel 台账、数字表单模板生成表单台账（均固定引用最新发布版本），可直接填写。"/>
      <Table
        rowKey={entryKeyOf}
        rowSelection={rowSelection}
        size="small"
        loading={store.isGenerateFetching}
        dataSource={preview.entries}
        columns={columns}
        scroll={{x: PERIOD_PREVIEW_SCROLL_X}}
        pagination={false}/>
    </React.Fragment>
  );
});

/** 预览判定表列定义（路线/模板/系统/周期/期次/版本/判定+补建）。 */
function buildPreviewColumns(handleRebuild, isGenerating) {
  return [
    {title: '模板路线', key: 'kind', width: 90,
     render: (v, entry) => (
       <Tag color={entry.template_kind === 'form' ? 'purple' : 'blue'}>
         {TEMPLATE_KIND_TEXT[entry.template_kind || 'excel']}
       </Tag>
     )},
    {title: '模板名称', dataIndex: 'template_name', width: 160, ellipsis: true},
    {title: '适用系统', key: 'system', width: 150, ellipsis: true,
     render: (v, entry) => entry.system_name
       ? `${entry.system_name}（${entry.system_code}）`
       : <Tag>待配置</Tag>},
    {title: '生成周期', dataIndex: 'generation_period_text', width: 80},
    {title: '本期期次', key: 'period', width: 190,
     render: (v, entry) => entry.period_text || '—'},
    {title: '使用版本', key: 'version', width: 80, align: 'center',
     render: (v, entry) => entry.version_no ? `v${entry.version_no}` : '—'},
    {title: '判定', key: 'status', width: 300, fixed: 'right',
     render: (v, entry) => {
       const conf = GENERATE_STATUS[entry.status] || {text: entry.status};
       return (
         <span>
           <Tag color={conf.color}>{conf.text}</Tag>
           {entry.reason && (
             <span style={{color: '#999', fontSize: 12}}>{entry.reason}</span>
           )}
           {entry.rebuildable && (
             <AuthButton
               auth={PERM_L.LED_ADD}
               data-testid="period-rebuild"
               type="link" size="small"
               disabled={isGenerating}
               onClick={() => handleRebuild(entry)}>
               补建
             </AuthButton>
           )}
         </span>
       );
     }},
  ];
}

/** 预览到达后自动勾选"将新建"条目（每条只勾一次，重拉预览不重复加入）。 */
function useAutoSelectCreateEntries(visible, preview, initializedRef, setSelected) {
  React.useEffect(() => {
    if (!visible || !preview || !preview.entries) return;
    const newKeys = [];
    preview.entries.forEach(entry => {
      const key = entryKeyOf(entry);
      if (entry.status === 'create'
          && !initializedRef.current.has(key)) {
        initializedRef.current.add(key);
        newKeys.push(key);
      }
    });
    if (newKeys.length) {
      setSelected(current => Array.from(new Set([...current, ...newKeys])));
    }
  }, [visible, preview]);
}

function LedgerPeriodGenerateModal({visible, ledgerType, store, onCancel}) {
  const preview = store.generatePreview;
  const isSeasonal = ledgerType === 'seasonal';
  const [maintenanceCycles, setMaintenanceCycles] = useState(
    isSeasonal ? ['seasonal'] : ['weekly']);
  const [selectedTemplateIds, setSelectedTemplateIds] = useState([]);
  const initializedTemplateIds = useRef(new Set());

  useEffect(() => {
    if (visible) {
      const initialCycles = isSeasonal ? ['seasonal'] : ['weekly'];
      setMaintenanceCycles(initialCycles);
      setSelectedTemplateIds([]);
      initializedTemplateIds.current = new Set();
      store.fetchGeneratePreview(ledgerType, initialCycles);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  useAutoSelectCreateEntries(visible, preview, initializedTemplateIds, setSelectedTemplateIds);

  const handleGenerate = () => {
    const eligible = (preview && preview.entries || [])
      .filter(entry => entry.status === 'create'
        && selectedTemplateIds.includes(entryKeyOf(entry)));
    store.generatePeriodLedgers(
      ledgerType, maintenanceCycles,
      eligible.map(entry => entry.template_id),
      eligible.map(entry => entry.template_kind || 'excel'))
      .catch(() => {});
  };

  const handleCyclesChange = (cycles) => {
    setMaintenanceCycles(cycles);
    if (cycles.length) {
      store.fetchGeneratePreview(ledgerType, cycles);
    } else {
      store.generatePreview = null;
      store.generatePeriodResult = null;
    }
  };

  /** 明确补建（已作废占用的本期槽位）：成功后重拉预览刷新判定结果。 */
  const handleRebuild = (entry) => {
    store.rebuildPeriodLedger(entry.template_id, entry.template_kind || 'excel')
      .then(() => store.fetchGeneratePreview(ledgerType, maintenanceCycles))
      .catch(() => {});
  };

  const eligibleEntries = (preview && preview.entries || [])
    .filter(entry => entry.status === 'create');
  const selectedCount = eligibleEntries.filter(
    entry => selectedTemplateIds.includes(entryKeyOf(entry))).length;
  const rowSelection = {
    selectedRowKeys: selectedTemplateIds,
    onChange: keys => setSelectedTemplateIds(keys),
    getCheckboxProps: entry => ({disabled: entry.status !== 'create'}),
  };

  const columns = buildPreviewColumns(handleRebuild, store.isGenerating);

  const result = store.generatePeriodResult;
  const periodLabels = (preview && preview.period_labels) || {};
  const cycleOptions = isSeasonal ? [] : [
    {value: 'weekly', label: `周维护（本周 ${periodLabels.weekly || ''}）`},
    {value: 'monthly', label: `月维护（${periodLabels.monthly || ''}）`},
  ];

  return (
    <Modal
      title={`生成本期应填${LEDGER_TYPE_TEXT[ledgerType] || ''}台账`}
      visible={visible}
      confirmLoading={store.isGenerating}
      onOk={handleGenerate}
      onCancel={onCancel}
      okText={`确认生成（${selectedCount}项）`}
      okButtonProps={{disabled: !preview || !maintenanceCycles.length
        || selectedCount === 0}}
      cancelText={result ? '关闭' : '取消'}
      width={1160}
      destroyOnClose>
      <div data-testid="period-generate-body">
        {!preview && store.isGenerateFetching && <Alert type="info" showIcon message="正在获取本期应填台账预览..."/>}
        {!isSeasonal && !maintenanceCycles.length && (
          <Alert type="warning" showIcon message="请至少选择一个维护周期"/>
        )}
        {!isSeasonal && (
          <div style={{marginBottom: 12}}>
            <div style={{fontWeight: 600, marginBottom: 6}}>维护周期</div>
            <Checkbox.Group
              options={cycleOptions}
              value={maintenanceCycles}
              onChange={handleCyclesChange}/>
          </div>
        )}
        {preview && (
          <React.Fragment>
            <SummaryCounts summary={preview.summary}/>
            {result ? (
              <ResultSection result={result}/>
            ) : (
              <PreviewSection
                preview={preview} rowSelection={rowSelection}
                columns={columns} store={store}/>
            )}
          </React.Fragment>
        )}
      </div>
    </Modal>
  );
}

export default observer(LedgerPeriodGenerateModal);

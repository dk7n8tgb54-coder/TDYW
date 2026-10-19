/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 生成本期应填台账弹窗（2026-10-14 重构原"一键新增"弹窗）。
 *
 * - 打开即拉取后端预览：逐模板展示 模板名称/适用系统/生成周期/具体期次/
 *   将使用的版本，并汇总 将新建/已存在跳过/缺少可用版本/需人工处理 的
 *   数量与原因；每周模板期次显示完整起止日期（周一~周日，跨月周归入
 *   周一所在月份）；
 * - 确认后按预览口径重新计算并创建缺项，结果如实展示实际新增/跳过/
 *   未处理（不以预览数量冒充实际结果），成功后刷新当前填写列表；
 * - 已作废台账不在一键生成中重建（预览标记需人工处理，行内提供"补建"
 *   明确补建操作，2026-10-16）；未配置适用系统/生成周期的历史模板标记
 *   待配置（在 Excel 模板管理页配置）；
 * - antd 4.21.5：Modal 用 visible；错误提示由 http 拦截器统一弹出。
 */
import React, {useEffect} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Modal, Table, Tag} from 'antd';
import {AuthButton} from 'components';
import {LEDGER_TYPE_TEXT, PERM_L} from './constants';

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

function LedgerPeriodGenerateModal({visible, ledgerType, store, onCancel}) {
  const preview = store.generatePreview;

  useEffect(() => {
    if (visible) {
      store.fetchGeneratePreview(ledgerType);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const handleGenerate = () => {
    store.generatePeriodLedgers(ledgerType).catch(() => {});
  };

  /** 明确补建（已作废占用的本期槽位）：成功后重拉预览刷新判定结果。 */
  const handleRebuild = (entry) => {
    store.rebuildPeriodLedger(entry.template_id, ledgerType)
      .then(() => store.fetchGeneratePreview(ledgerType))
      .catch(() => {});
  };

  const columns = [
    {title: '模板名称', dataIndex: 'template_name', ellipsis: true},
    {title: '适用系统', key: 'system', width: 150, ellipsis: true,
     render: (v, entry) => entry.system_name
       ? `${entry.system_name}（${entry.system_code}）`
       : <Tag>待配置</Tag>},
    {title: '生成周期', dataIndex: 'generation_period_text', width: 80},
    {title: '本期期次', key: 'period', width: 190,
     render: (v, entry) => entry.period_text || '—'},
    {title: '使用版本', key: 'version', width: 80, align: 'center',
     render: (v, entry) => entry.version_no ? `v${entry.version_no}` : '—'},
    {title: '判定', key: 'status', width: 300,
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
               disabled={store.isGenerating}
               onClick={() => handleRebuild(entry)}>
               补建
             </AuthButton>
           )}
         </span>
       );
     }},
  ];

  const result = store.generatePeriodResult;

  return (
    <Modal
      title={`生成本期应填${LEDGER_TYPE_TEXT[ledgerType] || ''}台账`}
      visible={visible}
      confirmLoading={store.isGenerating}
      onOk={handleGenerate}
      onCancel={onCancel}
      okText="确认生成"
      okButtonProps={{disabled: !preview || !preview.summary
        || preview.summary.create === 0}}
      cancelText={result ? '关闭' : '取消'}
      width={860}
      destroyOnClose>
      <div data-testid="period-generate-body">
        {!preview && store.isGenerateFetching && <Alert type="info" showIcon message="正在获取本期应填台账预览..."/>}
        {preview && (
          <React.Fragment>
            <SummaryCounts summary={preview.summary}/>
            {result ? (
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
            ) : (
              <React.Fragment>
                <Alert
                  type="info"
                  showIcon
                  style={{marginBottom: 12}}
                  message="将按各模板配置的适用系统与生成周期，生成本期（当前周/月/航季）应填台账"
                  description="生成的台账为 Excel 模板台账（固定引用最新发布版本），可直接填写。"/>
                <Table
                  rowKey="template_id"
                  size="small"
                  loading={store.isGenerateFetching}
                  dataSource={preview.entries}
                  columns={columns}
                  pagination={false}/>
              </React.Fragment>
            )}
          </React.Fragment>
        )}
      </div>
    </Modal>
  );
}

export default observer(LedgerPeriodGenerateModal);

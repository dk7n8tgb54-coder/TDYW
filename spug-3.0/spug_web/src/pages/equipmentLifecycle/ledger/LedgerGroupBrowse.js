/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 模板组"翻阅台账"视图（2026-10-18）：网页内像翻同一本纸质台账一样连续
 * 查看某个模板的历次记录。
 *
 * - 数据来自 store.openBrowse 拉取的后端翻阅清单（筛选与组内列表同口径：
 *   默认不含已作废，显式筛选"已作废/全部"时按该范围；期次起始日期升序，
 *   无期次标记的历史台账回退执行日期、ID 兜底稳定；同一期次补建并存的
 *   多张全部保留）。翻页在该清单内移动，不受组内列表分页限制；
 * - 每张台账复用 ExcelLedgerDetail（创建时固定引用的模板版本快照回放，
 *   不受模板改名/更新版本/停用影响；草稿可继续填写，导出等能力不变）。
 *   台账内无工作表切换概念（绑定限主工作表），翻页按钮明确命名为
 *   "上一张台账/下一张台账"，与台账内容查看区分；
 * - 未保存拦截：草稿/更正存在未保存修改时，切换台账、期次跳转、退出
 *   翻阅均先确认，选择"继续填写"保留当前内容；只读台账直接翻阅；
 * - 顶栏（窄屏自动换行）：退出翻阅/上一张/下一张/第几张共几张/模板名称/
 *   当前期次/状态/期次跳转；首张与末张时对应按钮禁用。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Empty, Modal, Select, Space, Spin, Tag} from 'antd';
import {ArrowLeftOutlined, ArrowRightOutlined} from '@ant-design/icons';
import ExcelLedgerDetail from './excel/ExcelLedgerDetail';
import {ExcelLedgerStore} from './excel/excelLedgerStore';
import {STATUS_COLOR, STATUS_TEXT} from './constants';

// 期次跳转里"未标注期次"的选项键（period_key 为空的条目归并为一组）
const UNMARKED_PERIOD_KEY = '__unmarked__';

/** 期次跳转选项：按清单顺序归并同期条目（index=该期次第一张的下标）。 */
function buildPeriodOptions(entries) {
  const seen = new Map();
  entries.forEach((item, index) => {
    const key = item.period_key || UNMARKED_PERIOD_KEY;
    if (seen.has(key)) {
      seen.get(key).count += 1;
    } else {
      seen.set(key, {key, index, label: item.period_label, count: 1});
    }
  });
  return Array.from(seen.values());
}

/** 期次跳转下拉：选项为期次标签+张数，选中跳到该期次第一张。 */
function PeriodJumpSelect({options, value, onSelect}) {
  return (
    <Select
      data-testid="browse-period-jump"
      style={{minWidth: 240, maxWidth: 360}}
      value={value}
      placeholder="跳转到期次"
      onChange={onSelect}>
      {options.map(option => (
        <Select.Option key={option.key} value={option.key}>
          {option.label}（{option.count}张）
        </Select.Option>
      ))}
    </Select>
  );
}

/** 翻阅主体：空态 / 详情加载态与失败重试 / 台账详情（版本快照回放）。
 * ExcelLedgerDetail 的"返回列表"经 onDetailBack 直接退出翻阅（其内部
 * 已做未保存确认）。 */
function BrowseBody({entries, excelStore, detail, loadError, onRetry, onDetailBack}) {
  if (entries.length === 0) {
    return <Empty description="当前筛选范围内没有可翻阅的台账"/>;
  }
  if (!detail) {
    return (
      <div style={{textAlign: 'center', padding: '80px 0'}}>
        {loadError ? (
          <Space direction="vertical" size={12}>
            <Alert type="warning" showIcon
                   message="台账详情加载失败"
                   description="请重试，或退出翻阅后重新进入。"/>
            <Button data-testid="browse-retry" onClick={onRetry}>重试</Button>
          </Space>
        ) : (
          <Spin tip="正在加载台账..."/>
        )}
      </div>
    );
  }
  return <ExcelLedgerDetail store={excelStore} onBack={onDetailBack}/>;
}

function LedgerGroupBrowse({store}) {
  const [excelStore] = useState(() => new ExcelLedgerStore());
  const [loadError, setLoadError] = useState(false);
  const browse = store.browseState;
  const entries = browse ? browse.entries : [];
  const entry = browse && browse.index < entries.length
    ? entries[browse.index] : null;
  const detail = excelStore.detail;
  const currentId = entry ? entry.id : null;

  // 当前条目变化 → 拉取该台账详情（版本快照回放）；导航前已清空详情
  useEffect(() => {
    if (!currentId) return;
    if (detail && detail.id === currentId) return;
    setLoadError(false);
    excelStore.fetchDetail(currentId).catch(() => setLoadError(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  /** 未保存守卫：有未保存修改先确认（取消=继续填写保留内容）。 */
  const guardUnsaved = (proceed, actionText) => {
    if (!excelStore.hasUnsaved) {
      proceed();
      return;
    }
    Modal.confirm({
      title: '有未保存的修改',
      content: `${actionText}将放弃尚未保存的填写值，是否继续？`,
      okText: '放弃修改并继续',
      cancelText: '继续填写',
      onOk: () => {
        excelStore.applyDetail(null);
        proceed();
      },
    });
  };

  /** 退出翻阅（未加守卫版）：清详情 + 关翻阅 + 按进入层级刷新列表。 */
  const exitBrowse = () => {
    excelStore.applyDetail(null);
    store.closeBrowse();
    store.refresh();
  };

  const navigateTo = (index) => {
    if (!browse || index < 0 || index >= entries.length || index === browse.index) return;
    // 切换前清空详情：目标台账加载中以加载态呈现，不残留上一张内容
    guardUnsaved(() => {
      excelStore.applyDetail(null);
      store.setBrowseIndex(index);
    }, '切换到其他台账');
  };

  const handleExit = () => guardUnsaved(exitBrowse, '退出翻阅');

  const retryLoad = () => {
    setLoadError(false);
    excelStore.fetchDetail(currentId).catch(() => setLoadError(true));
  };

  const statusValue = detail ? detail.status : (entry ? entry.status : '');
  const periodOptions = buildPeriodOptions(entries);

  return (
    <div data-testid="ledger-group-browse">
      <div style={{
        display: 'flex', flexWrap: 'wrap', alignItems: 'center',
        gap: 8, marginBottom: 12,
      }}>
        <Button data-testid="browse-exit" icon={<ArrowLeftOutlined/>} onClick={handleExit}>
          退出翻阅
        </Button>
        <Button
          data-testid="browse-prev"
          icon={<ArrowLeftOutlined/>}
          disabled={!entry || browse.index <= 0}
          onClick={() => navigateTo(browse.index - 1)}>
          上一张台账
        </Button>
        <Button
          data-testid="browse-next"
          disabled={!entry || browse.index >= entries.length - 1}
          onClick={() => navigateTo(browse.index + 1)}>
          下一张台账 <ArrowRightOutlined/>
        </Button>
        <span data-testid="browse-counter" style={{whiteSpace: 'nowrap'}}>
          {entry ? `第 ${browse.index + 1} 张 / 共 ${entries.length} 张` : `共 ${entries.length} 张`}
        </span>
        <span style={{whiteSpace: 'nowrap'}}>
          模板：<strong>{browse ? browse.groupName : ''}</strong>
        </span>
        {entry && (
          <span data-testid="browse-period" style={{whiteSpace: 'nowrap'}}>
            期次：{entry.period_label}
          </span>
        )}
        {statusValue && (
          <Tag data-testid="browse-status" color={STATUS_COLOR[statusValue]}
               style={{marginRight: 0}}>
            {STATUS_TEXT[statusValue] || statusValue}
          </Tag>
        )}
        {entries.length > 0 && (
          <PeriodJumpSelect
            options={periodOptions}
            value={entry ? (entry.period_key || UNMARKED_PERIOD_KEY) : undefined}
            onSelect={key => {
              const option = periodOptions.find(item => item.key === key);
              if (option) navigateTo(option.index);
            }}/>
        )}
      </div>
      <BrowseBody
        entries={entries} excelStore={excelStore} detail={detail}
        loadError={loadError} onRetry={retryLoad} onDetailBack={exitBrowse}/>
    </div>
  );
}

export default observer(LedgerGroupBrowse);

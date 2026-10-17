/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行处置记录详情模块共享小工具（区块标题内联样式，不新增全局样式）。
 * 2026-10-15 起同时承载列表展示单元（状态/故障影响标签、标题、编号）：
 * 主列表与系统档案页签两个真实场景共用同一套展示规则，避免复制业务规则。
 */
import React from 'react';
import moment from 'moment';
import {Tag, Typography} from 'antd';
import {
  RECORD_STATUS_TEXT, RECORD_STATUS_COLOR,
  RECORD_TYPE_TEXT, RECORD_TYPE_COLOR,
  FAULT_IMPACT_TEXT, FAULT_IMPACT_COLOR,
} from '../constants';

// 进展条目的显示名随记录类型（详情页签/时间线标题/概览指称共用）：
// 一般记录=补充记录 / 异常事件=跟进记录 / 设备故障=处置记录；
// 异常事件在原记录认定为设备故障后随详情刷新自动切换。
// 类型未知（详情加载中）时由使用方回退通用名"处理进展"。
export const PROGRESS_TAB_TEXT = {
  routine: '补充记录',
  abnormal: '跟进记录',
  fault: '处置记录',
};

// ==================== 列表展示单元（主列表与系统页签共用） ====================

// 状态标签：已撤销使用虚线灰样式，与进行态明显区分
export function RecordStatusTag({status}) {
  if (status === 'cancelled') {
    return (
      <Tag
        color="default"
        style={{borderStyle: 'dashed', color: 'rgba(0, 0, 0, 0.45)'}}
      >
        {RECORD_STATUS_TEXT[status] || status}
      </Tag>
    );
  }
  return <Tag color={RECORD_STATUS_COLOR[status]}>{RECORD_STATUS_TEXT[status] || status}</Tag>;
}

// 设备故障影响程度并入状态列的规则：仅设备故障显示；影响运行时展示
// 程度标签（降级/故障/中断），否则展示中性"不影响运行"标签
export function FaultImpactTag({record}) {
  if (!record || record.record_type !== 'fault') return null;
  if (record.affects_system_operation) {
    return (
      <Tag color={FAULT_IMPACT_COLOR[record.impact_status]} style={{marginLeft: 4}}>
        {FAULT_IMPACT_TEXT[record.impact_status] || record.impact_status}
      </Tag>
    );
  }
  return <Tag style={{marginLeft: 4}}>不影响运行</Tag>;
}

// 标题单元格：前置记录类型标签，标题为主要入口点击打开统一详情；
// 长标题由列 ellipsis 截断，悬浮可见全文（native title）
export function RecordTitleCell({record, onOpen}) {
  return (
    <span>
      <Tag color={RECORD_TYPE_COLOR[record.record_type]} style={{marginRight: 4}}>
        {RECORD_TYPE_TEXT[record.record_type] || record.record_type}
      </Tag>
      <a onClick={() => onOpen(record)} title={record.title}>{record.title}</a>
    </span>
  );
}

// 编号单元格：一键复制（引用字段可查找、可复制）
export function RecordNoCell({value}) {
  return (
    <Typography.Text
      copyable={{tooltips: ['复制编号', '已复制']}}
      style={{maxWidth: 140}}
    >
      {value}
    </Typography.Text>
  );
}

// 区块标题（基本信息区块与进展工作区共用，与系统档案详情同款内联样式）
export function sectionTitle(text, style) {
  return <div style={{fontWeight: 600, marginBottom: 8, ...style}}>{text}</div>;
}

// 持续时间展示（后端 duration_seconds，秒）：口径为最新进展时间 - 发生时间，
// 无进展/负差值后端置空，这里显示"-"；0 显示"0分钟"；
// 不足 1 小时"35分钟"；不足 1 天"2小时15分钟"（整小时省略分钟）；
// 跨天"1天3小时"（天以上不再展示分钟）
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || seconds < 0) return '-';
  const totalMinutes = Math.floor(seconds / 60);
  if (totalMinutes < 60) return `${totalMinutes}分钟`;
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) {
    return hours > 0 ? `${days}天${hours}小时` : `${days}天`;
  }
  return minutes > 0 ? `${hours}小时${minutes}分钟` : `${hours}小时`;
}

// 恢复耗时（秒）= 恢复时间 - 发生时间（设备故障结案后的真实恢复耗时口径，
// 与"发生至最近进展"不同——后者只衡量到最近一条进展的时间跨度，不暗示恢复）。
// 时间缺失/非法/恢复早于发生（数据异常）返回 null，展示"-"
export function recoveryDurationSeconds(record) {
  if (!record || !record.occurred_at || !record.recovered_at) return null;
  const start = moment(record.occurred_at);
  const end = moment(record.recovered_at);
  if (!start.isValid() || !end.isValid()) return null;
  const seconds = (end - start) / 1000;
  return seconds >= 0 ? Math.round(seconds) : null;
}

// 详情"下一步"提示：按类型与状态给出当前最重要的动作指引（文案与详情页
// 实际可用动作一致，后端状态机为准）。已撤销记录由详情页既有的只读横幅
// 承载，这里不再重复提示
export function nextStepHint(record) {
  if (!record || !record.record_type) return null;
  const {record_type: type, status} = record;
  if (type === 'fault') {
    if (status === 'handling') {
      return '处置中：持续添加处置记录跟进进展；确认恢复后点击"确认恢复并结案"完成闭环。';
    }
    if (status === 'closed') return '已关闭归档：仅供查看，不能修改或追加进展。';
    return null;
  }
  if (type === 'abnormal') {
    if (status === 'recorded') {
      return '已记录：点击"添加跟进记录"开始跟进；如确认是设备故障，可"认定设备故障"。';
    }
    if (status === 'following_up') return '跟进中：持续跟进，完成后点击"完成跟进"。';
    if (status === 'completed') {
      return '已完成：如需继续跟进，追加一条跟进记录即可重新跟进。';
    }
    return null;
  }
  if (type === 'routine') {
    return '一般记录已留痕：可继续补充记录或上传附件，不进入故障流程。';
  }
  return null;
}

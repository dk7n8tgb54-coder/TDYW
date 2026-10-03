/**
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 升级存档打印工具（从 WorkbenchForm 抽出，纯函数无组件状态）。
 * - printUpgradeArchive：打印基本信息存档封面；
 * - printUpgradeSteps：打印步骤执行清单（可按阶段过滤）。
 * 打印窗口共用同一套 A4 纵向样式，编号（upgrade_no）随基本信息一并打印。
 */
import { message } from 'antd';
import { groupStepsByPhase } from './shared';

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const ARCHIVE_CSS = '@page { size: A4 portrait; margin: 15mm; } body { font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 13px; color: #000; margin: 0; } h1 { font-size: 22px; text-align: center; margin: 0 0 6px; } .subtitle { text-align: center; color: #666; font-size: 12px; margin-bottom: 20px; } table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid #000; padding: 8px 10px; text-align: left; } th { background: #f0f0f0; font-weight: bold; width: 130px; } .footer { margin-top: 28px; font-size: 11px; color: #666; text-align: right; border-top: 1px dashed #999; padding-top: 6px; } .no-print { text-align: center; margin-top: 20px; } .no-print button { padding: 6px 18px; margin: 0 6px; cursor: pointer; } @media print { .no-print { display: none; } }';

function openPrintWindow() {
  const win = window.open('', '_blank', 'width=900,height=700');
  if (!win) return null;
  win.focus();
  return win;
}

function schedulePrint(win) {
  setTimeout(() => { try { win.print(); } catch (e) {} }, 300);
}

/**
 * 打印基本信息存档封面（A4 纵向：基本信息表格 + 大段说明块）
 */
export function printUpgradeArchive(info) {
  const win = openPrintWindow();
  if (!win) { message.warning('请允许浏览器弹窗以打印基本信息'); return; }

  const fields = [
    ['编号', info.upgrade_no],
    ['标题', info.title],
    ['系统', info.system_name],
    ['升级类型', info.upgrade_type],
    ['负责人', info.owner],
    ['计划升级时间', info.upgrade_time],
    ['状态', info.status],
  ];
  const blocks = [
    ['升级内容', info.upgrade_content],
    ['影响范围', info.impact_scope],
    ['风险说明', info.risk_desc],
    ['回退方案摘要', info.rollback_plan],
  ];
  const rowsHtml = fields.map(([k, v]) =>
    `<tr><th>${k}</th><td>${escapeHtml(v || '-')}</td></tr>`
  ).join('');
  const blocksHtml = blocks.map(([k, v]) =>
    `<div style="margin-top:14px"><div style="font-weight:bold;border-bottom:1px solid #000;padding-bottom:4px">${k}</div><div style="padding:8px 4px;min-height:40px;white-space:pre-wrap;line-height:1.8">${escapeHtml(v || '（无）')}</div></div>`
  ).join('');

  win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>升级存档 - ${escapeHtml(info.title)}</title><style>${ARCHIVE_CSS}</style></head><body><h1>升级存档</h1><div class="subtitle">升级基本信息</div><table>${rowsHtml}</table>${blocksHtml}<div class="footer">打印时间：${new Date().toLocaleString()}</div><div class="no-print"><button onclick="window.print()">打印</button><button onclick="window.close()">关闭</button></div></body></html>`);
  win.document.close();
  schedulePrint(win);
  return true;
}

const STEPS_CSS = '@page { size: A4 portrait; margin: 15mm; } body { font-family: -apple-system, "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 12px; color: #000; margin: 0; } h1 { font-size: 18px; text-align: center; margin: 0 0 8px; } .meta { margin: 8px 0 12px; border-bottom: 2px solid #000; padding-bottom: 8px; } .meta div { display: inline-block; margin-right: 28px; line-height: 1.9; } .meta b { font-weight: bold; } table { width: 100%; border-collapse: collapse; margin-top: 4px; } th, td { border: 1px solid #000; padding: 8px; text-align: left; vertical-align: top; } th { background: #f0f0f0; font-weight: bold; text-align: center; font-size: 12px; } td { line-height: 28px; } .step-title { font-weight: bold; } .step-desc { font-size: 11px; color: #444; margin-top: 4px; line-height: 1.5; } .phase-section { margin-bottom: 16px; page-break-inside: avoid; } .phase-header { font-weight: bold; font-size: 13px; padding: 6px 8px; background: #fafafa; border: 1px solid #000; border-bottom: none; display: flex; justify-content: space-between; } .phase-check { font-weight: normal; font-size: 11px; } .sign { margin-top: 24px; font-size: 12px; } .sign div { display: inline-block; margin-right: 60px; } .footer { margin-top: 16px; font-size: 11px; color: #666; text-align: right; border-top: 1px dashed #999; padding-top: 6px; } .no-print { text-align: center; margin-top: 20px; } .no-print button { padding: 6px 18px; margin: 0 6px; cursor: pointer; } @media print { .no-print { display: none; } }';

function buildStepSection(title, steps) {
  const rows = steps.map((s, i) => {
    const desc = s.description || s.remark || '';
    return `<tr><td style="text-align:center">${s.sequence || i + 1}</td><td><div class="step-title">${escapeHtml(s.title)}</div>${desc ? `<div class="step-desc">${escapeHtml(desc)}</div>` : ''}</td><td style="text-align:center">☐</td><td></td></tr>`;
  }).join('');
  return `<div class="phase-section"><div class="phase-header">【${escapeHtml(title)}】 <span class="phase-check">阶段完成：☐</span></div><table><thead><tr><th style="width:40px">序号</th><th>步骤说明</th><th style="width:70px">执行情况</th><th style="width:120px">备注</th></tr></thead><tbody>${rows || '<tr><td colspan="4" style="text-align:center">暂无步骤</td></tr>'}</tbody></table></div>`;
}

/**
 * 打印步骤执行清单；phase 传空打印全部阶段（未分组单独成节）
 */
export function printUpgradeSteps({info, recordSteps, phases, phase}) {
  const win = openPrintWindow();
  if (!win) { message.warning('请允许浏览器弹窗以打印步骤清单'); return; }

  const steps = phase
    ? recordSteps.filter(s => s.phase === phase)
    : recordSteps;

  let sectionsHtml;
  if (phase) {
    // 指定阶段：固定只打这一节（无步骤时打印占位行，与页面口径一致）
    sectionsHtml = buildStepSection(phase, steps);
  } else {
    const {groups, ungrouped} = groupStepsByPhase(steps, phases);
    sectionsHtml = groups.map(g => buildStepSection(g.name, g.steps)).join('');
    if (ungrouped.length > 0) {
      sectionsHtml += buildStepSection('未分组', ungrouped);
    }
  }

  win.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>升级步骤执行清单 - ${escapeHtml(info.title)}</title><style>${STEPS_CSS}</style></head><body><h1>升级步骤执行清单</h1><div class="meta"><div><b>编号：</b>${escapeHtml(info.upgrade_no)}</div><div><b>标题：</b>${escapeHtml(info.title)}</div><div><b>系统：</b>${escapeHtml(info.system_name)}</div><div><b>升级类型：</b>${escapeHtml(info.upgrade_type)}</div><div><b>升级时间：</b>${escapeHtml(info.upgrade_time)}</div><div><b>负责人：</b>${escapeHtml(info.owner)}</div><div><b>状态：</b>${escapeHtml(info.status)}</div></div>${sectionsHtml || '<div style="text-align:center;padding:20px;">暂无步骤</div>'}<div class="sign"><div>执行人签字：________________</div><div>使用部门确认：________________</div></div><div class="footer">打印时间：${new Date().toLocaleString()}</div><div class="no-print"><button onclick="window.print()">打印</button><button onclick="window.close()">关闭</button></div></body></html>`);
  win.document.close();
  schedulePrint(win);
  return true;
}

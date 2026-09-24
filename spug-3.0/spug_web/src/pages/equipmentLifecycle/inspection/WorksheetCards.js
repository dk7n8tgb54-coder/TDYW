/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 今日巡检工作台的展示卡片（合并矩阵表改造）：
 * - HeaderCard：值班日 / 巡检模板 / 值班人员（仅手输姓名）与"开始巡检"入口；
 * - SheetMatrixCard：单张四轮巡检矩阵表（检查项目 | 检查内容 | 四个固定轮次），
 *   卡片头部 = 单号信息 + 轮次选择 + 一键正常/记录本轮/提交巡检单/作废按钮；
 *   不再区分"填写表格"与"记录回显表格"两套渲染；
 * - 底色只跟随当前选择的轮次列：未记录轮次整列浅黄可编辑；选中已记录轮次时
 *   已填单元格浅蓝只读；未选中的列无论是否已记录都无底色；异常单元格浅红；
 * - 表格均为列式布局：第一列检查项目（连续同项目合并单元格）、第二列检查内容。
 * 组件只读 props 不直接读取 store，保证 observable 读取发生在 observer 顶层组件。
 */
import React from 'react';
import {
  Button, Card, Col, DatePicker, Input, Radio, Row, Select, Tag, Tooltip,
} from 'antd';
import moment from 'moment';
import {AuthButton} from 'components';
import {
  ABNORMAL_VALUE, DISPOSITION_TEXT, INSPECTION_ROUNDS, PERM_I,
  SHEET_STATUS_COLOR, SHEET_STATUS_TEXT, NORMAL_ABNORMAL_CHOICES,
} from './constants';
import {withProjectSpans} from './tableUtils';

function groupRecordsByRound(records) {
  // 记录回收：轮次 → {recordKey: record}（recordKey 用模板项 id / 临时加项键）
  const recordsByRound = {};
  (records || []).forEach(r => {
    const key = r.template_item ? `t_${r.template_item}` : `m_${r.client_key || r.id}`;
    recordsByRound[r.round_no] = recordsByRound[r.round_no] || {};
    recordsByRound[r.round_no][key] = r;
  });
  return recordsByRound;
}

function buildMatrixRows(sheet, template) {
  // 矩阵行：模板设备×检查内容在前，历史临时加项记录排后（当前页面已无新增入口）
  const rows = [];
  (template ? template.devices : []).forEach(device => {
    (device.items || []).forEach(item => {
      rows.push({
        key: `t_${item.id}`, project: device.device_name,
        content: item.name, item,
      });
    });
  });
  const tempKeys = {};
  (sheet.records || []).forEach(r => {
    if (!r.is_temporary) return;
    const key = `m_${r.client_key || r.id}`;
    if (!tempKeys[key]) {
      tempKeys[key] = true;
      rows.push({key, project: r.device_name || '临时检查项', content: r.item_name, item: null});
    }
  });
  return rows;
}

function ValueControl({item, value, onChange}) {
  if (item.input_type === 'choice') {
    return (
      <Select
        style={{width: 120}}
        allowClear
        placeholder="正常 / 不正常"
        value={value || undefined}
        onChange={v => onChange(v || '')}
      >
        {NORMAL_ABNORMAL_CHOICES.map(c => (
          <Select.Option value={c} key={c}>{c}</Select.Option>
        ))}
      </Select>
    );
  }
  return (
    <Input
      style={{width: 140}}
      placeholder="请输入"
      value={value || ''}
      onChange={e => onChange(e.target.value)}
    />
  );
}

function RecordValue({record, isSubmitted, onConvert}) {
  const color = record.result === 'abnormal' ? 'red' : 'inherit';
  const showConvertBtns = isSubmitted && record.result === 'abnormal' &&
    record.disposition && record.disposition.status === 'none';
  const showDispositionTag = isSubmitted && record.result === 'abnormal' &&
    record.disposition && record.disposition.status !== 'none';
  return (
    <span>
      <span style={{color}}>
        {record.value_text || '—'}
        {record.onsite_action ? `（${record.onsite_action}）` : ''}
      </span>
      {showConvertBtns && (
        <span>
          <AuthButton auth={PERM_I.HANDLE} type="link" size="small" style={{padding: 0}}
                      onClick={() => onConvert({type: 'fault', record})}>
            转故障
          </AuthButton>
          <AuthButton auth={PERM_I.HANDLE} type="link" size="small" style={{padding: 0}}
                      onClick={() => onConvert({type: 'work_order', record})}>
            转工单
          </AuthButton>
        </span>
      )}
      {showDispositionTag && <Tag>{DISPOSITION_TEXT[record.disposition.status]}</Tag>}
    </span>
  );
}

function RoundCell({item, record, editable, highlightRecorded, value, onChange,
                     isSubmitted, onConvert}) {
  const cls = ['el-ins-round-cell'];
  const abnormal = editable
    ? value.value_text === ABNORMAL_VALUE
    : !!(record && record.result === 'abnormal');
  if (editable) cls.push('el-ins-cell-current');
  else if (record && highlightRecorded) cls.push('el-ins-cell-recorded');
  if (abnormal) cls.push('el-ins-cell-abnormal');
  return (
    <td className={cls.join(' ')}>
      {editable ? (
        <span>
          <ValueControl item={item} value={value.value_text}
                        onChange={val => onChange(`t_${item.id}`, 'value_text', val)}/>
          {value.value_text === ABNORMAL_VALUE && (
            <Input
              size="small"
              style={{marginTop: 4}}
              placeholder="现场处理内容"
              value={value.onsite_action || ''}
              onChange={e => onChange(`t_${item.id}`, 'onsite_action', e.target.value)}
            />
          )}
        </span>
      ) : record ? (
        <RecordValue record={record} isSubmitted={isSubmitted} onConvert={onConvert}/>
      ) : (
        <span style={{color: '#ddd'}}>—</span>
      )}
    </td>
  );
}

function LegendChip({className, text}) {
  return (
    <span style={{marginLeft: 12, fontWeight: 'normal'}}>
      <span className={`el-ins-legend-chip ${className}`}/>
      {text}
    </span>
  );
}

function HeaderCard({dutyDate, onDutyDateChange, templateId, onTemplateChange,
                     persons, onPersonsChange, templates, users, sheet,
                     hasTemplate, isVoid, onStart}) {
  return (
    <Card size="small" style={{marginBottom: 12}}>
      <Row gutter={12}>
        <Col>
          <span>值班日：</span>
          <DatePicker
            value={dutyDate ? moment(dutyDate) : null}
            format="YYYY-MM-DD"
            allowClear={false}
            onChange={d => onDutyDateChange(d ? d.format('YYYY-MM-DD') : dutyDate)}
          />
          <Tooltip title="第四轮（次日 06:30）发生在下一自然日，请回选前一值班日填写">
            <a style={{marginLeft: 6}}>跨夜说明</a>
          </Tooltip>
        </Col>
        <Col>
          <span>巡检模板：</span>
          <Select
            style={{width: 240}}
            placeholder="请选择巡检模板"
            value={templateId}
            onChange={onTemplateChange}
          >
            {templates.map(t => (
              <Select.Option value={t.id} key={t.id}>{t.name}</Select.Option>
            ))}
          </Select>
        </Col>
        <Col>
          <span>值班人员：</span>
          {/* open=false：仅手输姓名（回车/失焦添加），不再提供账号下拉选择；
              options 仅用于历史草稿中账号值的姓名回显 */}
          <Select
            mode="tags"
            open={false}
            style={{width: 300}}
            placeholder="输入姓名后回车确认（可多个）"
            value={persons}
            onChange={onPersonsChange}
          >
            {users.map(u => (
              <Select.Option value={String(u.id)} key={u.id}>
                {u.nickname || u.username}
              </Select.Option>
            ))}
          </Select>
        </Col>
      </Row>
      {!sheet && hasTemplate && (
        <div style={{marginTop: 12}}>
          <span style={{color: '#999'}}>
            当日（{dutyDate}）尚无此模板的巡检单：
          </span>
          <Button type="primary" onClick={onStart}>开始巡检</Button>
        </div>
      )}
      {isVoid && <div style={{marginTop: 12}}><Tag>已作废</Tag> 该巡检单已作废，请重新开始巡检。</div>}
    </Card>
  );
}

function SheetMatrixCard({sheet, template, currentRound, recordedRounds, editable,
                          values, onRoundChange, onValueChange,
                          onFillNormal, onRecord, onSubmit, onVoid, onConvert}) {
  const isSubmitted = sheet.status === 'submitted';
  const recordsByRound = groupRecordsByRound(sheet.records);
  const rows = buildMatrixRows(sheet, template);
  return (
    <Card
      size="small"
      title={
        <span>
          巡检单 {sheet.sheet_no}
          <Tag style={{marginLeft: 8}} color={SHEET_STATUS_COLOR[sheet.status]}>
            {SHEET_STATUS_TEXT[sheet.status]}
          </Tag>
          <span style={{color: '#999', marginLeft: 8, fontWeight: 'normal'}}>
            值班日 {sheet.duty_date}｜模板：{sheet.template_name}
            ｜值班人员：{sheet.persons.length
            ? sheet.persons.map(p => p.person_name).join('、') : '（未登记）'}
          </span>
          {editable && (
            <span>
              <LegendChip className="el-ins-legend-current" text="当前填写"/>
              <LegendChip className="el-ins-legend-recorded" text="已记录"/>
              <LegendChip className="el-ins-legend-abnormal" text="异常"/>
            </span>
          )}
        </span>
      }
      extra={
        editable ? (
          <span>
            记录轮次：
            <Radio.Group
              style={{marginLeft: 8}}
              value={currentRound}
              onChange={e => onRoundChange(e.target.value)}
            >
              {INSPECTION_ROUNDS.map(r => (
                <Radio.Button value={r.value} key={r.value}>{r.label}</Radio.Button>
              ))}
            </Radio.Group>
            <AuthButton auth={PERM_I.EDIT} style={{marginLeft: 8}} onClick={onFillNormal}>
              一键正常
            </AuthButton>
            <AuthButton auth={PERM_I.EDIT} type="primary" style={{marginLeft: 8}} onClick={onRecord}>
              记录本轮
            </AuthButton>
            <AuthButton auth={PERM_I.SUBMIT} style={{marginLeft: 8}} onClick={onSubmit}>
              提交巡检单
            </AuthButton>
            <AuthButton auth={PERM_I.DEL} style={{marginLeft: 8}} onClick={onVoid}>
              作废
            </AuthButton>
          </span>
        ) : null
      }>
      <div className="el-ins-matrix-wrap">
        <table className="el-ins-recap-table el-ins-matrix">
          <thead>
          <tr>
            <th className="el-ins-col-project">检查项目</th>
            <th className="el-ins-col-content">检查内容</th>
            {INSPECTION_ROUNDS.map(r => <th key={r.value}>{r.label}</th>)}
          </tr>
          </thead>
          <tbody>
          {withProjectSpans(rows).map(({item, isGroupStart, span}) => (
            <tr key={item.key}>
              {isGroupStart
                ? <td className="el-ins-col-project" rowSpan={span}>{item.project}</td>
                : null}
              <td className="el-ins-col-content">{item.content}</td>
              {INSPECTION_ROUNDS.map(r => (
                <RoundCell
                  key={r.value}
                  item={item.item}
                  record={(recordsByRound[r.value] || {})[item.key]}
                  editable={!!(editable && item.item && r.value === currentRound &&
                    !(recordedRounds || []).includes(r.value))}
                  highlightRecorded={!!editable && r.value === currentRound}
                  value={(values[r.value] || {})[item.key] || {}}
                  onChange={onValueChange}
                  isSubmitted={isSubmitted} onConvert={onConvert}/>
              ))}
            </tr>
          ))}
          </tbody>
        </table>
      </div>
      {isSubmitted && (
        <div style={{color: '#999', marginTop: 8}}>
          已提交巡检单不可再修改；异常明细可转故障/工单（转换时需选择系统）。
        </div>
      )}
    </Card>
  );
}

export {HeaderCard, SheetMatrixCard};

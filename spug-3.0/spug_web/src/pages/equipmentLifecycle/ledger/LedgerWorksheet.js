/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 常驻运维工作台（"一日一账"的常驻页形态，首期接入巡检台账）：
 * - 一日一张台账：对齐纸质台账"拿出本子填写"的习惯——每次检查填好当前
 *   区域点"记录本次检查"，追加进当日同一张草稿台账（明细各带实际执行
 *   时刻 executed_at，作为同日多轮的区分依据），写完一天点"提交台账"
 *   一次性转入待复核；列表/复核/导出都以天为粒度；
 * - 打开即填：按上次使用的模板展开明细（模板自动覆盖全部未停用电台）；
 *   挂载时恢复当日草稿台账的已记录轮次（只读网格回显，一页见全天）；
 * - 表头默认：实际执行日期=今天（无草稿时改日期即补录）、执行人=当前
 *   登录人、检查时刻=当前时间（每次记录后自动刷新为当前时刻，补录可改）；
 * - 未记录的当前轮填写过程暂存浏览器本地（localStorage，按用户+台账类型
 *   隔离，不跨设备），已记录轮次以服务器草稿台账为准；
 * - 动作语义：旧版"提交立账"实际创建的是草稿却提示"已提交待复核"，本版
 *   将"记录（累积进草稿）"与"提交（转入待复核）"显式分为两个动作；
 * - 模板组合可调整，只影响后续轮次；模板后续修改不影响已记录明细（快照）。
 */
import React from 'react';
import {Alert, Button, Collapse, Divider, Form, Input, Modal, Select, message} from 'antd';
import {DeleteOutlined, PlusOutlined, SettingOutlined} from '@ant-design/icons';
import {http} from 'libs';
import {AuthDiv, AuthButton, Breadcrumb} from 'components';
import {API_PREFIX_L, LEDGER_TYPE, LEDGER_TYPE_TEXT, PERM_L} from './constants';
import {
  buildAccumulatedEntries, expandTemplateEntries, makeRow, nowTimeStr,
  normalizeTemplateEntries, roundsFromDetail, rowsFromPreview, rowLooksAbnormal, todayStr,
} from './ledgerCommon';
import LedgerRowsTable from './LedgerRowsTable';
import LedgerRoundsGrid from './LedgerRoundsGrid';

const {Panel} = Collapse;
const {Option} = Select;

function newClientToken() {
  return `ws_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function storageKey(kind, ledgerType) {
  const nickname = sessionStorage.getItem('nickname') || 'anonymous';
  return `el_ledger_ws_${kind}_${ledgerType}_${encodeURIComponent(nickname)}`;
}

function readStorage(key) {
  try {
    return JSON.parse(window.localStorage.getItem(key) || 'null');
  } catch (e) {
    return null;
  }
}

// 当前轮是否已有填写内容（填写值/临时项名称）：空骨架不入暂存，
// 避免"刚记录重建的空表"被当成未提交草稿在下次打开时误报恢复
function rowsHaveContent(rows) {
  return rows.some(r => (
    r.value_text || r.value_number !== null || r.value_bool !== null
    || (r.is_temporary && r.item_name)
  ));
}

class LedgerWorksheet extends React.Component {
  state = {
    loading: false,
    systems: [],
    templates: [],
    templateEntries: [],
    adjustVisible: false,     // 模板组合调整区
    rows: [],                 // 本次填写（未记录）的明细行
    cycle: undefined,
    header: {
      executed_date: todayStr(),
      executor_names: sessionStorage.getItem('nickname') || '',
    },
    roundTime: nowTimeStr(),  // 本次检查时刻（记录后自动刷新）
    clientToken: '',
    restored: false,          // 本次打开恢复了未提交的填写
    // 当日草稿台账（一日一账：所有轮次累积在同一张上）
    ledgerId: null,
    ledgerNo: '',
    ledgerVersion: null,
    rounds: [],               // 已记录轮次 [{time, rows}]（以服务器为准，只读）
    submittedCount: 0,        // 当日已提交/复核台账数（顶部提示用）
  };

  componentDidMount() {
    // 展开明细需要系统候选（模板自动覆盖全部未停用系统），先加载再引导/展开
    http.get(`${API_PREFIX_L}/systems/`, {params: {page: 1, page_size: 999}})
      .then(res => {
        this.setState({systems: res.data}, () => this.bootstrap());
      })
      .catch(() => this.bootstrap());
    // 巡检不依赖周期，挂载即加载；周月维护接入时按所选周期加载
    this.fetchTemplates().then(templates => this.setState({templates}));
  }

  get isWeekMonth() {
    return this.props.ledgerType === LEDGER_TYPE.WEEK_MONTH;
  }

  get lastKey() {
    return storageKey('last', this.props.ledgerType);
  }

  get draftKey() {
    return storageKey('draft', this.props.ledgerType);
  }

  defaultHeader = () => ({
    executed_date: todayStr(),
    executor_names: sessionStorage.getItem('nickname') || '',
  });

  // ===== 暂存（localStorage，不跨设备；仅当前未记录轮） =====

  saveDraft = () => {
    const {templateEntries, rows, header, roundTime, clientToken} = this.state;
    if (!rowsHaveContent(rows)) {
      // 空表（首次进入/刚记录重建/仅骨架）不产生草稿
      window.localStorage.removeItem(this.draftKey);
      return;
    }
    window.localStorage.setItem(this.draftKey, JSON.stringify({
      templateEntries,
      rows,
      header,
      round_time: roundTime,
      client_token: clientToken,
      saved_at: Date.now(),
    }));
  };

  writeLastTemplates = () => {
    window.localStorage.setItem(this.lastKey, JSON.stringify({
      templateEntries: this.state.templateEntries,
    }));
  };

  // ===== 当日台账状态 =====

  /**
   * 查询当日台账：取最新一张草稿详情用于轮次还原，并统计已提交/复核张数。
   * 列表按 -created_at 排序，草稿取第一张；查询失败按无草稿处理。
   */
  fetchTodayState = () => {
    const today = todayStr();
    return http.get(`${API_PREFIX_L}/ledgers/`, {
      params: {
        ledger_type: this.props.ledgerType,
        executed_from: today, executed_to: today,
        page: 1, page_size: 100,
      },
    }).then(res => {
      const records = (res && res.data) || [];
      const drafts = records.filter(r => r.status === 'draft');
      const submittedCount = records.filter(r => r.status !== 'draft').length;
      if (!drafts.length) return {draftDetail: null, submittedCount};
      return http.get(`${API_PREFIX_L}/ledgers/${drafts[0].id}/`).then(detail => ({
        draftDetail: detail || null,
        submittedCount,
      })).catch(() => ({draftDetail: null, submittedCount}));
    }).catch(() => ({draftDetail: null, submittedCount: 0}));
  };

  // ===== 展开/恢复 =====

  bootstrap = () => {
    this.fetchTodayState().then(({draftDetail, submittedCount}) => {
      const draft = readStorage(this.draftKey);
      const localDate = draft && draft.header ? draft.header.executed_date : null;
      const serverDate = draftDetail ? draftDetail.executed_date : null;
      if (draftDetail) {
        // 当日已有草稿台账：还原已记录轮次，继续在同一张上累积
        const serverHeader = {
          executed_date: serverDate || todayStr(),
          executor_names: draftDetail.executor_names || sessionStorage.getItem('nickname') || '',
        };
        const localUsable = draft && Array.isArray(draft.rows) && draft.rows.length
          && (!localDate || !serverDate || localDate === serverDate);
        if (localUsable) {
          // 同时恢复未记录完的当前轮与已记录轮次
          this.setState({
            rounds: roundsFromDetail(draftDetail),
            ledgerId: draftDetail.id,
            ledgerNo: draftDetail.ledger_no,
            ledgerVersion: draftDetail.version,
            submittedCount,
            rows: draft.rows,
            templateEntries: normalizeTemplateEntries(draft.templateEntries),
            header: {...serverHeader, ...draft.header, executed_date: serverHeader.executed_date},
            roundTime: draft.round_time || nowTimeStr(),
            clientToken: draft.client_token || newClientToken(),
            restored: true,
          });
          return;
        }
        if (localDate && serverDate && localDate !== serverDate) {
          // 本地暂存属于其他日期（跨日残留），弃用
          window.localStorage.removeItem(this.draftKey);
        }
        const last = readStorage(this.lastKey);
        const entries = last && Array.isArray(last.templateEntries)
          ? normalizeTemplateEntries(last.templateEntries) : [];
        if (entries.length) {
          this.setState({
            rounds: roundsFromDetail(draftDetail),
            ledgerId: draftDetail.id,
            ledgerNo: draftDetail.ledger_no,
            ledgerVersion: draftDetail.version,
            submittedCount,
            header: serverHeader,
          }, () => this.buildSheet(entries));
        } else {
          this.setState({
            rounds: roundsFromDetail(draftDetail),
            ledgerId: draftDetail.id,
            ledgerNo: draftDetail.ledger_no,
            ledgerVersion: draftDetail.version,
            submittedCount,
            header: serverHeader,
            adjustVisible: true,
          });
        }
        return;
      }
      // 当日尚无草稿台账：沿用本地暂存 / 上次模板组合 / 引导选择
      if (draft && Array.isArray(draft.rows) && draft.rows.length) {
        // 恢复未提交的填写；跨租户/账号残留的系统行由记录时后端校验兜底
        this.setState({
          rows: draft.rows,
          templateEntries: normalizeTemplateEntries(draft.templateEntries),
          header: {...this.defaultHeader(), ...draft.header},
          roundTime: draft.round_time || nowTimeStr(),
          clientToken: draft.client_token || newClientToken(),
          restored: true,
          submittedCount,
        });
        return;
      }
      const last = readStorage(this.lastKey);
      if (last && Array.isArray(last.templateEntries) && last.templateEntries.length) {
        // normalizeTemplateEntries 兼容旧版 {system_id, template_id} 单配对种子
        const entries = normalizeTemplateEntries(last.templateEntries);
        if (entries.length) {
          this.setState({submittedCount}, () => this.buildSheet(entries));
          return;
        }
      }
      // 从未选择过模板：打开调整区引导选择
      this.setState({adjustVisible: true, submittedCount});
    });
  };

  buildSheet = (templateEntries) => {
    // 模板条目自动覆盖全部未停用电台：展开为 系统×模板 配对（预览接口契约不变）。
    // 仅重建"本次填写"区；表头与已记录轮次由调用方管理，幂等令牌随新表轮换。
    const entries = expandTemplateEntries(templateEntries, this.state.systems);
    if (!entries.length) {
      message.error(templateEntries.some(t => t.template_id)
        ? '系统档案中没有可用系统，请先维护系统'
        : '请先选择模板条目');
      return;
    }
    this.setState({loading: true});
    http.post(`${API_PREFIX_L}/ledgers/preview/`, {
      ledger_type: this.props.ledgerType,
      maintenance_cycle: this.isWeekMonth ? (this.state.cycle || '') : '',
      entries,
    }).then(res => {
      const rows = rowsFromPreview(res.data);
      if (!rows.length) {
        message.warning('所选模板没有与本次周期匹配的项目');
      }
      this.setState({
        rows,
        templateEntries,
        restored: false,
        clientToken: newClientToken(),
      }, () => this.saveDraft());
    }).finally(() => this.setState({loading: false}));
  };

  // ===== 模板组合调整 =====

  addTemplateEntry = () => {
    this.setState(prev => ({
      templateEntries: [...prev.templateEntries, {template_id: undefined}],
    }));
  };

  setTemplateEntry = (index, patch) => {
    this.setState(prev => ({
      templateEntries: prev.templateEntries.map((t, i) => (i === index ? {...t, ...patch} : t)),
    }), () => this.saveDraft());
  };

  removeTemplateEntry = (index) => {
    this.setState(prev => ({
      templateEntries: prev.templateEntries.filter((t, i) => i !== index),
    }), () => this.saveDraft());
  };

  handleApplyTemplates = () => {
    const entries = expandTemplateEntries(this.state.templateEntries, this.state.systems);
    if (!entries.length) {
      message.error(this.state.templateEntries.some(t => t.template_id)
        ? '系统档案中没有可用系统，请先维护系统'
        : '请先选择模板');
      return;
    }
    const hasValues = rowsHaveContent(this.state.rows);
    if (hasValues) {
      Modal.confirm({
        title: '重新展开将清空本次未记录的填写内容',
        content: '工作表将按新模板组合重新展开；已记录的检查不受影响。',
        onOk: () => this.buildSheet(entries),
      });
      return;
    }
    this.buildSheet(entries);
  };

  // ===== 填写 =====

  fetchTemplates = (cycleOverride) => {
    let url = `${API_PREFIX_L}/ledger-templates/available/?ledger_type=${this.props.ledgerType}`;
    const cycle = cycleOverride || this.state.cycle;
    if (this.isWeekMonth && cycle) url += `&maintenance_cycle=${cycle}`;
    return http.get(url).then(res => res.data).catch(() => []);
  };

  setHeader = (key, value) => {
    // 一日一账：已有草稿时更改日期意味着另起一张（原草稿留在原日期，
    // 可在台账列表继续提交），需显式确认，避免误把两个日期混进一张台账
    if (key === 'executed_date' && this.state.ledgerId && value
      && value !== this.state.header.executed_date) {
      Modal.confirm({
        title: '更改实际执行日期将另起一张台账',
        content: `已记录的 ${this.state.rounds.length} 轮检查保留在原日期草稿台账`
          + `（${this.state.ledgerNo}）中，可在台账列表中继续提交；更改后的日期将另起新账记录。`,
        onOk: () => {
          this.setState(prev => ({
            ledgerId: null,
            ledgerNo: '',
            ledgerVersion: null,
            rounds: [],
            header: {...prev.header, executed_date: value},
            clientToken: newClientToken(),
          }), () => this.saveDraft());
        },
      });
      return;
    }
    this.setState(prev => ({header: {...prev.header, [key]: value}}), () => this.saveDraft());
  };

  setRoundTime = (value) => {
    this.setState({roundTime: value}, () => this.saveDraft());
  };

  setRow = (clientKey, patch) => {
    this.setState(prev => ({
      rows: prev.rows.map(r => (r.client_key === clientKey ? {...r, ...patch} : r)),
    }), () => this.saveDraft());
  };

  addManualRow = (systemId) => {
    this.setState(prev => ({
      rows: [...prev.rows, makeRow({system_id: systemId, is_temporary: true})],
    }), () => this.saveDraft());
  };

  removeRow = (clientKey) => {
    this.setState(prev => ({rows: prev.rows.filter(r => r.client_key !== clientKey)}), () => this.saveDraft());
  };

  // ===== 记录 / 提交 =====

  /**
   * 记录本次检查：首轮 POST 创建当日草稿台账，后续 PUT 追加明细
   * （已有明细带 id 保留，新增明细带本轮 executed_at）。成功后以服务器
   * 详情还原已记录轮次、清空当前填写区并刷新检查时刻，等待下一轮。
   */
  handleRecord = () => {
    const {rows, header, roundTime, clientToken, ledgerId, ledgerVersion, rounds} = this.state;
    if (!header.executed_date) {
      message.error('请填写实际执行日期');
      return;
    }
    if (!roundTime) {
      message.error('请填写本次检查时刻');
      return;
    }
    if (!rows.length) {
      message.error('请先展开巡检表');
      return;
    }
    const built = buildAccumulatedEntries(rounds, rows, `${header.executed_date} ${roundTime}`);
    if (built.error) {
      message.error(built.error);
      return;
    }
    const payload = {
      ledger_type: this.props.ledgerType,
      // 巡检固定空周期（周月维护接入时提交所选周期）
      maintenance_cycle: this.isWeekMonth ? (this.state.cycle || '') : '',
      created_from: 'template',
      executed_date: header.executed_date,
      executor_names: header.executor_names,
      client_token: clientToken,
      entries: built.entries,
    };
    this.setState({loading: true});
    const req = ledgerId
      ? http.put(`${API_PREFIX_L}/ledgers/${ledgerId}/`, {...payload, version: ledgerVersion})
      : http.post(`${API_PREFIX_L}/ledgers/`, payload);
    req.then(detail => {
      const nextRounds = roundsFromDetail(detail);
      this.setState({
        rounds: nextRounds,
        ledgerId: detail.id,
        ledgerNo: detail.ledger_no,
        ledgerVersion: detail.version,
        rows: [],
        roundTime: nowTimeStr(),
        restored: false,
        clientToken: newClientToken(),
      }, () => {
        this.saveDraft();
        this.writeLastTemplates();
        this.buildSheet(this.state.templateEntries);
        message.success(`已记录第 ${nextRounds.length} 次检查`);
      });
    }).catch(() => {
      // 业务错误提示由 http 拦截器统一弹出；当前轮填写保留，不重复提示
    }).finally(() => this.setState({loading: false}));
  };

  /**
   * 提交当日台账：草稿转入待复核（submit 后明细不可再编辑）。
   */
  handleSubmitLedger = () => {
    const {ledgerId, templateEntries} = this.state;
    if (!ledgerId) {
      message.error('还没有已记录的检查，请先填写并记录');
      return;
    }
    this.setState({loading: true});
    http.post(`${API_PREFIX_L}/ledgers/${ledgerId}/submit/`)
      .then(() => {
        message.success('今日台账已提交，待复核');
        window.localStorage.removeItem(this.draftKey);
        this.setState(prev => ({
          ledgerId: null,
          ledgerNo: '',
          ledgerVersion: null,
          rounds: [],
          submittedCount: prev.submittedCount + 1,
          header: this.defaultHeader(),
          roundTime: nowTimeStr(),
          clientToken: newClientToken(),
        }), () => this.buildSheet(templateEntries));
      })
      .catch(() => {
        // 业务错误提示由 http 拦截器统一弹出
      })
      .finally(() => this.setState({loading: false}));
  };

  // ===== 渲染 =====

  renderHeader = () => {
    const {header, roundTime} = this.state;
    return (
      <Form layout="inline" style={{marginBottom: 8}}>
        <Form.Item required label="实际执行日期">
          <Input
            style={{width: 130}}
            type="date"
            value={header.executed_date || ''}
            onChange={e => this.setHeader('executed_date', e.target.value)}/>
        </Form.Item>
        <Form.Item required label="检查时刻">
          <Input
            style={{width: 110}}
            type="time"
            value={roundTime || ''}
            onChange={e => this.setRoundTime(e.target.value)}/>
        </Form.Item>
        <Form.Item label="执行人">
          <Input style={{width: 150}} value={header.executor_names} onChange={e => this.setHeader('executor_names', e.target.value)}/>
        </Form.Item>
      </Form>
    );
  };

  renderTemplateBar = () => {
    const {templateEntries, templates, adjustVisible, ledgerId, ledgerNo} = this.state;
    const names = templateEntries
      .filter(t => t.template_id)
      .map(t => {
        const tpl = templates.find(x => x.id === t.template_id);
        return tpl ? tpl.name : `模板 #${t.template_id}`;
      });
    return (
      <div style={{marginBottom: 8}}>
        <span style={{color: '#666'}}>当前模板：</span>
        {names.length ? <span>{names.join('、')}</span> : <span style={{color: '#f5222d'}}>未选择模板</span>}
        {ledgerId && <span style={{marginLeft: 12, color: '#888'}}>当日台账：{ledgerNo}（草稿）</span>}
        <Button
          size="small" style={{marginLeft: 12}}
          icon={<SettingOutlined/>}
          onClick={() => this.setState(prev => ({adjustVisible: !prev.adjustVisible}))}>
          {adjustVisible ? '收起调整' : '调整模板组合'}
        </Button>
      </div>
    );
  };

  renderAdjustSection = () => {
    const {templateEntries, templates} = this.state;
    return (
      <div style={{marginBottom: 12, padding: 8, background: '#fafafa', borderRadius: 4}}>
        {templateEntries.map((entry, index) => {
          return (
            <div key={index} style={{marginBottom: 4}}>
              <div style={{marginBottom: 4}}>
                <Select
                  style={{width: 240, marginRight: 8}} placeholder="选择模板"
                  value={entry.template_id}
                  onChange={v => this.setTemplateEntry(index, {template_id: v})}>
                  {templates.map(t => (
                    <Option value={t.id} key={t.id}>{t.name}</Option>
                  ))}
                </Select>
                <Button icon={<DeleteOutlined/>} onClick={() => this.removeTemplateEntry(index)}/>
              </div>
            </div>
          );
        })}
        <div>
          <Button size="small" icon={<PlusOutlined/>} onClick={this.addTemplateEntry}>添加模板条目</Button>
          <Button size="small" type="primary" ghost style={{marginLeft: 8}} onClick={this.handleApplyTemplates}>
            应用并展开
          </Button>
        </div>
      </div>
    );
  };

  renderManualSection = () => {
    const {systems} = this.state;
    return (
      <div style={{marginTop: 8, color: '#666', fontSize: 12}}>
        临时增加检查项：
        {systems.map(s => (
          <Button
            key={s.id} size="small" type="dashed"
            style={{marginRight: 8, marginBottom: 4}}
            onClick={() => this.addManualRow(s.id)}>
            + {s.name}
          </Button>
        ))}
      </div>
    );
  };

  render() {
    const {rows, rounds, loading, systems, restored, adjustVisible} = this.state;
    const groups = [];
    const groupMap = {};
    rows.forEach(r => {
      const system = systems.find(s => s.id === r.system_id);
      const key = String(r.system_id);
      if (!groupMap[key]) {
        groupMap[key] = {
          system_id: r.system_id,
          label: system ? `${system.name}（${system.install_location}）` : `系统 #${r.system_id}`,
          rows: [],
        };
        groups.push(groupMap[key]);
      }
      groupMap[key].rows.push(r);
    });
    const hasTemplates = this.state.templates.length > 0;
    const typeText = LEDGER_TYPE_TEXT[this.props.ledgerType];
    return (
      <AuthDiv auth={PERM_L.LED_VIEW}>
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
          <Breadcrumb.Item>运行维护</Breadcrumb.Item>
          <Breadcrumb.Item>今日{typeText}</Breadcrumb.Item>
        </Breadcrumb>
        {restored && (
          <Alert
            type="info" showIcon style={{marginBottom: 8}}
            message="已恢复上次未提交的填写内容（暂存仅保存在本机浏览器）"/>
        )}
        {this.state.submittedCount > 0 && (
          <Alert
            type="info" showIcon style={{marginBottom: 8}}
            message={`今日已有 ${this.state.submittedCount} 张已提交/复核的${typeText}台账；本次"记录"将另起一张新台账。`}/>
        )}
        {this.renderHeader()}
        {this.renderTemplateBar()}
        {adjustVisible && this.renderAdjustSection()}
        {!adjustVisible && !this.state.templateEntries.length && (
          <div style={{marginBottom: 12, color: '#999', fontSize: 12}}>
            {hasTemplates
              ? '点击"调整模板组合"选择巡检模板，展开今日巡检表（自动覆盖全部未停用电台）；选择一次后每天打开即填。'
              : '请先在"台账模板"中配置巡检模板，再在调整区选择模板。'}
          </div>
        )}
        {rounds.length > 0 && (
          <div style={{marginBottom: 12}}>
            <div style={{marginBottom: 6, color: '#666'}}>
              已记录的检查（{rounds.length} 次）——同一天的多次检查累积在同一张台账
            </div>
            <LedgerRoundsGrid rounds={rounds} systems={systems}/>
          </div>
        )}
        {groups.length > 0 && (
          <div style={{marginBottom: 4, color: '#666', fontSize: 12}}>本次检查填写（记录后清空，进入上方已记录区）</div>
        )}
        {groups.length > 0 ? (
          <Collapse defaultActiveKey={groups.map(g => String(g.system_id))}>
            {groups.map(g => (
              <Panel
                header={g.label}
                key={String(g.system_id)}
                extra={
                  <span>
                    {g.rows.length} 项
                    {g.rows.some(r => rowLooksAbnormal(r)) && (
                      <span style={{color: '#f5222d', marginLeft: 8}}>
                        异常 {g.rows.filter(r => rowLooksAbnormal(r)).length}
                      </span>
                    )}
                  </span>
                }>
                <LedgerRowsTable rows={g.rows} onSetRow={this.setRow} onRemoveRow={this.removeRow}/>
              </Panel>
            ))}
          </Collapse>
        ) : null}
        {rows.length > 0 && this.renderManualSection()}
        <Divider style={{margin: '12px 0 8px'}}/>
        <div style={{textAlign: 'center'}}>
          <AuthButton auth={this.state.ledgerId ? PERM_L.LED_EDIT : PERM_L.LED_ADD}>
            <Button
              type="primary" size="large" loading={loading}
              style={{width: 200}}
              onClick={this.handleRecord}>
              记录本次检查
            </Button>
          </AuthButton>
          {this.state.ledgerId && (
            <AuthButton auth={PERM_L.LED_SUBMIT}>
              <Button
                size="large" loading={loading}
                style={{width: 200, marginLeft: 16}}
                onClick={this.handleSubmitLedger}>
                提交{typeText}台账
              </Button>
            </AuthButton>
          )}
        </div>
      </AuthDiv>
    );
  }
}

export default LedgerWorksheet;
export {LedgerWorksheet};
